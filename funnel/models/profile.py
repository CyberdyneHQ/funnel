from __future__ import annotations

from typing import Iterable, List, Optional, Set, Union

from baseframe import __
from coaster.sqlalchemy import Query, StateManager, immutable, with_roles
from coaster.utils import LabeledEnum

from ..typing import OptionalMigratedTables
from . import (
    BaseMixin,
    MarkdownColumn,
    TSVectorType,
    UrlType,
    UuidMixin,
    db,
    hybrid_property,
)
from .helpers import (
    RESERVED_NAMES,
    ImgeeType,
    add_search_trigger,
    markdown_content_options,
    valid_username,
    visual_field_delimiter,
)
from .user import Organization, User
from .utils import do_migrate_instances

__all__ = ['Profile']


class PROFILE_STATE(LabeledEnum):  # NOQA: N801
    AUTO = (0, 'auto', __("Autogenerated"))
    PUBLIC = (1, 'public', __("Public"))
    PRIVATE = (2, 'private', __("Private"))


# This model does not use BaseNameMixin because it has no title column. The title comes
# from the linked User or Organization
class Profile(UuidMixin, BaseMixin, db.Model):
    """
    Public-facing profiles for :class:`User` and :class:`Organization` models.

    Profiles hold the account name in a shared namespace between these models (aka
    "username"), and also host projects and other future document types.
    """

    __tablename__ = 'profile'
    __uuid_primary_key__ = False
    # length limit 63 to fit DNS label limit
    __name_length__ = 63
    reserved_names = RESERVED_NAMES

    #: The "username" assigned to a user or organization.
    #: Length limit 63 to fit DNS label limit
    name = db.Column(
        db.Unicode(__name_length__),
        db.CheckConstraint("name <> ''"),
        nullable=False,
        unique=True,
    )
    # Only one of the following three may be set:
    #: User that owns this name (limit one per user)
    user_id = db.Column(
        None, db.ForeignKey('user.id', ondelete='SET NULL'), unique=True, nullable=True
    )

    # No `cascade='delete-orphan'` in User and Organization backrefs as profiles cannot
    # be trivially deleted

    user = with_roles(
        db.relationship(
            'User',
            lazy='joined',
            backref=db.backref('profile', lazy='joined', uselist=False, cascade='all'),
        ),
        grants={'owner'},
    )
    #: Organization that owns this name (limit one per organization)
    organization_id = db.Column(
        None,
        db.ForeignKey('organization.id', ondelete='SET NULL'),
        unique=True,
        nullable=True,
    )
    organization = db.relationship(
        'Organization',
        lazy='joined',
        backref=db.backref('profile', lazy='joined', uselist=False, cascade='all'),
    )
    #: Reserved profile (not assigned to any party)
    reserved = db.Column(db.Boolean, nullable=False, default=False, index=True)

    _state = db.Column(
        'state',
        db.Integer,
        StateManager.check_constraint('state', PROFILE_STATE),
        nullable=False,
        default=PROFILE_STATE.AUTO,
    )
    state = StateManager('_state', PROFILE_STATE, doc="Current state of the profile")

    description = MarkdownColumn(
        'description', default='', nullable=False, options=markdown_content_options
    )
    website = db.Column(UrlType, nullable=True)
    logo_url = db.Column(ImgeeType, nullable=True)
    banner_image_url = db.Column(ImgeeType, nullable=True)

    # These two flags are read-only. There is no provision for writing to them within
    # the app:

    #: Protected profiles cannot be deleted
    is_protected = with_roles(
        immutable(db.Column(db.Boolean, default=False, nullable=False)),
        read={'owner', 'admin'},
    )
    #: Verified profiles get a public badge
    is_verified = with_roles(
        immutable(db.Column(db.Boolean, default=False, nullable=False, index=True)),
        read={'all'},
    )

    search_vector = db.deferred(
        db.Column(
            TSVectorType(
                'name',
                'description_text',
                weights={'name': 'A', 'description_text': 'B'},
                regconfig='english',
                hltext=lambda: db.func.concat_ws(
                    visual_field_delimiter, Profile.title, Profile.description_html
                ),
            ),
            nullable=False,
        )
    )

    __table_args__ = (
        db.CheckConstraint(
            db.case([(user_id.isnot(None), 1)], else_=0)
            + db.case([(organization_id.isnot(None), 1)], else_=0)
            + db.case([(reserved.is_(True), 1)], else_=0)
            == 1,
            name='profile_owner_check',
        ),
        db.Index(
            'ix_profile_name_lower',
            db.func.lower(name).label('name_lower'),
            unique=True,
            postgresql_ops={'name_lower': 'varchar_pattern_ops'},
        ),
        db.Index('ix_profile_search_vector', 'search_vector', postgresql_using='gin'),
    )

    __roles__ = {
        'all': {
            'read': {
                'urls',
                'uuid_b58',
                'name',
                'title',
                'description',
                'website',
                'logo_url',
                'user',
                'organization',
                'banner_image_url',
                'is_organization_profile',
                'is_user_profile',
                'owner',
            },
            'call': {'url_for', 'features', 'forms', 'state'},
        }
    }

    __datasets__ = {
        'primary': {
            'urls',
            'uuid_b58',
            'name',
            'title',
            'description',
            'logo_url',
            'website',
            'user',
            'organization',
            'owner',
            'is_verified',
        },
        'related': {
            'urls',
            'uuid_b58',
            'name',
            'title',
            'description',
            'logo_url',
            'is_verified',
        },
    }

    def __repr__(self):
        """Represent :class:`Profile` as a string."""
        return f'<Profile "{self.name}">'

    @property
    def owner(self) -> Union[User, Organization]:
        return self.user or self.organization

    @owner.setter
    def owner(self, value: Union[User, Organization]) -> None:
        if isinstance(value, User):
            self.user = value
            self.organization = None
        elif isinstance(value, Organization):
            self.user = None
            self.organization = value
        else:
            raise ValueError(value)
        self.reserved = False

    @hybrid_property
    def is_user_profile(self) -> bool:
        return self.user_id is not None

    @is_user_profile.expression
    def is_user_profile(cls):  # NOQA: N805
        return cls.user_id.isnot(None)

    @hybrid_property
    def is_organization_profile(self) -> bool:
        return self.organization_id is not None

    @is_organization_profile.expression
    def is_organization_profile(cls):  # NOQA: N805
        return cls.organization_id.isnot(None)

    @property
    def is_public(self) -> bool:
        return bool(self.state.PUBLIC)

    with_roles(is_public, read={'all'})

    @hybrid_property
    def title(self) -> str:
        if self.user:
            return self.user.fullname
        elif self.organization:
            return self.organization.title
        else:
            return ''

    @title.setter
    def title(self, value: str) -> None:
        if self.user:
            self.user.fullname = value
        elif self.organization:
            self.organization.title = value
        else:
            raise ValueError("Reserved profiles do not have titles")

    @title.expression
    def title(cls):  # NOQA: N805
        return db.case(
            [
                (
                    # if...
                    cls.user_id.isnot(None),
                    # then...
                    db.select([User.fullname])
                    .where(cls.user_id == User.id)
                    .as_scalar(),
                ),
                (
                    # elif...
                    cls.organization_id.isnot(None),
                    # then...
                    db.select([Organization.title])
                    .where(cls.organization_id == Organization.id)
                    .as_scalar(),
                ),
            ],
            else_='',
        )

    def roles_for(self, actor: Optional[User], anchors: Iterable = ()) -> Set:
        if self.owner:
            roles = self.owner.roles_for(actor, anchors)
        else:
            roles = super().roles_for(actor, anchors)
        if self.state.PUBLIC:
            roles.add('reader')
        return roles

    @classmethod
    def get(cls, name: str) -> Optional[Profile]:
        return cls.query.filter(
            db.func.lower(Profile.name) == db.func.lower(name)
        ).one_or_none()

    @classmethod
    def all_public(cls) -> Query:
        return cls.query.filter(cls.state.PUBLIC)

    @classmethod
    def validate_name_candidate(cls, name: str) -> Optional[str]:
        """
        Validate an account name candidate.

        Returns one of several error codes, or `None` if all is okay:

        * ``blank``: No name supplied
        * ``reserved``: Name is reserved
        * ``invalid``: Invalid characters in name
        * ``long``: Name is longer than allowed size
        * ``user``: Name is assigned to a user
        * ``org``: Name is assigned to an organization
        """
        if not name:
            return 'blank'
        elif name.lower() in cls.reserved_names:
            return 'reserved'
        elif not valid_username(name):
            return 'invalid'
        elif len(name) > cls.__name_length__:
            return 'long'
        existing = (
            cls.query.filter(db.func.lower(cls.name) == db.func.lower(name))
            .options(
                db.load_only(
                    cls.id, cls.uuid, cls.user_id, cls.organization_id, cls.reserved
                )
            )
            .one_or_none()
        )
        if existing is not None:
            if existing.reserved:
                return 'reserved'
            elif existing.user_id:
                return 'user'
            elif existing.organization_id:
                return 'org'
        return None

    @classmethod
    def is_available_name(cls, name: str) -> bool:
        return cls.validate_name_candidate(name) is None

    @db.validates('name')
    def validate_name(self, key: str, value: str):
        if value.lower() in self.reserved_names or not valid_username(value):
            raise ValueError("Invalid account name: " + value)
        # We don't check for existence in the db since this validator only
        # checks for valid syntax. To confirm the name is actually available,
        # the caller must call :meth:`is_available_name` or attempt to commit
        # to the db and catch IntegrityError.
        return value

    @classmethod
    def migrate_user(cls, old_user: User, new_user: User) -> OptionalMigratedTables:
        if old_user.profile is not None and new_user.profile is None:
            # New user doesn't have a profile. Simply transfer ownership.
            new_user.profile = old_user.profile
        elif old_user.profile is not None and new_user.profile is not None:
            # Both have profiles. Move everything that refers to old profile
            done = do_migrate_instances(
                old_user.profile, new_user.profile, 'migrate_profile'
            )
            if done:
                db.session.delete(old_user.profile)
        # Do nothing if old_user.profile is None and new_user.profile is not None
        return None

    @property
    def teams(self) -> List:
        if self.organization:
            return self.organization.teams
        else:
            return []

    @with_roles(call={'owner'})
    @state.transition(None, state.PUBLIC, title=__("Make public"))
    def make_public(self) -> None:
        pass

    @with_roles(call={'owner'})
    @state.transition(None, state.PRIVATE, title=__("Make private"))
    def make_private(self) -> None:
        pass

    def is_safe_to_delete(self) -> bool:
        """Return True if profile is not protected and has no projects."""
        return self.is_protected is False and self.projects.count() == 0


add_search_trigger(Profile, 'search_vector')
