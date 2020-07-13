from sqlalchemy.ext.hybrid import hybrid_property

from baseframe import __
from coaster.sqlalchemy import StateManager, with_roles
from coaster.utils import LabeledEnum, valid_username

from . import BaseMixin, MarkdownColumn, TSVectorType, UrlType, UuidMixin, db
from .helpers import RESERVED_NAMES, add_search_trigger
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
    Profiles are the public-facing pages for the User and Organization models.
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

    description = MarkdownColumn('description', default='', nullable=False)
    logo_url = db.Column(UrlType, nullable=True)
    banner_image_url = db.Column(UrlType, nullable=True)
    #: Legacy profiles are available via funnelapp, non-legacy in the main app
    legacy = db.Column(db.Boolean, default=False, nullable=False)

    search_vector = db.deferred(
        db.Column(
            TSVectorType(
                'name',
                'description_text',
                weights={'name': 'A', 'description_text': 'B'},
                regconfig='english',
                hltext=lambda: db.func.concat_ws(
                    ' / ', Profile.title, Profile.description_html
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
                'logo_url',
                'user',
                'organization',
                'banner_image_url',
            },
            'call': {'url_for', 'features', 'forms'},
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
            'user',
            'organization',
        },
        'related': {'urls', 'uuid_b58', 'name', 'title', 'description', 'logo_url'},
    }

    def __repr__(self):
        return f'<Profile "{self.name}">'

    @property
    def owner(self):
        return self.user or self.organization

    @owner.setter
    def owner(self, value):
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
    def title(self):
        if self.user:
            return self.user.fullname
        elif self.organization:
            return self.organization.title
        else:
            return ''

    @title.setter
    def title(self, value):
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

    def roles_for(self, actor, anchors=()):
        if self.owner:
            roles = self.owner.roles_for(actor, anchors)
        else:
            roles = super().roles_for(actor, anchors)
        if self.state.PUBLIC:
            roles.add('reader')
        return roles

    @classmethod
    def get(cls, name):
        return cls.query.filter(
            db.func.lower(Profile.name) == db.func.lower(name)
        ).one_or_none()

    @classmethod
    def validate_name_candidate(cls, name):
        """
        Check if a name is available, returning one of several error codes, or None if
        all is okay:

        * ``blank``: No name supplied
        * ``invalid``: Invalid characters in name
        * ``long``: Name is longer than allowed size
        * ``reserved``: Name is reserved
        * ``user``: Name is assigned to a user
        * ``org``: Name is assigned to an organization
        """
        if not name:
            return 'blank'
        elif name in RESERVED_NAMES:
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
        if existing:
            if existing.reserved:
                return 'reserved'
            elif existing.user_id:
                return 'user'
            elif existing.organization_id:
                return 'org'

    @classmethod
    def is_available_name(cls, name):
        return cls.validate_name_candidate(name) is None

    @db.validates('name')
    def validate_name(self, key, value):
        if value in RESERVED_NAMES or not valid_username(value):
            raise ValueError("Invalid account name: " + value)
        # We don't check for existence in the db since this validator only
        # checks for valid syntax. To confirm the name is actually available,
        # the caller must call :meth:`is_available_name` or attempt to commit
        # to the db and catch IntegrityError.
        return value

    @classmethod
    def migrate_user(cls, old_user, new_user):
        if old_user.profile and not new_user.profile:
            # New user doesn't have a profile. Simply transfer ownership.
            new_user.profile = old_user.profile
        elif old_user.profile and new_user.profile:
            # Both have profiles. Move everything that refers to old profile
            done = do_migrate_instances(
                old_user.profile, new_user.profile, 'migrate_profile'
            )
            if done:
                db.session.delete(old_user.profile)

    @property
    def teams(self):
        if self.organization:
            return self.organization.teams
        else:
            return []

    def permissions(self, user, inherited=None):
        perms = super(Profile, self).permissions(user, inherited)
        perms.add('view')
        if 'admin' in self.roles_for(user):
            perms.add('edit-profile')
            perms.add('new_project')
            perms.add('delete-project')
            perms.add('edit_project')
        return perms

    @with_roles(call={'owner'})
    @state.transition(None, state.PUBLIC, title=__("Make public"))
    def make_public(self):
        pass

    @with_roles(call={'owner'})
    @state.transition(None, state.PRIVATE, title=__("Make private"))
    def make_private(self):
        pass


add_search_trigger(Profile, 'search_vector')
