from __future__ import annotations

from baseframe.forms import render_redirect, render_template
from baseframe.forms.auto import ConfirmDeleteForm
from coaster.auth import current_auth
from coaster.views import (
    ModelView,
    UrlChangeCheck,
    UrlForView,
    render_with,
    requires_roles,
    route,
)

from .. import app
from ..forms import AddSponsorForm
from ..models import Profile, Project, SponsorMembership, db
from .login_session import requires_login


@SponsorMembership.views('main')
@route('/<profile>/<project>/sponsors/<sponsor>')
class ProjectSponsorView(UrlChangeCheck, UrlForView, ModelView):
    model = SponsorMembership
    route_model_map = {
        'profile': 'project.profile.name',
        'project': 'project.name',
        'sponsor': 'id',
    }

    AddSponsorForm = AddSponsorForm

    def loader(
        self,
        profile: str,  # skipcq: PYL-W0613
        project: str,  # skipcq: PYL-W0613
        sponsor: str,
    ) -> SponsorMembership:
        obj = (
            self.model.query.join(Project, Profile)
            .filter(SponsorMembership.id == sponsor)
            .first()
        )

        return obj

    def after_loader(self):
        self.project = self.obj.project
        self.profile = self.obj.profile
        return super().after_loader()

    @route('edit', methods=['GET', "POST"])
    @requires_login
    @requires_roles({'editor'})
    @render_with('add_sponsor_modal.html.jinja2')
    def edit_sponsor(self):
        sponsorship = self.obj
        form = AddSponsorForm(
            label=self.obj.label, is_promoted=self.obj.is_promoted, obj=sponsorship
        )
        form.profile.data = [self.profile.name]  # Not working as expected
        if form.validate_on_submit():
            del form.profile
            with db.session.no_autoflush:
                with sponsorship.amend_by(current_auth.user) as amendment:
                    form.populate_obj(amendment)
            db.session.commit()
            return render_redirect(self.project.url_for())

        return {
            'project': self.project,
            'form': form,
            'ref_id': 'edit_sponsor',
            'action': self.obj.url_for('edit_sponsor'),
        }

    @route('remove', methods=['GET', "POST"])
    @requires_login
    @requires_roles({'editor'})
    def remove_sponsor(self):
        sponsorship = self.obj
        user = current_auth.user

        form = ConfirmDeleteForm()
        template = 'delete.html.jinja2'
        title = "Remove Sponsor?"
        sponsor_name = self.obj.profile.name
        if form.validate_on_submit():
            sponsorship.revoke(actor=user)
            db.session.add(sponsorship)
            db.session.commit()
            return render_redirect(self.project.url_for())

        return render_template(
            template,
            form=form,
            title=title,
            message=("Do you want to remove ‘{sponsor_name}’ as a sponsor?").format(
                sponsor_name=sponsor_name
            ),
            success=("Sponsor has been removed"),
            next=self.project.url_for(),
            cancel_url=self.project.url_for(),
        )


ProjectSponsorView.init_app(app)
