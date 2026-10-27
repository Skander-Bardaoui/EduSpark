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
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic import FormView, View
from django.views.generic.base import ContextMixin, TemplateResponseMixin

from accounts.models import SchoolClass

from .forms import ChapterDraftFormSet, SyllabusRequestForm
from .mixins import ProfessorMixin
from .models import Chapter, Course
from .services import ai, jobs
from .tasks import STATUS_OK, STATUS_UNAVAILABLE, generate_syllabus_task

logger = logging.getLogger(__name__)

JOBS_SESSION_KEY = "courses_ai_jobs"
MAX_JOBS = 10

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

    def preview_context(self, formset, mode, topics=(), local_status="", timings=None):
        return self.get_context_data(
            formset=formset,
            mode=mode,
            mode_label=MODE_LABELS[mode],
            topics=list(topics),
            local_notice=LOCAL_NOTICES.get(local_status, ""),
            timings=timings,
        )

    def render_result(self, result):
        """Aperçu modifiable à partir du résultat de la tâche de génération."""
        course = self.get_course()
        if result.get("status") != STATUS_OK:
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
            formset, result["mode"], result["topics"], result["local_status"], result.get("timings"),
        ))


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
            ai.check_rate_limit(self.request.user.pk)
        except ai.RateLimitExceeded as error:
            messages.warning(self.request, str(error))
            return redirect("courses:prof_ai_syllabus_manual", pk=course.pk)

        args = (form.cleaned_data["title"], form.cleaned_data["level"], course.pk, form.options())
        job_id = jobs.submit(generate_syllabus_task, *args)
        job = jobs.get(job_id)
        if jobs.is_ready(job):  # tâche déjà terminée (exécution immédiate des tests)
            return self.render_result(job_result(job))
        remember_job(self.request, job_id, course.pk)
        return redirect("courses:prof_ai_syllabus_wait", pk=course.pk, job_id=job_id)


def job_result(job):
    """Résultat d'une tâche terminée ; une tâche en échec ou expirée est « indisponible »."""
    result = job and job.get("result")
    return result if isinstance(result, dict) else {"status": STATUS_UNAVAILABLE}


def remember_job(request, job_id, course_id):
    """Seul le professeur qui a lancé une génération peut en suivre le résultat."""
    known = request.session.get(JOBS_SESSION_KEY, {})
    known = dict(list(known.items())[-(MAX_JOBS - 1):])
    known[str(job_id)] = course_id
    request.session[JOBS_SESSION_KEY] = known


class _JobMixin(_SyllabusMixin):
    """Tâche de génération lancée par ce professeur, pour ce cours (sinon 404)."""

    def get_job_id(self):
        job_id = str(self.kwargs["job_id"])
        if self.request.session.get(JOBS_SESSION_KEY, {}).get(job_id) != self.get_course().pk:
            raise Http404("Génération inconnue")
        return job_id

    def job_urls(self, job_id):
        pk = self.get_course().pk
        return {
            "status_url": reverse("courses:prof_ai_syllabus_status", args=[pk, job_id]),
            "result_url": reverse("courses:prof_ai_syllabus_result", args=[pk, job_id]),
            "manual_url": reverse("courses:prof_ai_syllabus_manual", args=[pk]),
        }


class SyllabusWaitView(_JobMixin, ContextMixin, TemplateResponseMixin, View):
    """Page d'attente : la génération tourne en arrière-plan (courses.services.jobs)."""

    template_name = "courses/ai_syllabus_wait.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data(**self.job_urls(self.get_job_id())))


class SyllabusStatusView(_JobMixin, View):
    """État de la tâche en JSON, interrogé par la page d'attente."""

    def get(self, request, *args, **kwargs):
        job = jobs.get(self.get_job_id())
        state = job["state"] if job else "EXPIRED"
        return JsonResponse({"state": state, "ready": jobs.is_ready(job)})


class SyllabusResultView(_JobMixin, ContextMixin, View):
    """Affiche l'aperçu dès que la tâche est terminée (sinon retour à l'attente)."""

    def get(self, request, *args, **kwargs):
        job_id = self.get_job_id()
        job = jobs.get(job_id)
        if not jobs.is_ready(job):
            return redirect("courses:prof_ai_syllabus_wait", pk=self.get_course().pk, job_id=job_id)
        return self.render_result(job_result(job))


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
