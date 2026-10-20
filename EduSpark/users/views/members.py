"""Professeurs et étudiants de l'université courante (admin université).

Les deux CRUD partagent la même mécanique : une classe de base paramétrée
par le modèle de profil, déclinée pour chaque rôle.
"""

from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import DeleteView, DetailView, FormView, ListView, UpdateView

from ..forms import ProfessorCreateForm, ProfessorProfileForm, StudentCreateForm, StudentProfileForm
from ..models import Membership, ProfessorProfile, SchoolClass, StudentGroup, StudentProfile
from ..tenancy import Role, TenantScopedMixin, has_role, tenant_required
from .mixins import (
    GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin, distinct_choices,
    redirect_next, send_set_password_email,
)

ADMIN = (Role.UNIVERSITY_ADMIN,)
STATUS_FILTER = {
    "param": "statut", "lookup": "membership__is_active", "label": "Statut", "bool": True,
    "choices": [("1", "Actif"), ("0", "En attente / suspendu")],
}


class _MemberQuerysetMixin(TenantScopedMixin):
    def get_queryset(self):
        qs = super().get_queryset().select_related("membership__user")
        # Seul l'admin voit les membres en attente ou suspendus.
        if not has_role(self.request, Role.UNIVERSITY_ADMIN):
            qs = qs.filter(membership__is_active=True)
        return qs


class _MemberListView(_MemberQuerysetMixin, SearchFilterMixin, ListView):
    context_object_name = "profiles"

    def get_filters(self):
        base = self.model.objects.filter(university=self.request.university)
        filters = self.extra_filters(base)
        if has_role(self.request, Role.UNIVERSITY_ADMIN):
            filters.append(STATUS_FILTER)
        return filters


class _MemberCreateView(TenantScopedMixin, GenericFormMixin, FormView):
    allowed_roles = ADMIN
    submit_label = "Ajouter"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        return kwargs

    def form_valid(self, form):
        membership, created = form.save_member()
        if created:
            send_set_password_email(self.request, membership.user, self.request.university)
            messages.success(self.request, f"{membership.user} ajouté(e). Un e-mail lui permet de définir son mot de passe.")
        else:
            messages.success(self.request, f"Compte existant : {membership.user} rejoint {self.request.university}.")
        self.created_profile = membership.ensure_profile()
        return super().form_valid(form)


