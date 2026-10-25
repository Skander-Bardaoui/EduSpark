from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import AccountForm, ProfileForm, UniversityAdminEditForm, UniversityForm
from .models import Invitation, Membership, ProfessorProfile, SchoolClass, StudentProfile, University
from .tenancy import (
    MEMBERSHIP_ROLES, PlatformAdminRequiredMixin, Role, TenantRequiredMixin, has_role, is_platform_admin,
    platform_admin_required,
)
from .view_mixins import (
    GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin,
    distinct_choices, send_invitation_email,
)

User = get_user_model()


def _member_count(role=None):
    qs = Membership.objects.filter(university=OuterRef("pk"), is_active=True)
    if role:
        qs = qs.filter(role=role)
    return Coalesce(Subquery(qs.values("university").annotate(c=Count("pk")).values("c")[:1]), 0)


class UniversityListView(PlatformAdminRequiredMixin, SearchFilterMixin, ListView):
    model = University
    template_name = "accounts/admin_universities.html"
    context_object_name = "universities"
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


class UniversityCreateView(PlatformAdminRequiredMixin, GenericFormMixin, SuccessMessageMixin, CreateView):
    model = University
    form_class = UniversityForm
    page_title = "Nouvelle université"
    page_icon = "account_balance"
    submit_label = "Créer l'université"
    cancel_url = reverse_lazy("portal:admin_universities")
    success_message = "Université créée. Invitez maintenant son administrateur."

    def get_success_url(self):
        return reverse("portal:admin_university_detail", args=[self.object.pk])


class UniversityDetailView(PlatformAdminRequiredMixin, DetailView):
    model = University
    template_name = "accounts/admin_university_detail.html"
    context_object_name = "university"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        university = self.object
        members = Membership.objects.filter(university=university)
        context.update({
            "stats": {
                "admins": members.filter(role=Role.UNIVERSITY_ADMIN, is_active=True).count(),
                "professors": members.filter(role=Role.PROFESSOR, is_active=True).count(),
                "students": members.filter(role=Role.STUDENT, is_active=True).count(),
                "pending": members.filter(is_active=False).count(),
                "classes": SchoolClass.objects.filter(university=university).count(),
            },
            "admins": members.filter(role=Role.UNIVERSITY_ADMIN).select_related("user"),
            "admin_invitations": Invitation.objects.filter(
                university=university, role=Role.UNIVERSITY_ADMIN, status=Invitation.STATUS_PENDING,
            ),
        })
        return context


class UniversityUpdateView(TenantRequiredMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    model = University
    require_university = False
    allowed_roles = (Role.UNIVERSITY_ADMIN,)
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
        self.page_title = "Modifier — %s" % self.object
        return super().get_context_data(**kwargs)

    def get_cancel_url(self):
        if is_platform_admin(self.request.user):
            return reverse("portal:admin_university_detail", args=[self.object.pk])
        return reverse("portal:admin_university")

    def get_success_url(self):
        return self.get_cancel_url()


class UniversityDeleteView(PlatformAdminRequiredMixin, GenericDeleteMixin, DeleteView):
    model = University
    success_url = reverse_lazy("portal:admin_universities")
    delete_title = "Supprimer l'université"
    delete_warning = (
        "Toutes les données de cette université (membres, profils, classes, invitations) "
        "seront supprimées. Préférez la désactivation si vous hésitez."
    )
    success_message = "Université supprimée."


@platform_admin_required
@require_POST
def university_invite_admin(request, pk):
    university = get_object_or_404(University, pk=pk)
    email = (request.POST.get("email") or "").strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, "Adresse e-mail invalide.")
        return redirect("portal:admin_university_detail", pk=pk)
    if Invitation.objects.filter(
        university=university, email=email, status=Invitation.STATUS_PENDING,
    ).exists():
        messages.info(request, "Une invitation est déjà en attente pour %s." % email)
        return redirect("portal:admin_university_detail", pk=pk)
    invitation = Invitation.objects.create(
        university=university, email=email, role=Role.UNIVERSITY_ADMIN, invited_by=request.user,
    )
    send_invitation_email(request, invitation)
    messages.success(request, "Invitation d'administrateur envoyée à %s." % email)
    return redirect("portal:admin_university_detail", pk=pk)


