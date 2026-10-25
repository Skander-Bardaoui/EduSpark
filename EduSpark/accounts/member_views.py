from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import DeleteView, FormView, ListView, UpdateView

from .forms import ProfessorCreateForm, ProfessorProfileForm, StudentCreateForm, StudentProfileForm
from .models import Membership, ProfessorProfile, SchoolClass, StudentProfile
from .tenancy import Role, TenantRequiredMixin, TenantScopedMixin, tenant_required
from .view_mixins import (
    GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin,
    distinct_choices, send_set_password_email,
)

ADMIN = (Role.UNIVERSITY_ADMIN,)


class _MemberListView(TenantScopedMixin, SearchFilterMixin, ListView):
    allowed_roles = ADMIN
    context_object_name = "profiles"
    member_role = None

    def get_queryset(self):
        return super().get_queryset().select_related("membership__user")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pending_memberships"] = Membership.objects.filter(
            university=self.request.university, is_active=False, role=self.member_role,
        ).select_related("user").order_by("-created_at")
        return context


class _MemberCreateView(TenantRequiredMixin, GenericFormMixin, FormView):
    allowed_roles = ADMIN
    submit_label = "Ajouter"
    page_icon = "person_add"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        return kwargs

    def form_valid(self, form):
        membership, created = form.save_member()
        if created:
            send_set_password_email(self.request, membership.user, self.request.university)
            messages.success(
                self.request,
                "%s ajouté(e). Un e-mail lui permet de définir son mot de passe." % membership.user,
            )
        else:
            messages.success(
                self.request,
                "Compte existant : %s rejoint %s." % (membership.user, self.request.university),
            )
        return redirect(self.get_success_url())


class _MemberUpdateView(TenantScopedMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    allowed_roles = ADMIN
    success_message = "Profil mis à jour."

    def get_context_data(self, **kwargs):
        self.page_title = "Modifier — %s" % self.object.user
        return super().get_context_data(**kwargs)

    def get_cancel_url(self):
        return reverse(self.list_url_name)

    def get_success_url(self):
        return reverse(self.list_url_name)


class _MemberDeleteView(TenantScopedMixin, GenericDeleteMixin, DeleteView):
    allowed_roles = ADMIN

    def form_valid(self, form):
        membership = self.object.membership
        membership.delete()
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())

    def get_cancel_url(self):
        return reverse(self.list_url_name)

    def get_success_url(self):
        return reverse(self.list_url_name)


# --- Professeurs -------------------------------------------------------------

class ProfessorListView(_MemberListView):
    model = ProfessorProfile
    template_name = "accounts/admin_teachers.html"
    member_role = Role.PROFESSOR
    search_fields = (
        "membership__user__first_name", "membership__user__last_name",
        "membership__user__email", "department", "speciality",
    )
    search_placeholder = "Nom, e-mail, département, spécialité…"

    def get_queryset(self):
        return super().get_queryset().annotate(class_count=Count("classes", distinct=True))

    def extra_filters(self, base):
        return [
            {"param": "departement", "lookup": "department", "label": "Département",
             "choices": distinct_choices(base, "department")},
            {"param": "grade", "lookup": "grade", "label": "Grade",
             "choices": ProfessorProfile.GRADE_CHOICES},
        ]

    def get_filters(self):
        base = ProfessorProfile.objects.filter(university=self.request.university)
        return self.extra_filters(base)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profiles = ProfessorProfile.objects.filter(university=self.request.university)
        grades = dict(ProfessorProfile.GRADE_CHOICES)
        context.update({
            "stats": {
                "professors": profiles.filter(membership__is_active=True).count(),
                "pending": context["pending_memberships"].count(),
                "departments": profiles.exclude(department="").values("department").distinct().count(),
                "classes": SchoolClass.objects.filter(
                    university=self.request.university, professors__isnull=False,
                ).distinct().count(),
            },
            "grade_breakdown": [
                {"label": grades.get(row["grade"], "Non renseigné"), "total": row["total"]}
                for row in profiles.values("grade").annotate(total=Count("pk")).order_by("-total")
            ],
            "department_breakdown": list(
                profiles.exclude(department="").values("department")
                .annotate(total=Count("pk")).order_by("-total", "department")[:6]
            ),
        })
        return context


