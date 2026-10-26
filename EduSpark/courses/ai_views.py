"""Plan de cours assisté par IA (portail professeur).

L'IA propose, le professeur décide : la génération n'écrit rien en base ; elle
affiche un aperçu modifiable (ajout, suppression, réordonnancement des
chapitres, objectifs et durées), et seuls les chapitres validés par le bouton
« Enregistrer » sont créés. Si l'IA est indisponible, le professeur est
redirigé vers le même aperçu, vide, pour saisir son plan à la main.
"""

import logging

from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic import FormView, View
from django.views.generic.base import ContextMixin, TemplateResponseMixin

from accounts.models import SchoolClass

from .forms import ChapterDraftFormSet, SyllabusRequestForm
from .mixins import ProfessorMixin
from .models import Chapter, Course
from .services import ai

logger = logging.getLogger(__name__)

EYEBROW = "Cours"
PREVIEW_TEMPLATE = "courses/ai_syllabus_preview.html"
MODE_MANUAL = "manual"
MODE_LABELS = {
    ai.MODE_LOCAL_API: "Analyse locale + Rédaction API",
    ai.MODE_API_ONLY: "Rédaction API seule",
    MODE_MANUAL: "Saisie manuelle",
}
LOCAL_NOTICES = {
    ai.LOCAL_NO_MATERIALS: (
        "Ce cours n'a pas encore de support lisible (PDF, PowerPoint, Word) : "
        "le plan a été rédigé à partir du titre et du niveau."
    ),
    ai.LOCAL_UNAVAILABLE: (
        "L'analyse locale de vos supports n'a pas répondu à temps : "
        "le plan a été rédigé à partir du titre et du niveau seulement."
    ),
}
UNAVAILABLE_MESSAGE = (
    "L'assistant IA est indisponible pour le moment. "
    "Saisissez votre plan ci-dessous : le reste du module fonctionne normalement."
)


class _SyllabusMixin(ProfessorMixin):
    """Cours du professeur courant, dans l'université courante (sinon 404)."""

    def get_course(self):
        if not hasattr(self, "_course"):
            self._course = get_object_or_404(
                Course.objects.select_related("subject__program"),
                pk=self.kwargs["pk"], university=self.request.university, professor=self.professor,
            )
        return self._course

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "course": self.get_course(),
            "eyebrow": EYEBROW,
            "detail_url": reverse("courses:prof_course_detail", args=[self.get_course().pk]),
        })
        return context

    def preview_context(self, formset, mode, topics=(), local_status=""):
        return self.get_context_data(
            formset=formset,
            mode=mode,
            mode_label=MODE_LABELS[mode],
            topics=list(topics),
            local_notice=LOCAL_NOTICES.get(local_status, ""),
        )


class SyllabusGenerateView(_SyllabusMixin, FormView):
    """GET : options de génération. POST : lance le pipeline et affiche l'aperçu."""

    form_class = SyllabusRequestForm
    template_name = "courses/ai_syllabus_form.html"

    def get_initial(self):
        course = self.get_course()
        school_class = (
            SchoolClass.objects.filter(
                teaching_assignments__professor=self.professor,
                teaching_assignments__subject=course.subject,
            ).order_by("-academic_year", "name").first()
        )
        level = (school_class.level or school_class.name) if school_class else ""
        return {"title": course.title, "level": level}

    def form_valid(self, form):
        course = self.get_course()
        try:
            result = ai.generate_syllabus(
                form.cleaned_data["title"], form.cleaned_data["level"],
                course_id=course.pk, options=form.options(), user_id=self.request.user.pk,
            )
        except ai.RateLimitExceeded as error:
            messages.warning(self.request, str(error))
            return redirect("courses:prof_ai_syllabus_manual", pk=course.pk)
        except ai.AIUnavailable as error:
            logger.warning("Plan de cours IA indisponible (cours %s) : %s", course.pk, error)
            messages.warning(self.request, UNAVAILABLE_MESSAGE)
            return redirect("courses:prof_ai_syllabus_manual", pk=course.pk)

        formset = ChapterDraftFormSet(initial=[
            {
                "title": chapter["title"],
                "objectives": "\n".join(chapter["objectives"]),
                "duration_hours": chapter["duration_hours"],
            }
            for chapter in result["chapters"]
        ])
        return TemplateResponse(self.request, PREVIEW_TEMPLATE, self.preview_context(
            formset, result["mode"], result["topics"], result["local_status"],
        ))


class SyllabusManualView(_SyllabusMixin, ContextMixin, TemplateResponseMixin, View):
    """Aperçu vide : saisie manuelle du plan, sans IA."""

    template_name = PREVIEW_TEMPLATE

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.preview_context(ChapterDraftFormSet(), MODE_MANUAL))


class SyllabusSaveView(_SyllabusMixin, ContextMixin, TemplateResponseMixin, View):
    """Crée les chapitres validés par le professeur, en une seule transaction."""

    http_method_names = ["post"]
    template_name = PREVIEW_TEMPLATE

    def post(self, request, *args, **kwargs):
        course = self.get_course()
        formset = ChapterDraftFormSet(request.POST)
        if not formset.is_valid():
            mode = request.POST.get("mode")
            topics = [topic[:120] for topic in request.POST.getlist("topics")[:ai.MAX_TOPICS]]
            return self.render_to_response(self.preview_context(
                formset, mode if mode in MODE_LABELS else MODE_MANUAL, topics,
            ))

        with transaction.atomic():
            # Verrouille le cours : deux enregistrements simultanés ne
            # produisent pas deux chapitres avec le même numéro.
            Course.objects.select_for_update().filter(pk=course.pk).first()
            last = course.chapters.aggregate(last=Max("order"))["last"] or 0
            chapters = [
                Chapter(
                    course=course,
                    title=form.cleaned_data["title"].strip(),
                    objectives=form.cleaned_data["objectives"],
                    duration_hours=form.cleaned_data.get("duration_hours"),
                    order=last + position,
                )
                for position, form in enumerate(formset.ordered_forms, start=1)
            ]
            Chapter.objects.bulk_create(chapters)
        messages.success(request, "%d chapitre%s ajouté%s au cours." % (
            len(chapters), "s" if len(chapters) > 1 else "", "s" if len(chapters) > 1 else "",
        ))
        return redirect("courses:prof_course_detail", pk=course.pk)
