"""Portail professeur : ses matières, son emploi du temps, ses cours (chapitres
et supports) et la publication de chaque cours pour chacune de ses classes."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView,
)

from accounts.models import SchoolClass
from accounts.tenancy import Role, tenant_required
from accounts.view_mixins import SearchFilterMixin, SuccessMessageMixin

from . import files
from .forms import ChapterForm, CourseForm, MaterialForm
from .mixins import DeletePageMixin, FormPageMixin, ProfessorMixin
from .models import (
    Chapter, Course, CourseMaterial, ScheduleSlot, TeachingAssignment,
)
from .services import build_week_grid, next_session, set_publication

COURSES_URL = reverse_lazy("courses:prof_course")
MATERIALS_URL = reverse_lazy("courses:prof_course_materials")
EYEBROW = "Cours"


def _own_course_or_404(request, professor, pk):
    return get_object_or_404(
        Course, pk=pk, university=request.university, professor=professor,
    )


# ---------------------------------------------------------------------------
# Mes matières et mon emploi du temps
# ---------------------------------------------------------------------------

class SubjectsView(ProfessorMixin, TemplateView):
    """Matières que le professeur enseigne, d'après les affectations de l'administration."""

    template_name = "courses/prof_subjects.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        assignments = (
            TeachingAssignment.objects.filter(
                university=self.request.university, professor=self.professor,
            )
            .select_related("school_class", "subject__program__department")
            .annotate(
                student_total=Count("school_class__groups__students", distinct=True),
                slot_total=Count("slots", distinct=True),
            )
            .order_by("subject__semester", "subject__name", "-school_class__academic_year", "school_class__name")
        )
        courses_by_subject = {}
        for course in Course.objects.filter(
            university=self.request.university, professor=self.professor,
        ).annotate(
            published_total=Count("publications", filter=Q(publications__is_published=True), distinct=True),
        ):
            courses_by_subject.setdefault(course.subject_id, []).append(course)

        rows = {}
        for assignment in assignments:
            row = rows.setdefault(assignment.subject_id, {
                "subject": assignment.subject, "assignments": [], "students": 0, "slots": 0,
                "courses": courses_by_subject.get(assignment.subject_id, []),
            })
            row["assignments"].append(assignment)
            row["students"] += assignment.student_total
            row["slots"] += assignment.slot_total
        rows = list(rows.values())
        subjects = [row["subject"] for row in rows]
        context.update({
            "rows": rows,
            "stats": {
                "subjects": len(rows),
                "classes": len({a.school_class_id for row in rows for a in row["assignments"]}),
                "hours": sum(subject.total_hours for subject in subjects),
                "credits": sum(subject.credits for subject in subjects),
            },
        })
        return context


class TimetableView(ProfessorMixin, TemplateView):
    template_name = "courses/prof_timetable.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slots = list(
            ScheduleSlot.objects.filter(
                university=self.request.university, assignment__professor=self.professor,
            ).select_related(
                "assignment__school_class", "assignment__subject",
                "assignment__professor__membership__user", "group",
            )
        )
        grid = build_week_grid(slots)
        context.update({
            "grid": grid,
            "next_session": next_session(slots),
            "class_count": len({slot.assignment.school_class_id for slot in slots}),
            "subject_count": len({slot.assignment.subject_id for slot in slots}),
        })
        return context


# ---------------------------------------------------------------------------
# Cours
# ---------------------------------------------------------------------------

class CourseListView(ProfessorMixin, SearchFilterMixin, ListView):
    model = Course
    template_name = "courses/prof_course.html"
    context_object_name = "courses"
    search_fields = ("title", "subject__name", "subject__code")
    search_placeholder = "Titre ou matière…"

    def get_queryset(self):
        return (
            super().get_queryset()
            .filter(university=self.request.university, professor=self.professor)
            .select_related("subject__program")
            .annotate(
                chapter_count=Count("chapters", distinct=True),
                material_count=Count("materials", distinct=True),
                published_count=Count(
                    "publications", filter=Q(publications__is_published=True), distinct=True,
                ),
            )
            .order_by("subject__name", "title")
        )

    def get_filters(self):
        subjects = {
            assignment.subject_id: assignment.subject
            for assignment in TeachingAssignment.objects.filter(
                professor=self.professor,
            ).select_related("subject")
        }
        return [{
            "param": "matiere", "lookup": "subject_id", "label": "Matière",
            "choices": [
                (str(pk), "%s · %s" % (subject.code, subject.name))
                for pk, subject in sorted(subjects.items(), key=lambda item: item[1].name)
            ],
        }]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        assigned = dict(
            TeachingAssignment.objects.filter(professor=self.professor)
            .values_list("subject_id").annotate(total=Count("school_class", distinct=True))
        )
        for course in context["courses"]:
            course.assigned_class_count = assigned.get(course.subject_id, 0)
            course.to_publish = max(course.assigned_class_count - course.published_count, 0)
        own = Course.objects.filter(university=self.request.university, professor=self.professor)
        context["stats"] = {
            "courses": own.count(),
            "chapters": Chapter.objects.filter(course__in=own).count(),
            "materials": CourseMaterial.objects.filter(course__in=own).count(),
            "published": own.filter(publications__is_published=True).distinct().count(),
        }
        context["can_create"] = bool(assigned)
        return context


class CourseDetailView(ProfessorMixin, DetailView):
    model = Course
    template_name = "courses/prof_course_detail.html"
    context_object_name = "course"

    def get_queryset(self):
        return (
            super().get_queryset()
            .filter(university=self.request.university, professor=self.professor)
            .select_related("subject__program__department")
            .prefetch_related("chapters__materials", "materials", "publications")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.object
        publications = {item.school_class_id: item for item in course.publications.all()}
        classes = (
            SchoolClass.objects.filter(
                teaching_assignments__professor=self.professor,
                teaching_assignments__subject=course.subject,
            )
            .annotate(student_total=Count("groups__students", distinct=True))
            .order_by("-academic_year", "name")
            .distinct()
        )
        class_rows = []
        for school_class in classes:
            publication = publications.get(school_class.pk)
            class_rows.append({
                "school_class": school_class,
                "publication": publication,
                "is_published": bool(publication and publication.is_published),
            })
        slots = ScheduleSlot.objects.filter(
            assignment__professor=self.professor, assignment__subject=course.subject,
        ).select_related("assignment__school_class", "group")
        chapters = list(course.chapters.all())
        context.update({
            "chapters": chapters,
            "general_materials": [item for item in course.materials.all() if item.chapter_id is None],
            "class_rows": class_rows,
            "published_total": sum(1 for row in class_rows if row["is_published"]),
            "slots": slots,
            "material_total": len(course.materials.all()),
        })
        return context


class _CourseFormView(ProfessorMixin, FormPageMixin, SuccessMessageMixin):
    eyebrow = EYEBROW
    page_icon = "menu_book"
    cancel_url = COURSES_URL

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["professor"] = self.professor
        return kwargs


class CourseCreateView(_CourseFormView, CreateView):
    model = Course
    form_class = CourseForm
    page_title = "Nouveau cours"
    submit_label = "Créer le cours"
    success_message = "Cours créé : ajoutez vos chapitres et vos supports, puis publiez-le pour vos classes."
    page_hint = "Le cours est lié à une matière qui vous est affectée ; vous le publierez ensuite classe par classe."

    def get(self, request, *args, **kwargs):
        if not TeachingAssignment.objects.filter(professor=self.professor).exists():
            messages.info(
                request,
                "Aucune matière ne vous est encore affectée : l'administration de votre université "
                "doit d'abord vous affecter à une classe.",
            )
            return redirect("courses:prof_course")
        return super().get(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        subject = self.request.GET.get("matiere", "")
        if subject.isdigit():
            initial["subject"] = int(subject)
        return initial

    def get_success_url(self):
        return reverse("courses:prof_course_detail", args=[self.object.pk])


class CourseUpdateView(_CourseFormView, UpdateView):
    model = Course
    form_class = CourseForm
    submit_label = "Enregistrer"
    success_message = "Cours mis à jour."

    def get_queryset(self):
        return Course.objects.filter(university=self.request.university, professor=self.professor)

    def get_context_data(self, **kwargs):
        self.page_title = "Modifier — %s" % self.object.title
        return super().get_context_data(**kwargs)

    def get_cancel_url(self):
        return reverse("courses:prof_course_detail", args=[self.object.pk])

    def get_success_url(self):
        return self.get_cancel_url()


class CourseDeleteView(ProfessorMixin, DeletePageMixin, DeleteView):
    model = Course
    eyebrow = EYEBROW
    cancel_url = COURSES_URL
    success_url = COURSES_URL
    delete_title = "Supprimer le cours"
    delete_warning = (
        "Le cours, ses chapitres et ses supports seront supprimés définitivement, "
        "et retirés de toutes les classes où il est publié."
    )
    success_message = "Cours supprimé."

    def get_queryset(self):
        return Course.objects.filter(university=self.request.university, professor=self.professor)

    def get_blockers(self):
        course = self.object
        return [
            ("chapitres", course.chapters.count()),
            ("supports de cours", course.materials.count()),
            ("classes où il est publié", course.publications.filter(is_published=True).count()),
        ]

    def get_cancel_url(self):
        return reverse("courses:prof_course_detail", args=[self.get_object().pk])


@tenant_required(Role.PROFESSOR)
@require_POST
def course_publication(request, pk, class_pk):
    """Publie ou retire un cours pour une classe où le professeur enseigne la matière."""
    professor = request.membership.ensure_profile()
    course = _own_course_or_404(request, professor, pk)
    school_class = get_object_or_404(SchoolClass, pk=class_pk, university=request.university)
    publish = request.POST.get("action") == "publier"
    try:
        set_publication(course, school_class, publish)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if publish:
            messages.success(request, "Cours publié : les étudiants de %s peuvent le consulter." % school_class.name)
        else:
            messages.success(request, "Cours retiré : il n'est plus visible des étudiants de %s." % school_class.name)
    return redirect("courses:prof_course_detail", pk=course.pk)


# ---------------------------------------------------------------------------
# Chapitres
# ---------------------------------------------------------------------------

class _ChapterMixin(ProfessorMixin):
    def get_course(self):
        if not hasattr(self, "_course"):
            self._course = _own_course_or_404(self.request, self.professor, self.kwargs["pk"])
        return self._course

    def get_cancel_url(self):
        return reverse("courses:prof_course_detail", args=[self.get_course().pk])

    def get_success_url(self):
        return self.get_cancel_url()


class _ChapterFormView(_ChapterMixin, FormPageMixin, SuccessMessageMixin):
    eyebrow = EYEBROW
    page_icon = "view_agenda"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["course"] = self.get_course()
        return kwargs


class ChapterCreateView(_ChapterFormView, CreateView):
    model = Chapter
    form_class = ChapterForm
    submit_label = "Ajouter le chapitre"
    success_message = "Chapitre ajouté."

    def get_context_data(self, **kwargs):
        self.page_title = "Nouveau chapitre — %s" % self.get_course().title
        return super().get_context_data(**kwargs)


class ChapterUpdateView(_ChapterFormView, UpdateView):
    model = Chapter
    form_class = ChapterForm
    submit_label = "Enregistrer"
    success_message = "Chapitre mis à jour."

    def get_queryset(self):
        return Chapter.objects.filter(course=self.get_course())

    def get_object(self, queryset=None):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["chapter_pk"])

    def get_context_data(self, **kwargs):
        self.page_title = "Modifier — %s" % self.object.title
        return super().get_context_data(**kwargs)


class ChapterDeleteView(_ChapterMixin, DeletePageMixin, DeleteView):
    model = Chapter
    eyebrow = EYEBROW
    delete_title = "Supprimer le chapitre"
    delete_warning = "Le chapitre et les supports qui lui sont rattachés seront supprimés définitivement."
    success_message = "Chapitre supprimé."

    def get_queryset(self):
        return Chapter.objects.filter(course=self.get_course())

    def get_object(self, queryset=None):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["chapter_pk"])

    def get_blockers(self):
        return [("supports de cours rattachés", self.object.materials.count())]


@tenant_required(Role.PROFESSOR)
@require_POST
def chapter_move(request, pk, chapter_pk, direction):
    """Remonte ou descend un chapitre dans l'ordre du cours."""
    professor = request.membership.ensure_profile()
    course = _own_course_or_404(request, professor, pk)
    chapter = get_object_or_404(Chapter, pk=chapter_pk, course=course)
    siblings = list(course.chapters.order_by("order", "pk"))
    index = siblings.index(chapter)
    target = index - 1 if direction == "monter" else index + 1
    if 0 <= target < len(siblings):
        siblings[index], siblings[target] = siblings[target], siblings[index]
    # Renumérote de 1 à n : l'ordre reste cohérent même si des numéros étaient égaux.
    for position, item in enumerate(siblings, start=1):
        if item.order != position:
            item.order = position
            item.save(update_fields=["order"])
    return redirect("courses:prof_course_detail", pk=course.pk)


