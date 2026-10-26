"""Administration du catalogue par l'admin de l'université : départements,
filières, matières, affectations des professeurs, emploi du temps de chaque
classe et supervision (lecture seule) des cours des professeurs."""

from collections import defaultdict

from django.db.models import Count, Q
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView,
)

from accounts.models import ProfessorProfile, SchoolClass
from accounts.view_mixins import SearchFilterMixin, SuccessMessageMixin, distinct_choices

from .forms import (
    DepartmentForm, ProgramForm, ScheduleSlotForm, SubjectForm, TeachingAssignmentForm,
    professor_label,
)
from .mixins import AdminMixin, DeletePageMixin, FormPageMixin, SelectedClassMixin
from .models import (
    Course, CoursePublication, Department, Program, ScheduleSlot, Subject, TeachingAssignment,
    display_name,
)
from .services import build_week_grid

OFFER_URL = reverse_lazy("courses:admin_program_offer")
SUBJECTS_URL = reverse_lazy("courses:admin_subjects")
ASSIGNMENTS_URL = reverse_lazy("courses:admin_assignments")
TIMETABLE_URL = reverse_lazy("courses:admin_timetable")


class _CatalogFormView(AdminMixin, FormPageMixin, SuccessMessageMixin):
    """Création / modification d'un objet du catalogue, borné à l'université courante."""

    cancel_url = OFFER_URL
    success_url = OFFER_URL

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        return kwargs


class _UpdateTitleMixin:
    def get_context_data(self, **kwargs):
        self.page_title = "Modifier — %s" % self.object
        return super().get_context_data(**kwargs)


# ---------------------------------------------------------------------------
# Départements et filières
# ---------------------------------------------------------------------------

class ProgramOfferView(AdminMixin, TemplateView):
    """Offre de formation : départements et filières de l'université."""

    template_name = "courses/admin_program_offer.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        university = self.request.university
        departments = list(
            Department.objects.filter(university=university)
            .select_related("head__membership__user")
            .annotate(
                program_count=Count("programs", distinct=True),
                subject_count=Count("programs__subjects", distinct=True),
            )
        )
        programs = (
            Program.objects.filter(university=university)
            .select_related("department", "coordinator__membership__user")
            .annotate(
                subject_count=Count("subjects", distinct=True),
                class_count=Count("school_classes", distinct=True),
            )
            .order_by("department__name", "name")
        )
        selected = self.request.GET.get("departement", "")
        selected_pk = int(selected) if selected.isdigit() else None
        if selected_pk:
            programs = programs.filter(department_id=selected_pk)
        context.update({
            "departments": departments,
            "programs": programs,
            "selected_department": selected_pk,
            "stats": {
                "departments": len(departments),
                "programs": Program.objects.filter(university=university).count(),
                "subjects": Subject.objects.filter(university=university).count(),
                "classes": SchoolClass.objects.filter(
                    university=university, study_program__isnull=False,
                ).count(),
            },
        })
        return context


class DepartmentCreateView(_CatalogFormView, CreateView):
    model = Department
    form_class = DepartmentForm
    page_title = "Nouveau département"
    page_icon = "account_tree"
    submit_label = "Créer le département"
    success_message = "Département créé."


class DepartmentUpdateView(_UpdateTitleMixin, _CatalogFormView, UpdateView):
    model = Department
    form_class = DepartmentForm
    page_icon = "account_tree"
    success_message = "Département mis à jour."


class DepartmentDeleteView(AdminMixin, DeletePageMixin, DeleteView):
    model = Department
    cancel_url = OFFER_URL
    success_url = OFFER_URL
    delete_title = "Supprimer le département"
    delete_warning = "Le département sera supprimé. Il ne doit plus contenir de filière."
    success_message = "Département supprimé."

    def get_blockers(self):
        return [("filières rattachées", self.object.programs.count())]


class ProgramCreateView(_CatalogFormView, CreateView):
    model = Program
    form_class = ProgramForm
    page_title = "Nouvelle filière"
    page_icon = "workspace_premium"
    submit_label = "Créer la filière"
    success_message = "Filière créée."
    page_hint = "Créez d'abord le département auquel la filière appartient."


class ProgramUpdateView(_UpdateTitleMixin, _CatalogFormView, UpdateView):
    model = Program
    form_class = ProgramForm
    page_icon = "workspace_premium"
    success_message = "Filière mise à jour."


class ProgramDeleteView(AdminMixin, DeletePageMixin, DeleteView):
    model = Program
    cancel_url = OFFER_URL
    success_url = OFFER_URL
    delete_title = "Supprimer la filière"
    delete_warning = (
        "La filière sera supprimée. Elle ne doit plus contenir de matière ; "
        "les classes qui la suivent sont simplement détachées."
    )
    success_message = "Filière supprimée."

    def get_blockers(self):
        return [
            ("matières rattachées", self.object.subjects.count()),
            ("classes qui la suivent", self.object.school_classes.count()),
        ]


