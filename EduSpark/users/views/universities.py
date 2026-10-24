from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, OuterRef, ProtectedError, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from ..forms import UniversityAdminEditForm, UniversityForm
from ..models import Invitation, Membership, SchoolClass, University
from ..tenancy import (
    PlatformAdminRequiredMixin, Role, TenantRequiredMixin, has_role, is_platform_admin,
    platform_admin_required,
)
from .mixins import (
    GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin, distinct_choices,
    redirect_next, send_invitation_email,
)

User = get_user_model()


def _member_count(role=None):
    qs = Membership.objects.filter(university=OuterRef("pk"), is_active=True)
    if role:
        qs = qs.filter(role=role)
    return Coalesce(Subquery(qs.values("university").annotate(c=Count("pk")).values("c")[:1]), 0)


class UniversityListView(PlatformAdminRequiredMixin, SearchFilterMixin, ListView):
    model = University
    template_name = "users/universities/list.html"
    search_fields = ("name", "code", "city", "email_domain")
    search_placeholder = "Nom, sigle, ville, domaine…"

    def get_queryset(self):
        return super().get_queryset().annotate(
            professor_count=_member_count(Role.PROFESSOR),
            student_count=_member_count(Role.STUDENT),
        )

    def get_filters(self):
        return [
            {"param": "statut", "lookup": "is_active", "label": "Statut", "bool": True,
             "choices": [("1", "Active"), ("0", "Désactivée")]},
            {"param": "pays", "lookup": "country", "label": "Pays",
             "choices": distinct_choices(University.objects.all(), "country")},
        ]


class UniversityDetailView(TenantRequiredMixin, DetailView):
    """Admin plateforme : toutes ; sinon uniquement l'université courante."""

    model = University
    template_name = "users/universities/detail.html"
    require_university = False

    def get_object(self, queryset=None):
        university = super().get_object(queryset)
        if not is_platform_admin(self.request.user) and university != self.request.university:
            raise Http404
        return university

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        u = self.object
        members = Membership.objects.filter(university=u)
        context.update({
            "stats": {
                "admins": members.filter(role=Role.UNIVERSITY_ADMIN, is_active=True).count(),
                "professors": members.filter(role=Role.PROFESSOR, is_active=True).count(),
                "students": members.filter(role=Role.STUDENT, is_active=True).count(),
                "pending": members.filter(is_active=False).count(),
                "classes": SchoolClass.objects.filter(university=u).count(),
            },
            "admins": members.filter(role=Role.UNIVERSITY_ADMIN).select_related("user"),
            "admin_invitations": Invitation.objects.filter(
                university=u, role=Role.UNIVERSITY_ADMIN, status=Invitation.STATUS_PENDING,
            ),
            "can_edit": is_platform_admin(self.request.user) or (
                u == self.request.university and has_role(self.request, Role.UNIVERSITY_ADMIN)
            ),
        })
        return context


class UniversityCreateView(PlatformAdminRequiredMixin, GenericFormMixin, SuccessMessageMixin, CreateView):
    model = University
    form_class = UniversityForm
    page_title = "Nouvelle université"
    page_icon = "account_balance"
    submit_label = "Créer l'université"
    cancel_url = reverse_lazy("users:university_list")
    success_message = "Université créée. Invitez maintenant son administrateur."

    def get_success_url(self):
        return reverse("users:university_detail", args=[self.object.pk])


class UniversityUpdateView(TenantRequiredMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    """Admin plateforme : tous les champs. Admin université : sa propre université,
    sans nom / domaine / statut."""

    model = University
    require_university = False
    page_icon = "account_balance"
    success_message = "Université mise à jour."

    def get_object(self, queryset=None):
        university = super().get_object(queryset)
        if is_platform_admin(self.request.user):
            return university
        if university == self.request.university and has_role(self.request, Role.UNIVERSITY_ADMIN):
            return university
        raise Http404

    def get_form_class(self):
        return UniversityForm if is_platform_admin(self.request.user) else UniversityAdminEditForm

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier — {self.object}"
        return super().get_context_data(**kwargs)

    def get_cancel_url(self):
        return reverse("users:university_detail", args=[self.object.pk])

    def get_success_url(self):
        return reverse("users:university_detail", args=[self.object.pk])


class UniversityDeleteView(PlatformAdminRequiredMixin, GenericDeleteMixin, DeleteView):
    model = University
    success_url = reverse_lazy("users:university_list")
    delete_title = "Supprimer l'université"
    delete_warning = (
        "Toutes les données de cette université (membres, profils, classes, invitations "
        "et données des autres modules) seront supprimées. Préférez la désactivation si vous hésitez."
    )
    success_message = "Université supprimée."

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "Suppression impossible : des données protégées y sont rattachées.")
            return redirect("users:university_detail", pk=self.object.pk)


class _InviteAdminForm(forms.Form):
    email = forms.EmailField()


@platform_admin_required
@require_POST
def university_invite_admin(request, pk):
    """Admin plateforme : invite l'administrateur d'une université."""
    university = get_object_or_404(University, pk=pk)
    form = _InviteAdminForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Adresse e-mail invalide.")
        return redirect("users:university_detail", pk=pk)
    email = form.cleaned_data["email"].strip().lower()
    if Invitation.objects.filter(university=university, email=email, status=Invitation.STATUS_PENDING).exists():
        messages.info(request, f"Une invitation est déjà en attente pour {email}.")
        return redirect("users:university_detail", pk=pk)
    invitation = Invitation.objects.create(
        university=university, email=email, role=Role.UNIVERSITY_ADMIN, invited_by=request.user,
    )
    send_invitation_email(request, invitation)
    messages.success(request, f"Invitation d'administrateur envoyée à {email}.")
    return redirect("users:university_detail", pk=pk)


@platform_admin_required
@require_POST
def membership_remove(request, pk):
    """Admin plateforme : retire un utilisateur d'une université."""
    membership = get_object_or_404(Membership.objects.select_related("user", "university"), pk=pk)
    membership.delete()
    messages.success(request, f"{membership.user} a été retiré(e) de {membership.university}.")
    return redirect_next(request, "users:university_detail", pk=membership.university_id)
