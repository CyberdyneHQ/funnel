# -*- coding: utf-8 -*-

from urllib.parse import urlparse

from flask import Markup, url_for

from baseframe import _, __
from coaster.utils import domain_namespace_match, getbool, valid_username
from lastuser_core.models import Organization, Permission, User
import baseframe.forms as forms

__all__ = [
    'ClientCredentialForm',
    'ClientTeamAccessForm',
    'ConfirmDeleteForm',
    'PermissionEditForm',
    'PermissionForm',
    'RegisterClientForm',
    'TeamPermissionAssignForm',
    'UserPermissionAssignForm',
]


class ConfirmDeleteForm(forms.Form):
    """
    Confirm a delete operation
    """

    delete = forms.SubmitField(__("Delete"))
    cancel = forms.SubmitField(__("Cancel"))


class RegisterClientForm(forms.Form):
    """
    Register a new OAuth client application
    """

    title = forms.StringField(
        __("Application title"),
        validators=[forms.validators.DataRequired()],
        description=__("The name of your application"),
    )
    description = forms.TextAreaField(
        __("Description"),
        validators=[forms.validators.DataRequired()],
        description=__("A description to help users recognize your application"),
    )
    client_owner = forms.RadioField(
        __("Owner"),
        validators=[forms.validators.DataRequired()],
        description=__(
            "User or organization that owns this application. Changing the owner "
            "will revoke all currently assigned permissions for this app"
        ),
    )
    confidential = forms.RadioField(
        __("Application type"),
        coerce=getbool,
        default=True,
        choices=[
            (
                True,
                __(
                    "Confidential (server-hosted app, capable of storing secret key securely)"
                ),
            ),
            (
                False,
                __(
                    "Public (native or in-browser app, not capable of storing secret key securely)"
                ),
            ),
        ],
    )
    website = forms.URLField(
        __("Application website"),
        validators=[forms.validators.DataRequired(), forms.validators.URL()],
        description=__("Website where users may access this application"),
    )
    namespace = forms.StringField(
        __("Client namespace"),
        validators=[forms.validators.Optional()],
        filters=[forms.filters.none_if_empty()],
        description=Markup(
            __(
                "A dot-based namespace that uniquely identifies your client application. "
                "For example, if your client website is <code>https://auth.hasgeek.com</code>, "
                "use <code>com.hasgeek.auth</code>. Only required if your client app provides resources"
            )
        ),
        widget_attrs={'autocorrect': 'none', 'autocapitalize': 'none'},
    )
    redirect_uris = forms.TextListField(
        __("Redirect URLs"),
        validators=[
            forms.validators.OptionalIf('confidential'),
            forms.ForEach([forms.URL()]),
        ],
        filters=[forms.strip_each()],
        description=__(
            "OAuth2 Redirect URL. If your app is available on multiple hostnames, "
            "list each redirect URL on a separate line"
        ),
    )
    notification_uri = forms.URLField(
        __("Notification URL"),
        validators=[forms.validators.Optional(), forms.validators.URL()],
        description=__(
            "When the user's data changes, Lastuser will POST a notice to this URL. "
            "Other notices may be posted too"
        ),
    )
    allow_any_login = forms.BooleanField(
        __("Allow anyone to login"),
        default=True,
        description=__(
            "If your application requires access to be restricted to specific users, uncheck this, "
            "and only users who have been assigned a permission to the app will be able to login"
        ),
    )
    team_access = forms.BooleanField(
        __("Requires access to teams"),
        default=False,
        description=__(
            "If your application is capable of assigning access permissions to teams, check this. "
            "Organization owners will then able to grant access to teams in their organizations"
        ),
    )

    def validate_client_owner(self, field):
        if field.data == self.edit_user.buid:
            self.user = self.edit_user
            self.org = None
        else:
            orgs = [
                org
                for org in self.edit_user.organizations_owned()
                if org.buid == field.data
            ]
            if len(orgs) != 1:
                raise forms.ValidationError(_("Invalid owner"))
            self.user = None
            self.org = orgs[0]

    def _urls_match(self, url1, url2):
        p1 = urlparse(url1)
        p2 = urlparse(url2)
        return (
            (p1.netloc == p2.netloc)
            and (p1.scheme == p2.scheme)
            and (p1.username == p2.username)
            and (p1.password == p2.password)
        )

    def validate_redirect_uri(self, field):
        if self.confidential.data and not self._urls_match(
            self.website.data, field.data
        ):
            raise forms.ValidationError(
                _("The scheme, domain and port must match that of the website URL")
            )

    def validate_notification_uri(self, field):
        if not self._urls_match(self.website.data, field.data):
            raise forms.ValidationError(
                _("The scheme, domain and port must match that of the website URL")
            )

    def validate_resource_uri(self, field):
        if not self._urls_match(self.website.data, field.data):
            raise forms.ValidationError(
                _("The scheme, domain and port must match that of the website URL")
            )

    def validate_namespace(self, field):
        if field.data:
            if not domain_namespace_match(self.website.data, field.data):
                raise forms.ValidationError(
                    _(
                        "The namespace should be derived from your application’s website domain"
                    )
                )
            client = self.edit_model.get(namespace=field.data)
            if client:
                if client == self.edit_obj:
                    return
                raise forms.ValidationError(
                    _("This namespace has been claimed by another client app")
                )