class _MemberUpdateView(_MemberQuerysetMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    allowed_roles = ADMIN
    success_message = "Profil mis à jour."

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier — {self.object.user.display_name}"
        return super().get_context_data(**kwargs)


class _MemberDeleteView(_MemberQuerysetMixin, GenericDeleteMixin, DeleteView):
    """Retire la personne de l'université : le compte (peut-être partagé avec
    d'autres universités) est conservé."""

    allowed_roles = ADMIN
    delete_warning = (
        "La personne sera retirée de cette université (profil, groupes). "
        "Son compte EduSpark et ses autres universités sont conservés."
    )
    success_message = "Membre retiré de l'université."

    def form_valid(self, form):
        self.object.membership.delete()  # supprime le profil en cascade
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


# --- Professeurs -------------------------------------------------------------

class ProfessorListView(_MemberListView):
    model = ProfessorProfile
    template_name = "users/professors/list.html"
    search_fields = (
        "membership__user__first_name", "membership__user__last_name", "membership__user__email",
        "department", "speciality",
    )
    search_placeholder = "Nom, e-mail, département, spécialité…"

    def extra_filters(self, base):
        return [
            {"param": "departement", "lookup": "department", "label": "Département",
             "choices": distinct_choices(base, "department")},
            {"param": "grade", "lookup": "grade", "label": "Grade", "choices": ProfessorProfile.GRADE_CHOICES},
        ]


class ProfessorDetailView(_MemberQuerysetMixin, DetailView):
    model = ProfessorProfile
    template_name = "users/professors/detail.html"
    context_object_name = "profile"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["classes"] = self.object.classes.filter(university=self.request.university)
        return context


class ProfessorCreateView(_MemberCreateView):
    form_class = ProfessorCreateForm
    page_title = "Ajouter un professeur"
    page_icon = "school"
    cancel_url = reverse_lazy("users:professor_list")

    def get_success_url(self):
        return reverse("users:professor_detail", args=[self.created_profile.pk])


class ProfessorUpdateView(_MemberUpdateView):
    model = ProfessorProfile
    form_class = ProfessorProfileForm
    page_icon = "school"

    def get_success_url(self):
        return reverse("users:professor_detail", args=[self.object.pk])


class ProfessorDeleteView(_MemberDeleteView):
    model = ProfessorProfile
    delete_title = "Retirer le professeur"
    success_url = reverse_lazy("users:professor_list")


# --- Étudiants ---------------------------------------------------------------

class StudentListView(_MemberListView):
    model = StudentProfile
    template_name = "users/students/list.html"
    allowed_roles = (Role.UNIVERSITY_ADMIN, Role.PROFESSOR)
    search_fields = (
        "membership__user__first_name", "membership__user__last_name", "membership__user__email",
        "student_number", "program",
    )
    search_placeholder = "Nom, e-mail, matricule, filière…"

    def get_queryset(self):
        groups = StudentGroup.objects.filter(university=self.request.university).select_related("school_class")
        return super().get_queryset().prefetch_related(Prefetch("groups", queryset=groups))

    def extra_filters(self, base):
        classes = SchoolClass.objects.filter(university=self.request.university)
        return [
            {"param": "filiere", "lookup": "program", "label": "Filière", "choices": distinct_choices(base, "program")},
            {"param": "promotion", "lookup": "promotion", "label": "Promotion",
             "choices": distinct_choices(base, "promotion")},
            {"param": "classe", "lookup": "groups__school_class", "label": "Classe",
             "choices": [(str(c.pk), str(c)) for c in classes]},
        ]


class StudentDetailView(_MemberQuerysetMixin, DetailView):
    model = StudentProfile
    template_name = "users/students/detail.html"
    context_object_name = "profile"
    allowed_roles = (Role.UNIVERSITY_ADMIN, Role.PROFESSOR)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["groups"] = (
            self.object.groups.filter(university=self.request.university).select_related("school_class")
        )
        return context


class StudentCreateView(_MemberCreateView):
    form_class = StudentCreateForm
    page_title = "Ajouter un étudiant"
    page_icon = "person_add"
    cancel_url = reverse_lazy("users:student_list")

    def get_success_url(self):
        return reverse("users:student_detail", args=[self.created_profile.pk])


class StudentUpdateView(_MemberUpdateView):
    model = StudentProfile
    form_class = StudentProfileForm
    page_icon = "badge"

    def get_success_url(self):
        return reverse("users:student_detail", args=[self.object.pk])


class StudentDeleteView(_MemberDeleteView):
    model = StudentProfile
    delete_title = "Retirer l'étudiant"
    success_url = reverse_lazy("users:student_list")


# --- Validation des inscriptions ----------------------------------------------

@tenant_required(Role.UNIVERSITY_ADMIN)
@require_POST
def membership_decide(request, pk):
    """Valide ou refuse une inscription en attente dans l'université courante."""
    membership = get_object_or_404(
        Membership.objects.select_related("user"), pk=pk, university=request.university, is_active=False,
    )
    if request.POST.get("decision") == "approve":
        membership.is_active = True
        membership.awaiting_email_verification = False
        membership.save(update_fields=["is_active", "awaiting_email_verification"])
        membership.ensure_profile()
        messages.success(request, f"Inscription de {membership.user} validée.")
    else:
        membership.delete()
        messages.success(request, f"Inscription de {membership.user} refusée.")
    return redirect_next(request, "users:dashboard")