class AdminUniversityView(TenantRequiredMixin, TemplateView):
    """Fiche de l'université courante pour l'admin université."""

    template_name = "accounts/admin_university.html"
    allowed_roles = (Role.UNIVERSITY_ADMIN,)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        university = self.request.university
        members = Membership.objects.filter(university=university)
        context.update({
            "university": university,
            "stats": {
                "professors": members.filter(role=Role.PROFESSOR, is_active=True).count(),
                "students": members.filter(role=Role.STUDENT, is_active=True).count(),
                "pending": members.filter(is_active=False).count(),
                "classes": SchoolClass.objects.filter(university=university).count(),
            },
            "admins": members.filter(role=Role.UNIVERSITY_ADMIN, is_active=True).select_related("user"),
            "can_edit": True,
        })
        return context


class AccountListView(PlatformAdminRequiredMixin, SearchFilterMixin, ListView):
    model = User
    template_name = "accounts/admin_accounts.html"
    context_object_name = "accounts"
    search_fields = ("first_name", "last_name", "email")
    search_placeholder = "Nom, prénom, e-mail…"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("memberships__university").order_by("email")

    def get_filters(self):
        return [
            {"param": "role", "lookup": "memberships__role", "label": "Rôle", "choices": MEMBERSHIP_ROLES},
            {"param": "universite", "lookup": "memberships__university", "label": "Université",
             "choices": [(str(u.pk), u.name) for u in University.objects.all()]},
            {"param": "admin", "lookup": "is_superuser", "label": "Admin plateforme", "bool": True,
             "choices": [("1", "Oui"), ("0", "Non")]},
            {"param": "statut", "lookup": "is_active", "label": "Statut", "bool": True,
             "choices": [("1", "Actif"), ("0", "Désactivé")]},
        ]


class AccountUpdateView(PlatformAdminRequiredMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    model = User
    form_class = AccountForm
    page_icon = "manage_accounts"
    success_message = "Compte mis à jour."

    def get_context_data(self, **kwargs):
        self.page_title = "Modifier le compte — %s" % (self.object.get_full_name() or self.object.email)
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        if self.object == self.request.user and not form.cleaned_data["is_platform_admin"]:
            form.add_error(
                "is_platform_admin", "Vous ne pouvez pas retirer vos propres droits d'admin plateforme.",
            )
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_cancel_url(self):
        return reverse("portal:admin_accounts")

    def get_success_url(self):
        return reverse("portal:admin_accounts")


class AccountDeleteView(PlatformAdminRequiredMixin, GenericDeleteMixin, DeleteView):
    model = User
    success_url = reverse_lazy("portal:admin_accounts")
    delete_title = "Supprimer le compte"
    delete_warning = "Le compte et toutes ses appartenances aux universités seront supprimés."
    success_message = "Compte supprimé."

    def form_valid(self, form):
        if self.object == self.request.user:
            messages.error(self.request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect("portal:admin_accounts")
        return super().form_valid(form)


class AdminProfileView(TenantRequiredMixin, View):
    """Profil personnel de l'admin plateforme ou université."""

    allowed_roles = (Role.UNIVERSITY_ADMIN,)
    require_university = False

    def get(self, request):
        return render(request, "accounts/admin_profile.html", {
            "form": ProfileForm(instance=request.user),
            "memberships": request.user.memberships.select_related("university"),
        })

    def post(self, request):
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profil enregistré.")
            return redirect("portal:admin_profile")
        return render(request, "accounts/admin_profile.html", {
            "form": form,
            "memberships": request.user.memberships.select_related("university"),
        })


class AdminPlatformSettingsView(PlatformAdminRequiredMixin, TemplateView):
    template_name = "accounts/admin_platform_settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "university_count": University.objects.count(),
            "account_count": User.objects.count(),
            "membership_count": Membership.objects.count(),
            "pending_invitations": Invitation.objects.filter(
                status=Invitation.STATUS_PENDING,
            ).count(),
        })
        return context
