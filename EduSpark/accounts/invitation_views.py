"""Invitations à rejoindre l'université courante (admin université)."""

from datetime import timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import InvitationForm
from .models import Invitation
from .tenancy import Role, TenantRequiredMixin, TenantScopedMixin, is_platform_admin, tenant_required
from .view_mixins import (
    GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin, send_invitation_email,
)

ADMIN = (Role.UNIVERSITY_ADMIN,)


class InvitationListView(TenantScopedMixin, SearchFilterMixin, ListView):
    model = Invitation
    template_name = "accounts/admin_invitations.html"
    context_object_name = "invitations"
    allowed_roles = ADMIN
    search_fields = ("email",)
    search_placeholder = "Rechercher une adresse e-mail…"

    def get_queryset(self):
        return super().get_queryset().select_related("invited_by", "accepted_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = Invitation.objects.filter(university=self.request.university)
        pending = base.filter(status=Invitation.STATUS_PENDING)
        context.update({
            "invitation_stats": {
                "pending": pending.filter(expires_at__gt=timezone.now()).count(),
                "expired": pending.filter(expires_at__lte=timezone.now()).count(),
                "accepted": base.filter(status=Invitation.STATUS_ACCEPTED).count(),
                "total": base.count(),
            },
            "invitation_form": InvitationForm(
                university=self.request.university, can_invite_admins=False,
            ),
        })
        return context

    def get_filters(self):
        return [
            {"param": "statut", "lookup": "status", "label": "Statut", "choices": Invitation.STATUS_CHOICES},
            {"param": "role", "lookup": "role", "label": "Rôle", "choices": [
                (Role.UNIVERSITY_ADMIN, "Admin université"),
                (Role.PROFESSOR, "Professeur"),
                (Role.STUDENT, "Étudiant"),
            ]},
        ]


class InvitationCreateView(TenantRequiredMixin, GenericFormMixin, CreateView):
    model = Invitation
    form_class = InvitationForm
    allowed_roles = ADMIN
    page_title = "Nouvelle invitation"
    page_icon = "mark_email_read"
    submit_label = "Envoyer l'invitation"
    cancel_url = reverse_lazy("portal:admin_invitations")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        kwargs["can_invite_admins"] = is_platform_admin(self.request.user)
        return kwargs

    def form_valid(self, form):
        form.instance.university = self.request.university
        form.instance.invited_by = self.request.user
        response = super().form_valid(form)
        send_invitation_email(self.request, self.object)
        messages.success(self.request, "Invitation envoyée à %s." % self.object.email)
        return response

    def get_success_url(self):
        return reverse_lazy("portal:admin_invitations")


class InvitationUpdateView(TenantScopedMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    model = Invitation
    form_class = InvitationForm
    allowed_roles = ADMIN
    page_icon = "mark_email_read"
    success_message = "Invitation mise à jour."

    def get_queryset(self):
        return super().get_queryset().filter(status=Invitation.STATUS_PENDING)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        kwargs["can_invite_admins"] = is_platform_admin(self.request.user)
        return kwargs

    def get_context_data(self, **kwargs):
        self.page_title = "Modifier — %s" % self.object.email
        return super().get_context_data(**kwargs)

    def get_cancel_url(self):
        return reverse_lazy("portal:admin_invitations")

    def get_success_url(self):
        return reverse_lazy("portal:admin_invitations")


class InvitationDeleteView(TenantScopedMixin, GenericDeleteMixin, DeleteView):
    model = Invitation
    allowed_roles = ADMIN
    success_url = reverse_lazy("portal:admin_invitations")
    delete_title = "Supprimer l'invitation"
    delete_warning = "Le lien envoyé ne fonctionnera plus."
    success_message = "Invitation supprimée."


@tenant_required(Role.UNIVERSITY_ADMIN)
@require_POST
def invitation_action(request, pk, action):
    """Renvoie ou révoque une invitation de l'université courante."""
    invitation = get_object_or_404(Invitation, pk=pk, university=request.university)
    if action == "renvoyer":
        if invitation.status != Invitation.STATUS_PENDING:
            messages.error(request, "Seule une invitation en attente peut être renvoyée.")
        else:
            invitation.expires_at = timezone.now() + timedelta(days=7)
            invitation.save(update_fields=["expires_at"])
            send_invitation_email(request, invitation)
            messages.success(request, "Invitation renvoyée à %s." % invitation.email)
    elif action == "revoquer":
        if invitation.status != Invitation.STATUS_PENDING:
            messages.error(request, "Seule une invitation en attente peut être révoquée.")
        else:
            invitation.status = Invitation.STATUS_REVOKED
            invitation.save(update_fields=["status"])
            messages.success(request, "Invitation de %s révoquée." % invitation.email)
    else:
        messages.error(request, "Action inconnue.")
    return redirect("portal:admin_invitations")