class ProfessorCreateView(_MemberCreateView):
    form_class = ProfessorCreateForm
    page_title = "Ajouter un professeur"
    page_icon = "school"
    list_url_name = "portal:admin_teachers"

    def get_success_url(self):
        return reverse("portal:admin_teachers")


class ProfessorUpdateView(_MemberUpdateView):
    model = ProfessorProfile
    form_class = ProfessorProfileForm
    page_icon = "school"
    list_url_name = "portal:admin_teachers"


class ProfessorDeleteView(_MemberDeleteView):
    model = ProfessorProfile
    list_url_name = "portal:admin_teachers"
    delete_title = "Retirer le professeur"
    delete_warning = (
        "La personne sera retirée de cette université (profil, classes). "
        "Son compte EduSpark et ses autres universités sont conservés."
    )
    success_message = "Membre retiré de l'université."


# --- Étudiants ---------------------------------------------------------------

class StudentListView(_MemberListView):
    model = StudentProfile
    template_name = "accounts/admin_students.html"
    member_role = Role.STUDENT
    search_fields = (
        "membership__user__first_name", "membership__user__last_name",
        "membership__user__email", "student_number", "program",
    )
    search_placeholder = "Nom, e-mail, matricule, filière…"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("groups__school_class")

    def extra_filters(self, base):
        from .models import SchoolClass
        classes = SchoolClass.objects.filter(university=self.request.university)
        return [
            {"param": "filiere", "lookup": "program", "label": "Filière",
             "choices": distinct_choices(base, "program")},
            {"param": "promotion", "lookup": "promotion", "label": "Promotion",
             "choices": distinct_choices(base, "promotion")},
            {"param": "classe", "lookup": "groups__school_class", "label": "Classe",
             "choices": [(str(c.pk), str(c)) for c in classes]},
        ]

    def get_filters(self):
        base = StudentProfile.objects.filter(university=self.request.university)
        return self.extra_filters(base)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profiles = StudentProfile.objects.filter(university=self.request.university)
        context.update({
            "stats": {
                "students": profiles.filter(membership__is_active=True).count(),
                "pending": context["pending_memberships"].count(),
                "programs": profiles.exclude(program="").values("program").distinct().count(),
                "classes": SchoolClass.objects.filter(
                    university=self.request.university, groups__students__isnull=False,
                ).distinct().count(),
            },
        })
        return context


class StudentCreateView(_MemberCreateView):
    form_class = StudentCreateForm
    page_title = "Ajouter un étudiant"
    page_icon = "person_add"
    list_url_name = "portal:admin_students"

    def get_success_url(self):
        return reverse("portal:admin_students")


class StudentUpdateView(_MemberUpdateView):
    model = StudentProfile
    form_class = StudentProfileForm
    page_icon = "badge"
    list_url_name = "portal:admin_students"


class StudentDeleteView(_MemberDeleteView):
    model = StudentProfile
    list_url_name = "portal:admin_students"
    delete_title = "Retirer l'étudiant"
    delete_warning = (
        "La personne sera retirée de cette université (profil, groupes). "
        "Son compte EduSpark et ses autres universités sont conservés."
    )
    success_message = "Membre retiré de l'université."


# --- Validation des inscriptions --------------------------------------------

@tenant_required(Role.UNIVERSITY_ADMIN)
@require_POST
def membership_decide(request, pk):
    """Valide ou refuse une inscription en attente dans l'université courante."""
    membership = get_object_or_404(
        Membership.objects.select_related("user"), pk=pk, university=request.university, is_active=False,
    )
    target = "portal:admin_students" if membership.role == Role.STUDENT else "portal:admin_teachers"
    if request.POST.get("decision") == "approve":
        membership.is_active = True
        membership.save(update_fields=["is_active"])
        membership.ensure_profile()
        messages.success(request, "Inscription de %s validée." % membership.user)
    else:
        messages.success(request, "Inscription de %s refusée." % membership.user)
        membership.delete()
    return redirect(target)
