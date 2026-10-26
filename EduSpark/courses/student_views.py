"""Portail étudiant : emploi du temps de sa classe, matières et enseignants,
cours publiés pour sa classe et leurs supports.

La classe d'un étudiant est celle de ses groupes (``StudentGroup``). Un cours
n'est visible que s'il est publié pour cette classe : c'est le professeur qui
décide, classe par classe.
"""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import DetailView, ListView, TemplateView

from accounts.view_mixins import SearchFilterMixin

from . import files
from .mixins import StudentMixin
from .models import Course, CourseMaterial, CoursePublication, TeachingAssignment
from .services import (
    build_week_grid, next_session, pick_class, published_courses, slots_for_student,
    student_classes, visible_course_ids,
)


class _StudentClassMixin(StudentMixin):
    """Classe affichée : celle demandée (?classe=) parmi les siennes, sinon la plus récente."""

    @cached_property
    def classes(self):
        return list(student_classes(self.student))

    @cached_property
    def school_class(self):
        return pick_class(self.classes, self.request.GET.get("classe"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "profile": self.student,
            "school_class": self.school_class,
            "student_classes": self.classes,
        })
        return context


class CatalogueView(_StudentClassMixin, TemplateView):
    """Matières de la classe, avec leurs enseignants et les cours publiés."""

    template_name = "courses/student_catalogue.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = []
        school_class = self.school_class
        if school_class is not None:
            publication = CoursePublication.objects.filter(
                course=OuterRef("pk"), school_class=school_class, is_published=True,
            )
            courses = published_courses(school_class).annotate(
                chapter_count=Count("chapters", distinct=True),
                material_count=Count("materials", distinct=True),
                published_on=Subquery(publication.values("published_at")[:1]),
            ).order_by("title")
            courses_by_subject = defaultdict(list)
            for course in courses:
                courses_by_subject[course.subject_id].append(course)
            by_subject = {}
            for assignment in TeachingAssignment.objects.filter(
                school_class=school_class,
            ).select_related("subject__program", "professor__membership__user").order_by(
                "subject__semester", "subject__name", "professor__membership__user__last_name",
            ):
                row = by_subject.setdefault(assignment.subject_id, {
                    "subject": assignment.subject,
                    "professors": [],
                    "courses": courses_by_subject.get(assignment.subject_id, []),
                })
                row["professors"].append(assignment.professor)
            rows = list(by_subject.values())
        context.update({
            "rows": rows,
            "stats": {
                "subjects": len(rows),
                "courses": sum(len(row["courses"]) for row in rows),
                "professors": len({prof.pk for row in rows for prof in row["professors"]}),
                "credits": sum(row["subject"].credits for row in rows),
            },
        })
        return context


class CourseDetailView(_StudentClassMixin, DetailView):
    model = Course
    template_name = "courses/student_course_detail.html"
    context_object_name = "course"

    def get_queryset(self):
        return (
            Course.objects.filter(
                university=self.request.university,
                publications__is_published=True,
                publications__school_class__in=self.classes,
            )
            .select_related("subject__program__department", "professor__membership__user")
            .prefetch_related("chapters__materials", "materials")
            .distinct()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.object
        published_for = [
            school_class for school_class in self.classes
            if CoursePublication.objects.filter(
                course=course, school_class=school_class, is_published=True,
            ).exists()
        ]
        slots = []
        for school_class in published_for:
            slots.extend(
                slots_for_student(self.student, school_class).filter(
                    assignment__subject=course.subject, assignment__professor=course.professor,
                )
            )
        context.update({
            "chapters": list(course.chapters.all()),
            "general_materials": [item for item in course.materials.all() if item.chapter_id is None],
            "material_total": len(course.materials.all()),
            "published_for": published_for,
            "slots": slots,
        })
        return context


class MaterialListView(_StudentClassMixin, SearchFilterMixin, ListView):
    """Bibliothèque des supports des cours publiés pour la classe."""

    model = CourseMaterial
    template_name = "courses/student_course_materials.html"
    context_object_name = "materials"
    search_fields = ("title", "original_name", "course__title", "course__subject__name", "course__subject__code")
    search_placeholder = "Support, matière, cours…"

    def get_queryset(self):
        qs = super().get_queryset()
        if self.school_class is None:
            return qs.none()
        return (
            qs.filter(course_id__in=visible_course_ids(self.school_class))
            .select_related("course__subject", "course__professor__membership__user", "chapter")
            .order_by("-created_at", "-pk")
        )

    def get_filters(self):
        subjects = {}
        if self.school_class is not None:
            for course in published_courses(self.school_class):
                subjects[course.subject_id] = course.subject
        return [
            {"param": "matiere", "lookup": "course__subject_id", "label": "Matière",
             "choices": [
                 (str(pk), "%s · %s" % (subject.code, subject.name))
                 for pk, subject in sorted(subjects.items(), key=lambda item: item[1].name)
             ]},
            {"param": "type", "lookup": "material_type", "label": "Type",
             "choices": list(files.TYPE_CHOICES)},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        everything = CourseMaterial.objects.none()
        if self.school_class is not None:
            everything = CourseMaterial.objects.filter(course_id__in=visible_course_ids(self.school_class))
        week_ago = timezone.now() - timedelta(days=7)
        context["stats"] = {
            "materials": everything.count(),
            "recent": everything.filter(created_at__gte=week_ago).count(),
            "subjects": everything.values("course__subject").distinct().count(),
            "media": everything.filter(material_type__in=(files.VIDEO, files.AUDIO)).count(),
        }
        return context


class TimetableView(_StudentClassMixin, TemplateView):
    template_name = "courses/student_timetable.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slots = []
        if self.school_class is not None:
            slots = list(slots_for_student(self.student, self.school_class))
        grid = build_week_grid(slots)
        context.update({
            "grid": grid,
            "next_session": next_session(slots),
            "professor_count": len({slot.assignment.professor_id for slot in slots}),
            "subject_count": len({slot.assignment.subject_id for slot in slots}),
        })
        return context