class ClientCredentialForm(forms.Form):
    """
    Generate new client credentials
    """

    title = forms.StringField(
        __("What’s this for?"),
        validators=[forms.validators.DataRequired(), forms.validators.Length(max=250)],
        description=__(
            "Add a description to help yourself remember why this was generated"
        ),
    )


class PermissionForm(forms.Form):
    """
    Create or edit a permission
    """

    name = forms.StringField(
        __("Permission name"),
        validators=[forms.validators.DataRequired()],
        description=__(
            "Name of the permission as a single word in lower case. "
            "This is passed to the application when a user logs in. "
            "Changing the name will not automatically update it everywhere. "
            "You must reassign the permission to users who had it with the old name"
        ),
        widget_attrs={'autocorrect': 'none', 'autocapitalize': 'none'},
    )
    title = forms.StringField(
        __("Title"),
        validators=[forms.validators.DataRequired()],
        description=__("Permission title that is displayed to users"),
    )
    description = forms.TextAreaField(
        __("Description"),
        description=__("An optional description of what the permission is for"),
    )
    context = forms.RadioField(
        __("Context"),
        validators=[forms.validators.DataRequired()],
        description=__("Context where this permission is available"),
    )

    def validate(self):
        rv = super(PermissionForm, self).validate()
        if not rv:
            return False

        if not valid_username(self.name.data):
            self.name.errors.append(_("Name contains invalid characters"))
            return False

        existing = Permission.get(name=self.name.data, allusers=True)
        if existing and existing.id != self.edit_id:
            self.name.errors.append(
                _("A global permission with that name already exists")
            )
            return False

        if self.context.data == self.edit_user.buid:
            existing = Permission.get(name=self.name.data, user=self.edit_user)
        else:
            org = Organization.get(buid=self.context.data)
            if org:
                existing = Permission.get(name=self.name.data, org=org)
            else:
                existing = None
        if existing and existing.id != self.edit_id:
            self.name.errors.append(_("You have another permission with the same name"))
            return False

        return True

    def validate_context(self, field):
        if field.data == self.edit_user.buid:
            self.user = self.edit_user
            self.org = None
        else:
            orgs = [
                org
                for org in self.edit_user.organizations_owned()
                if org.buid == field.data
            ]
            if len(orgs) != 1:
                raise forms.ValidationError(_("Invalid context"))
            self.user = None
            self.org = orgs[0]


class UserPermissionAssignForm(forms.Form):
    """
    Assign permissions to a user
    """

    user = forms.UserSelectField(
        __("User"),
        validators=[forms.validators.DataRequired()],
        description=__("Lookup a user by their username or email address"),
        lastuser=None,
        usermodel=User,
        autocomplete_endpoint=lambda: url_for('lastuser_oauth.user_autocomplete'),
        getuser_endpoint=lambda: url_for('lastuser_oauth.user_get_by_userids'),
    )
    perms = forms.SelectMultipleField(
        __("Permissions"), validators=[forms.validators.DataRequired()]
    )


class TeamPermissionAssignForm(forms.Form):
    """
    Assign permissions to a team
    """

    team_id = forms.RadioField(
        __("Team"),
        validators=[forms.validators.DataRequired()],
        description=__("Select a team to assign permissions to"),
    )
    perms = forms.SelectMultipleField(
        __("Permissions"), validators=[forms.validators.DataRequired()]
    )

    def validate_team_id(self, field):
        teams = [team for team in self.org.teams if team.buid == field.data]
        if len(teams) != 1:
            raise forms.ValidationError(_("Unknown team"))
        self.team = teams[0]


class PermissionEditForm(forms.Form):
    """
    Edit a user or team's permissions
    """

    perms = forms.SelectMultipleField(
        __("Permissions"), validators=[forms.validators.DataRequired()]
    )


class ClientTeamAccessForm(forms.Form):
    """
    Select organizations that the client has access to the teams of
    """

    organizations = forms.SelectMultipleField(__("Organizations"))