# ---------------------------------------------------------------------------
# Matières
# ---------------------------------------------------------------------------

class SubjectListView(AdminMixin, SearchFilterMixin, ListView):
    model = Subject
    template_name = "courses/admin_subjects.html"
    context_object_name = "subjects"
    search_fields = ("name", "code", "program__name", "program__department__name")
    search_placeholder = "Code, intitulé, filière…"

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related("program__department")
            .annotate(
                class_count=Count("teaching_assignments__school_class", distinct=True),
                course_count=Count("courses", distinct=True),
            )
            .order_by("program__name", "semester", "name")
        )

    def get_filters(self):
        university = self.request.university
        programs = Program.objects.filter(university=university).order_by("name")
        semesters = (
            Subject.objects.filter(university=university)
            .order_by("semester").values_list("semester", flat=True).distinct()
        )
        return [
            {"param": "filiere", "lookup": "program_id", "label": "Filière",
             "choices": [(str(program.pk), program.name) for program in programs]},
            {"param": "semestre", "lookup": "semester", "label": "Semestre",
             "choices": [(str(number), "Semestre %d" % number) for number in semesters]},
            {"param": "statut", "lookup": "is_active", "label": "Statut", "bool": True,
             "choices": (("1", "Actives"), ("0", "Archivées"))},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        subjects = Subject.objects.filter(university=self.request.university)
        context["stats"] = {
            "subjects": subjects.count(),
            "active": subjects.filter(is_active=True).count(),
            "credits": sum(subject.credits for subject in subjects.filter(is_active=True)),
            "hours": sum(subject.total_hours for subject in subjects.filter(is_active=True)),
        }
        return context


class SubjectCreateView(_CatalogFormView, CreateView):
    model = Subject
    form_class = SubjectForm
    cancel_url = SUBJECTS_URL
    success_url = SUBJECTS_URL
    page_title = "Nouvelle matière"
    page_icon = "auto_stories"
    submit_label = "Créer la matière"
    success_message = "Matière créée."
    page_hint = "La matière est rattachée à une filière ; elle sera ensuite affectée à des classes et à des professeurs."


class SubjectUpdateView(_UpdateTitleMixin, _CatalogFormView, UpdateView):
    model = Subject
    form_class = SubjectForm
    cancel_url = SUBJECTS_URL
    success_url = SUBJECTS_URL
    page_icon = "auto_stories"
    success_message = "Matière mise à jour."


class SubjectDeleteView(AdminMixin, DeletePageMixin, DeleteView):
    model = Subject
    cancel_url = SUBJECTS_URL
    success_url = SUBJECTS_URL
    delete_title = "Supprimer la matière"
    delete_warning = (
        "La matière sera supprimée. Elle ne doit plus être affectée à une classe ni utilisée par un cours ; "
        "vous pouvez aussi l'archiver en la modifiant."
    )
    success_message = "Matière supprimée."

    def get_blockers(self):
        return [
            ("affectations d'enseignement", self.object.teaching_assignments.count()),
            ("cours", self.object.courses.count()),
        ]


# ---------------------------------------------------------------------------
# Affectations des professeurs
# ---------------------------------------------------------------------------

class AssignmentListView(AdminMixin, SearchFilterMixin, ListView):
    model = TeachingAssignment
    template_name = "courses/admin_assignments.html"
    context_object_name = "assignments"
    search_fields = (
        "subject__name", "subject__code", "school_class__name",
        "professor__membership__user__last_name", "professor__membership__user__first_name",
        "professor__membership__user__email",
    )
    search_placeholder = "Classe, matière, professeur…"

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related(
                "school_class", "subject__program", "professor__membership__user",
            )
            .annotate(slot_count=Count("slots", distinct=True))
            .order_by("school_class__name", "subject__semester", "subject__name")
        )

    def get_filters(self):
        university = self.request.university
        classes = SchoolClass.objects.filter(university=university).order_by("-academic_year", "name")
        professors = ProfessorProfile.objects.filter(university=university).select_related(
            "membership__user",
        )
        return [
            {"param": "classe", "lookup": "school_class_id", "label": "Classe",
             "choices": [(str(item.pk), str(item)) for item in classes]},
            {"param": "professeur", "lookup": "professor_id", "label": "Professeur",
             "choices": [(str(item.pk), professor_label(item)) for item in professors]},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        university = self.request.university
        assignments = TeachingAssignment.objects.filter(university=university)
        classes = SchoolClass.objects.filter(university=university)
        context["stats"] = {
            "assignments": assignments.count(),
            "classes": assignments.values("school_class").distinct().count(),
            "professors": assignments.values("professor").distinct().count(),
            "unassigned_classes": classes.exclude(teaching_assignments__isnull=False).count(),
        }
        return context


class _AssignmentFormView(_CatalogFormView, SelectedClassMixin):
    cancel_url = ASSIGNMENTS_URL

    def get_success_url(self):
        school_class = self.get_selected_class()
        url = str(ASSIGNMENTS_URL)
        return "%s?classe=%d" % (url, school_class.pk) if school_class else url

    def get_cancel_url(self):
        return self.get_success_url()


class AssignmentCreateView(_AssignmentFormView, CreateView):
    model = TeachingAssignment
    form_class = TeachingAssignmentForm
    page_title = "Nouvelle affectation"
    page_icon = "how_to_reg"
    submit_label = "Affecter le professeur"
    success_message = "Affectation enregistrée : le professeur peut désormais publier ses cours pour cette classe."
    page_hint = (
        "Une affectation relie une classe, une matière et le professeur qui l'enseigne. "
        "Elle ouvre l'emploi du temps et la publication des cours."
    )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["school_class"] = self.get_selected_class()
        return kwargs


class AssignmentUpdateView(_UpdateTitleMixin, _AssignmentFormView, UpdateView):
    model = TeachingAssignment
    form_class = TeachingAssignmentForm
    page_icon = "how_to_reg"
    submit_label = "Enregistrer"
    success_message = "Affectation mise à jour."
    page_hint = (
        "Vous pouvez remplacer l'enseignant. Les séances déjà planifiées lui sont transférées "
        "et les cours de l'ancien enseignant sont retirés de la classe."
    )


class AssignmentDeleteView(AdminMixin, DeletePageMixin, DeleteView):
    model = TeachingAssignment
    cancel_url = ASSIGNMENTS_URL
    success_url = ASSIGNMENTS_URL
    delete_title = "Supprimer l'affectation"
    delete_warning = (
        "Le professeur n'enseignera plus cette matière à cette classe : ses séances sont retirées "
        "de l'emploi du temps et ses cours ne sont plus publiés pour cette classe."
    )
    success_message = "Affectation supprimée."

    def get_blockers(self):
        assignment = self.object
        return [
            ("séances de l'emploi du temps", assignment.slots.count()),
            ("publications de cours", CoursePublication.objects.filter(
                school_class=assignment.school_class, course__subject=assignment.subject,
                course__professor=assignment.professor, is_published=True,
            ).count()),
        ]


# ---------------------------------------------------------------------------
# Emploi du temps
# ---------------------------------------------------------------------------

class TimetableView(AdminMixin, TemplateView):
    """Emploi du temps hebdomadaire de chaque classe de l'université."""

    template_name = "courses/admin_timetable.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        university = self.request.university
        everything = SchoolClass.objects.filter(university=university)
        classes = everything
        level = self.request.GET.get("niveau", "").strip()
        program = self.request.GET.get("filiere", "").strip()
        class_pk = self.request.GET.get("classe", "").strip()
        if level:
            classes = classes.filter(level=level)
        if program:
            classes = classes.filter(program=program)
        if class_pk.isdigit():
            classes = classes.filter(pk=int(class_pk))
        classes = list(
            classes.select_related("study_program").prefetch_related("groups").order_by("level", "name")
        )

        slots_by_class = defaultdict(list)
        for slot in ScheduleSlot.objects.filter(assignment__school_class__in=classes).select_related(
            "assignment__school_class", "assignment__subject",
            "assignment__professor__membership__user", "group",
        ):
            slots_by_class[slot.assignment.school_class_id].append(slot)
        pending_by_class = defaultdict(list)
        for assignment in TeachingAssignment.objects.filter(school_class__in=classes).annotate(
            slot_total=Count("slots"),
        ).select_related("subject", "professor__membership__user"):
            if assignment.slot_total == 0:
                pending_by_class[assignment.school_class_id].append(assignment)

        timetables = []
        for school_class in classes:
            class_slots = slots_by_class.get(school_class.pk, [])
            timetables.append({
                "school_class": school_class,
                "grid": build_week_grid(class_slots),
                "professor_count": len({slot.assignment.professor_id for slot in class_slots}),
                "group_count": len(school_class.groups.all()),
                "pending": pending_by_class.get(school_class.pk, []),
            })
        all_slots = [slot for items in slots_by_class.values() for slot in items]
        filters_active = bool(level or program or class_pk)
        context.update({
            "timetables": timetables,
            "week_label": build_week_grid([])["week_label"],
            "class_count": len(timetables),
            "slot_count": len(all_slots),
            "professor_count": len({slot.assignment.professor_id for slot in all_slots}),
            "pending_count": sum(len(items) for items in pending_by_class.values()),
            "level_choices": distinct_choices(everything, "level"),
            "program_choices": distinct_choices(everything, "program"),
            "class_choices": [(str(item.pk), str(item)) for item in everything.order_by("name")],
            "current": {"niveau": level, "filiere": program, "classe": class_pk},
            "filters_active": filters_active,
        })
        return context


class _SlotFormView(_CatalogFormView, SelectedClassMixin):
    page_icon = "calendar_month"
    cancel_url = TIMETABLE_URL

    def get_slot_class(self):
        return self.get_selected_class()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["school_class"] = self.get_slot_class()
        return kwargs

    def get_success_url(self):
        school_class = self.get_slot_class()
        url = str(TIMETABLE_URL)
        return "%s?classe=%d" % (url, school_class.pk) if school_class else url

    def get_cancel_url(self):
        return self.get_success_url()


class SlotCreateView(_SlotFormView, CreateView):
    model = ScheduleSlot
    form_class = ScheduleSlotForm
    page_title = "Planifier une séance"
    submit_label = "Planifier la séance"
    success_message = "Séance planifiée."
    page_hint = (
        "Les conflits sont détectés : une classe, un professeur ou une salle ne peut pas "
        "avoir deux séances qui se chevauchent."
    )


class SlotUpdateView(_UpdateTitleMixin, _SlotFormView, UpdateView):
    model = ScheduleSlot
    form_class = ScheduleSlotForm
    submit_label = "Enregistrer"
    success_message = "Séance mise à jour."

    def get_slot_class(self):
        return self.object.assignment.school_class


class SlotDeleteView(AdminMixin, DeletePageMixin, DeleteView):
    model = ScheduleSlot
    cancel_url = TIMETABLE_URL
    success_url = TIMETABLE_URL
    delete_title = "Supprimer la séance"
    delete_warning = "La séance sera retirée de l'emploi du temps de la classe et du professeur."
    success_message = "Séance supprimée."


# ---------------------------------------------------------------------------
# Supervision des cours
# ---------------------------------------------------------------------------

class CourseListView(AdminMixin, SearchFilterMixin, ListView):
    """Tous les cours de l'université (lecture seule : les professeurs les gèrent)."""

    model = Course
    template_name = "courses/admin_courses.html"
    context_object_name = "courses"
    search_fields = (
        "title", "subject__name", "subject__code",
        "professor__membership__user__last_name", "professor__membership__user__first_name",
    )
    search_placeholder = "Titre, matière, professeur…"

    def get_queryset(self):
        qs = (
            super().get_queryset()
            .select_related("subject__program__department", "professor__membership__user")
            .annotate(
                chapter_count=Count("chapters", distinct=True),
                material_count=Count("materials", distinct=True),
                published_count=Count(
                    "publications", filter=Q(publications__is_published=True), distinct=True,
                ),
            )
            .order_by("subject__program__name", "subject__name", "title")
        )
        status = self.request.GET.get("statut", "")
        if status == "publie":
            qs = qs.filter(published_count__gt=0)
        elif status == "brouillon":
            qs = qs.filter(published_count=0)
        return qs

    def get_filters(self):
        university = self.request.university
        programs = Program.objects.filter(university=university).order_by("name")
        professors = ProfessorProfile.objects.filter(
            university=university, courses__isnull=False,
        ).distinct().select_related("membership__user")
        return [
            {"param": "filiere", "lookup": "subject__program_id", "label": "Filière",
             "choices": [(str(program.pk), program.name) for program in programs]},
            {"param": "professeur", "lookup": "professor_id", "label": "Professeur",
             "choices": [(str(item.pk), display_name(item.user)) for item in professors]},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        university = self.request.university
        courses = Course.objects.filter(university=university)
        published = courses.filter(publications__is_published=True).distinct().count()
        status = self.request.GET.get("statut", "")
        context.update({
            "status": status if status in ("publie", "brouillon") else "",
            "stats": {
                "courses": courses.count(),
                "published": published,
                "drafts": courses.count() - published,
                "professors": courses.values("professor").distinct().count(),
            },
        })
        context["is_filtered"] = context["is_filtered"] or bool(context["status"])
        return context


class CourseDetailView(AdminMixin, DetailView):
    model = Course
    template_name = "courses/admin_course_detail.html"
    context_object_name = "course"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "subject__program__department", "professor__membership__user",
        ).prefetch_related("chapters__materials", "materials", "publications__school_class")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.object
        context.update({
            "chapters": list(course.chapters.all()),
            "general_materials": [m for m in course.materials.all() if m.chapter_id is None],
            "publications": list(course.publications.all()),
            "back_url": reverse("courses:admin_courses"),
        })
        return context