# ---------------------------------------------------------------------------
# Supports de cours
# ---------------------------------------------------------------------------

class MaterialListView(ProfessorMixin, SearchFilterMixin, ListView):
    """Bibliothèque des supports déposés par le professeur, tous cours confondus."""

    model = CourseMaterial
    template_name = "courses/prof_course_materials.html"
    context_object_name = "materials"
    search_fields = ("title", "original_name", "course__title", "course__subject__name")
    search_placeholder = "Support, cours, matière…"

    def get_queryset(self):
        return (
            super().get_queryset()
            .filter(course__university=self.request.university, course__professor=self.professor)
            .select_related("course__subject", "chapter")
            .order_by("-created_at", "-pk")
        )

    def get_filters(self):
        courses = Course.objects.filter(
            university=self.request.university, professor=self.professor,
        ).select_related("subject").order_by("subject__name", "title")
        return [
            {"param": "cours", "lookup": "course_id", "label": "Cours",
             "choices": [(str(course.pk), "%s — %s" % (course.subject.code, course.title)) for course in courses]},
            {"param": "type", "lookup": "material_type", "label": "Type",
             "choices": list(files.TYPE_CHOICES)},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        own = CourseMaterial.objects.filter(
            course__university=self.request.university, course__professor=self.professor,
        )
        context["stats"] = {
            "materials": own.count(),
            "pdf": own.filter(material_type=files.PDF).count(),
            "media": own.filter(material_type__in=(files.VIDEO, files.AUDIO)).count(),
            "size": files.format_size(sum(own.values_list("size", flat=True))),
        }
        context["has_courses"] = Course.objects.filter(
            university=self.request.university, professor=self.professor,
        ).exists()
        return context


class _MaterialMixin(ProfessorMixin):
    def get_queryset(self):
        return CourseMaterial.objects.filter(
            course__university=self.request.university, course__professor=self.professor,
        ).select_related("course", "chapter")


class MaterialCreateView(_MaterialMixin, FormPageMixin, SuccessMessageMixin, CreateView):
    model = CourseMaterial
    form_class = MaterialForm
    eyebrow = EYEBROW
    page_title = "Ajouter un support"
    page_icon = "upload_file"
    submit_label = "Déposer le support"
    success_message = "Support déposé."
    page_hint = (
        "Le support sera visible des étudiants des classes pour lesquelles le cours est publié. "
        "Les fichiers ne sont accessibles qu'après authentification."
    )

    def get_course(self):
        if not hasattr(self, "_course"):
            pk = self.request.GET.get("cours", "")
            self._course = (
                Course.objects.filter(
                    pk=int(pk), university=self.request.university, professor=self.professor,
                ).first() if pk.isdigit() else None
            )
        return self._course

    def get_initial(self):
        initial = super().get_initial()
        chapter = self.request.GET.get("chapitre", "")
        course = self.get_course()
        if chapter.isdigit() and course is not None and course.chapters.filter(pk=int(chapter)).exists():
            initial["chapter"] = int(chapter)
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["professor"] = self.professor
        kwargs["course"] = self.get_course()
        return kwargs

    def form_valid(self, form):
        form.instance.uploaded_by = self.request.user
        return super().form_valid(form)

    def get_cancel_url(self):
        course = self.get_course()
        if course is not None:
            return reverse("courses:prof_course_detail", args=[course.pk])
        return str(MATERIALS_URL)

    def get_success_url(self):
        return reverse("courses:prof_course_detail", args=[self.object.course_id])


class MaterialUpdateView(_MaterialMixin, FormPageMixin, SuccessMessageMixin, UpdateView):
    model = CourseMaterial
    form_class = MaterialForm
    eyebrow = EYEBROW
    page_icon = "edit_document"
    submit_label = "Enregistrer"
    success_message = "Support mis à jour."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["professor"] = self.professor
        return kwargs

    def get_context_data(self, **kwargs):
        self.page_title = "Modifier — %s" % self.object.title
        return super().get_context_data(**kwargs)

    def get_cancel_url(self):
        return reverse("courses:prof_course_detail", args=[self.object.course_id])

    def get_success_url(self):
        return self.get_cancel_url()


class MaterialDeleteView(_MaterialMixin, DeletePageMixin, DeleteView):
    model = CourseMaterial
    eyebrow = EYEBROW
    delete_title = "Supprimer le support"
    delete_warning = "Le fichier sera supprimé définitivement ; les étudiants ne pourront plus le consulter."
    success_message = "Support supprimé."

    def get_cancel_url(self):
        return reverse("courses:prof_course_detail", args=[self.get_object().course_id])

    def get_success_url(self):
        return self.get_cancel_url()
