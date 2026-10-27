"""Classes et groupes de l'université courante (admin université)."""

from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import SchoolClassForm, StudentGroupForm
from .models import MAX_STUDENTS_PER_CLASS, SchoolClass, StudentGroup, StudentProfile
from .tenancy import Role, TenantRequiredMixin, TenantScopedMixin
from .view_mixins import (
    GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin, distinct_choices,
)

ADMIN = (Role.UNIVERSITY_ADMIN,)


class SchoolClassListView(TenantScopedMixin, SearchFilterMixin, ListView):
    model = SchoolClass
    template_name = "accounts/admin_classes.html"
    context_object_name = "classes"
    allowed_roles = ADMIN
    search_fields = ("name", "level", "section", "program", "academic_year")
    search_placeholder = "Nom, niveau, section, filière, année…"

    def get_queryset(self):
        return super().get_queryset().prefetch_related(
            "professors__membership__user",
        ).annotate(
            professor_count=Count("professors", distinct=True),
            group_count=Count("groups", distinct=True),
            student_count=Count("groups__students", distinct=True),
        ).order_by("-academic_year", "name")

    def get_filters(self):
        base = SchoolClass.objects.filter(university=self.request.university)
        return [
            {"param": "filiere", "lookup": "program", "label": "Filière",
             "choices": distinct_choices(base, "program")},
            {"param": "section", "lookup": "section", "label": "Section",
             "choices": distinct_choices(base, "section")},
            {"param": "annee", "lookup": "academic_year", "label": "Année",
             "choices": distinct_choices(base, "academic_year")},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        classes = SchoolClass.objects.filter(university=self.request.university)
        groups = StudentGroup.objects.filter(university=self.request.university)
        total_students = StudentProfile.objects.filter(university=self.request.university).count()
        levels = list(
            classes.exclude(level="").values("level").annotate(
                class_total=Count("pk", distinct=True),
                group_total=Count("groups", distinct=True),
                student_total=Count("groups__students", distinct=True),
            ).order_by("level")
        )
        for row in levels:
            row["share"] = round(row["student_total"] * 100 / total_students) if total_students else 0
        context.update({
            "stats": {
                "classes": classes.count(),
                "groups": groups.count(),
                "students": StudentProfile.objects.filter(
                    university=self.request.university, groups__isnull=False,
                ).distinct().count(),
                "levels": len(levels),
            },
            "max_students": MAX_STUDENTS_PER_CLASS,
            "level_breakdown": levels,
            "recent_groups": groups.select_related("school_class").annotate(
                student_total=Count("students", distinct=True),
            ).order_by("-pk")[:6],
        })
        return context


class SchoolClassDetailView(TenantScopedMixin, DetailView):
    model = SchoolClass
    template_name = "accounts/admin_class_detail.html"
    context_object_name = "school_class"
    allowed_roles = ADMIN

    def get_queryset(self):
        return super().get_queryset().select_related("study_program__department").prefetch_related(
            "professors__membership__user", "groups__students__membership__user",
            "teaching_assignments__subject", "teaching_assignments__professor__membership__user",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        school_class = self.object
        groups = list(school_class.groups.all())
        ungrouped_filters = {
            "university": school_class.university,
            "membership__is_active": True,
            "level__iexact": school_class.level,
            "groups__isnull": True,
        }
        if school_class.section:
            ungrouped_filters["section__iexact"] = school_class.section
        context.update({
            "groups": groups,
            "professors": school_class.professors.all(),
            "students": school_class.student_queryset().select_related("membership__user"),
            "ungrouped": StudentProfile.objects.filter(
                **ungrouped_filters,
            ).select_related("membership__user").distinct(),
            "max_students": MAX_STUDENTS_PER_CLASS,
            "seats_left": school_class.seats_left,
        })
        return context


class SchoolClassCreateView(TenantScopedMixin, GenericFormMixin, SuccessMessageMixin, CreateView):
    model = SchoolClass
    form_class = SchoolClassForm
    template_name = "accounts/admin_class_form.html"
    allowed_roles = ADMIN
    page_title = "Nouvelle classe"
    page_icon = "layers"
    submit_label = "Créer la classe"
    cancel_url = reverse_lazy("portal:admin_classes")
    success_message = "Classe créée."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        return kwargs

    def get_success_url(self):
        return reverse("portal:admin_class_detail", args=[self.object.pk])


class SchoolClassUpdateView(TenantScopedMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    model = SchoolClass
    form_class = SchoolClassForm
    template_name = "accounts/admin_class_form.html"
    allowed_roles = ADMIN
    page_icon = "layers"
    success_message = "Classe mise à jour."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        return kwargs

    def get_context_data(self, **kwargs):
        self.page_title = "Modifier — %s" % self.object
        return super().get_context_data(**kwargs)

    def get_cancel_url(self):
        return reverse("portal:admin_class_detail", args=[self.object.pk])

    def get_success_url(self):
        return reverse("portal:admin_class_detail", args=[self.object.pk])


class SchoolClassDeleteView(TenantScopedMixin, GenericDeleteMixin, DeleteView):
    model = SchoolClass
    allowed_roles = ADMIN
    success_url = reverse_lazy("portal:admin_classes")
    delete_title = "Supprimer la classe"
    delete_warning = "La classe et ses groupes seront supprimés. Les étudiants restent membres de l'université."
    success_message = "Classe supprimée."


class _GroupMixin(TenantRequiredMixin):
    allowed_roles = ADMIN

    def get_school_class(self):
        if not hasattr(self, "_school_class"):
            self._school_class = get_object_or_404(
                SchoolClass, pk=self.kwargs["pk"], university=self.request.university,
            )
        return self._school_class

    def get_group(self):
        return get_object_or_404(
            StudentGroup, pk=self.kwargs["gpk"], university=self.request.university,
            school_class=self.get_school_class(),
        )

    def get_cancel_url(self):
        return reverse("portal:admin_class_detail", args=[self.get_school_class().pk])


class _GroupFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["school_class"] = self.get_school_class()
        return kwargs


class StudentGroupCreateView(_GroupFormMixin, _GroupMixin, GenericFormMixin, SuccessMessageMixin, CreateView):
    model = StudentGroup
    form_class = StudentGroupForm
    page_title = "Nouveau groupe"
    page_icon = "groups"
    submit_label = "Créer le groupe"
    success_message = "Groupe créé."

    def form_valid(self, form):
        form.instance.school_class = self.get_school_class()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("portal:admin_class_detail", args=[self.get_school_class().pk])


class StudentGroupUpdateView(_GroupFormMixin, _GroupMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    model = StudentGroup
    form_class = StudentGroupForm
    page_icon = "groups"
    success_message = "Groupe mis à jour."

    def get_object(self, queryset=None):
        return self.get_group()

    def get_context_data(self, **kwargs):
        self.page_title = "Modifier — %s" % self.object.name
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        return reverse("portal:admin_class_detail", args=[self.get_school_class().pk])


class StudentGroupDeleteView(_GroupMixin, GenericDeleteMixin, DeleteView):
    model = StudentGroup
    delete_title = "Supprimer le groupe"
    delete_warning = "Le groupe sera supprimé. Les étudiants restent dans l'université."
    success_message = "Groupe supprimé."

    def get_object(self, queryset=None):
        return self.get_group()

    def get_success_url(self):
        return reverse("portal:admin_class_detail", args=[self.get_school_class().pk])
