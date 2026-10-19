from datetime import timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from ..forms import InvitationForm
from ..models import Invitation
from ..tenancy import MEMBERSHIP_ROLES, Role, TenantScopedMixin, is_platform_admin, tenant_required
from .mixins import GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin, send_invitation_email

ADMIN = (Role.UNIVERSITY_ADMIN,)


class InvitationListView(TenantScopedMixin, SearchFilterMixin, ListView):
    model = Invitation
    allowed_roles = ADMIN
    template_name = "users/invitations/list.html"
    context_object_name = "invitations"
    search_fields = ("email",)
    search_placeholder = "E-mail invité…"

    def get_queryset(self):
        return super().get_queryset().select_related("invited_by")

    def get_filters(self):
        return [
            {"param": "statut", "lookup": "status", "label": "Statut", "choices": Invitation.STATUS_CHOICES},
            {"param": "role", "lookup": "role", "label": "Rôle", "choices": MEMBERSHIP_ROLES},
        ]


class InvitationDetailView(TenantScopedMixin, DetailView):
    model = Invitation
    allowed_roles = ADMIN
    template_name = "users/invitations/detail.html"
    context_object_name = "invitation"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["link"] = self.request.build_absolute_uri(
            reverse("users:invitation_accept", kwargs={"token": self.object.token})
        )
        return context


class _InvitationFormMixin(TenantScopedMixin, GenericFormMixin, SuccessMessageMixin):
    model = Invitation
    form_class = InvitationForm
    allowed_roles = ADMIN
    page_icon = "forward_to_inbox"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        # Seul l'admin plateforme nomme des admins université.
        kwargs["can_invite_admins"] = is_platform_admin(self.request.user)
        return kwargs

    def get_success_url(self):
        return reverse("users:invitation_detail", args=[self.object.pk])


class InvitationCreateView(_InvitationFormMixin, CreateView):
    page_title = "Nouvelle invitation"
    submit_label = "Envoyer l'invitation"
    cancel_url = reverse_lazy("users:invitation_list")
    success_message = "Invitation envoyée."

    def form_valid(self, form):
        form.instance.invited_by = self.request.user
        response = super().form_valid(form)
        send_invitation_email(self.request, self.object)
        return response


class InvitationUpdateView(_InvitationFormMixin, UpdateView):
    success_message = "Invitation mise à jour."

    def get_queryset(self):
        # Une invitation acceptée ou révoquée n'est plus modifiable.
        return super().get_queryset().filter(status=Invitation.STATUS_PENDING)

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier l'invitation — {self.object.email}"
        return super().get_context_data(**kwargs)


class InvitationDeleteView(TenantScopedMixin, GenericDeleteMixin, DeleteView):
    model = Invitation
    allowed_roles = ADMIN
    success_url = reverse_lazy("users:invitation_list")
    delete_title = "Supprimer l'invitation"
    delete_warning = "Le lien envoyé ne fonctionnera plus. L'historique de l'invitation sera effacé."
    success_message = "Invitation supprimée."


@tenant_required(Role.UNIVERSITY_ADMIN)
@require_POST
def invitation_action(request, pk, action):
    """Renvoyer (prolonge de 7 jours) ou révoquer une invitation en attente."""
    invitation = get_object_or_404(
        Invitation, pk=pk, university=request.university, status=Invitation.STATUS_PENDING,
    )
    if action == "renvoyer":
        invitation.expires_at = timezone.now() + timedelta(days=7)
        invitation.save(update_fields=["expires_at"])
        send_invitation_email(request, invitation)
        messages.success(request, f"Invitation renvoyée à {invitation.email}.")
    elif action == "revoquer":
        invitation.status = Invitation.STATUS_REVOKED
        invitation.save(update_fields=["status"])
        messages.success(request, f"Invitation de {invitation.email} révoquée.")
    return redirect("users:invitation_detail", pk=invitation.pk)
