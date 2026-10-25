"""Pages et APIs du test de langue orale (espace étudiant et référent)."""

import json
import logging
import random
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import role_required
from accounts.models import Profil

from ..models import LanguageTestFeedback, LanguageTestSession
from ..services import caseload, display_name, get_professor, get_student, person_initials
from ..utils import fr_date_time, fr_day_short, fr_decimal, percent
from . import services
from .config import (
    EXAMS,
    EXERCISE_DESCRIPTIONS,
    EXERCISE_LABELS,
    EXERCISE_SELECTIONS,
    EXERCISE_TYPES,
    LANGUAGES,
    LANGUAGE_CODES,
    LEVEL_LABELS,
    LEVELS,
    STATUS_LABELS,
    STATUS_STYLES,
    VERDICT_LABELS,
    VERDICT_STYLES,
)

logger = logging.getLogger(__name__)

TRANSCRIPT_MAX_CHARS = 8000
HISTORY_MAX_TURNS = 50
HISTORY_MAX_CHARS = 4000
TTS_MAX_CHARS = 4096
EVALUATION_MAX_TURNS = 500


def _error(message, status=400, code="invalid_request"):
    return JsonResponse({"error": code, "message": message}, status=status)


def _parse_json(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return None


def _student_api(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _error("Vous devez être connecté", status=401, code="unauthorized")
        student = get_student(request)
        if student is None or getattr(request, "university", None) is None:
            return _error(
                "Accès réservé aux étudiants", status=403, code="forbidden",
            )
        request.language_student = student
        return view_func(request, *args, **kwargs)

    return wrapper


def _own_session(request, pk, student=None, require_active=False):
    student = student or request.language_student
    queryset = LanguageTestSession.objects.filter(
        pk=pk, university=request.university, student=student,
    )
    if require_active:
        queryset = queryset.filter(status=LanguageTestSession.STATUS_ACTIVE)
    try:
        return queryset.first()
    except (ValidationError, ValueError):
        return None


def _score_average(feedback):
    scores = [
        feedback.fluency_score,
        feedback.vocabulary_score,
        feedback.grammar_score,
        feedback.task_achievement_score,
    ]
    return round(sum(scores) / len(scores), 1)


def _session_row(session):
    feedback = getattr(session, "feedback", None)
    return {
        "session": session,
        "feedback": feedback,
        "exam_name": EXAMS.get(session.exam_type, {}).get("name", session.exam_type),
        "language_label": LANGUAGES.get(session.language, {}).get("label", session.language),
        "level_label": LEVEL_LABELS.get(session.level, session.level),
        "exercise_label": EXERCISE_LABELS.get(
            session.exercise_type, session.exercise_type,
        ),
        "when_label": fr_date_time(session.started_at),
        "status_label": STATUS_LABELS.get(session.status, session.status),
        "status_style": STATUS_STYLES.get(session.status, ""),
        "score_label": fr_decimal(_score_average(feedback), 1) if feedback else "—",
        "has_feedback": feedback is not None,
        "student_id": session.student_id,
        "verdict_label": (
            VERDICT_LABELS.get(feedback.overall_verdict, feedback.overall_verdict)
            if feedback else ""
        ),
        "verdict_style": (
            VERDICT_STYLES.get(
                feedback.overall_verdict, "bg-surface-container text-on-surface-variant",
            )
            if feedback else ""
        ),
        "overall_level": feedback.overall_level if feedback else "",
    }


def _result_context(session, feedback):
    if feedback is None:
        return {"session": session, "feedback": None}
    rows = [
        {
            "key": "fluency",
            "label": "Aisance",
            "score": feedback.fluency_score,
            "notes": feedback.fluency_notes,
        },
        {
            "key": "vocabulary",
            "label": "Vocabulaire",
            "score": feedback.vocabulary_score,
            "notes": feedback.vocabulary_notes,
        },
        {
            "key": "grammar",
            "label": "Grammaire",
            "score": feedback.grammar_score,
            "notes": feedback.grammar_notes,
        },
        {
            "key": "task",
            "label": "Réalisation de la tâche",
            "score": feedback.task_achievement_score,
            "notes": feedback.task_achievement_notes,
        },
    ]
    verdict = feedback.overall_verdict
    return {
        "session": session,
        "feedback": feedback,
        "exam_name": EXAMS.get(session.exam_type, {}).get("name", session.exam_type),
        "language_label": LANGUAGES.get(session.language, {}).get("label", session.language),
        "level_label": LEVEL_LABELS.get(session.level, session.level),
        "exercise_label": EXERCISE_LABELS.get(
            session.exercise_type, session.exercise_type,
        ),
        "started_label": fr_date_time(session.started_at),
        "ended_label": fr_date_time(session.ended_at) if session.ended_at else "—",
        "status_label": STATUS_LABELS.get(session.status, session.status),
        "verdict_label": VERDICT_LABELS.get(verdict, verdict),
        "verdict_style": VERDICT_STYLES.get(verdict, "bg-surface-container text-on-surface-variant"),
        "overall_level": feedback.overall_level,
        "average_label": fr_decimal(_score_average(feedback), 1),
        "scores": rows,
        "pronunciation_flags": feedback.pronunciation_flags or [],
        "recommendations": feedback.recommendations or [],
        "transcript": session.transcript or [],
        "recommendation_count": len(feedback.recommendations or []),
        "created_label": fr_date_time(feedback.created_at),
    }


# ---------------------------------------------------------------------------
# Espace étudiant — pages
# ---------------------------------------------------------------------------


@role_required(Profil.ROLE_ETUDIANT)
def student_language_tests(request):
    student = get_student(request)
    sessions = (
        LanguageTestSession.objects.filter(
            university=request.university, student=student,
        )
        .select_related("feedback")
        .order_by("-started_at")
    )
    rows = [_session_row(session) for session in sessions[:50]]
    completed = [row for row in rows if row["has_feedback"]]
    averages = [_score_average(row["feedback"]) for row in completed]
    average = round(sum(averages) / len(averages), 1) if averages else None
    active = next(
        (row for row in rows if row["session"].status == LanguageTestSession.STATUS_ACTIVE),
        None,
    )
    last = completed[0] if completed else None
    context = {
        "rows": rows,
        "row_count": len(rows),
        "test_count": len(rows),
        "completed_count": len(completed),
        "average_label": fr_decimal(average, 1) if average is not None else "—",
        "last_test_label": fr_day_short(last["session"].started_at) if last else "Aucun test terminé",
        "last_level_label": last["feedback"].overall_level if last else "—",
        "active_row": active,
        "setup_url": reverse("coaching:student_language_test_setup"),
    }
    return render(request, "coaching/language_test_list.html", context)


@role_required(Profil.ROLE_ETUDIANT)
def student_language_test_setup(request):
    language_options = [
        {
            "value": code,
            "label": data["label"],
            "description": data["description"],
        }
        for code, data in LANGUAGES.items()
    ]
    exam_options = [
        {
            "value": key,
            "name": value["name"],
            "description": value["description"],
        }
        for key, value in EXAMS.items()
    ]
    level_options = [{"value": key, "label": LEVEL_LABELS[key]} for key in LEVELS]
    exercise_options = [
        {
            "value": value,
            "label": "Aléatoire" if value == "random" else EXERCISE_LABELS[value],
            "description": EXERCISE_DESCRIPTIONS[value],
        }
        for value in EXERCISE_SELECTIONS
    ]
    config = {
        "startUrl": reverse("coaching:student_language_test_start"),
        "listUrl": reverse("coaching:student_language_tests"),
        "loginUrl": reverse("accounts:login"),
    }
    return render(
        request,
        "coaching/language_test_setup.html",
        {
            "language_options": language_options,
            "exam_options": exam_options,
            "level_options": level_options,
            "exercise_options": exercise_options,
            "config": config,
            "list_url": config["listUrl"],
        },
    )


@role_required(Profil.ROLE_ETUDIANT)
def student_language_test_session(request, pk):
    student = get_student(request)
    session = get_object_or_404(
        LanguageTestSession, pk=pk, university=request.university, student=student,
    )
    if hasattr(session, "feedback"):
        return redirect(
            "coaching:student_language_test_feedback", pk=session.pk,
        )
    if session.status != LanguageTestSession.STATUS_ACTIVE:
        return redirect("coaching:student_language_tests")
    language = LANGUAGES.get(session.language, LANGUAGES["en"])
    config = {
        "sttTokenUrl": reverse(
            "coaching:student_language_test_stt_token", args=[session.pk],
        ),
        "replyUrl": reverse(
            "coaching:student_language_test_reply", args=[session.pk],
        ),
        "ttsUrl": reverse(
            "coaching:student_language_test_tts", args=[session.pk],
        ),
        "evaluateUrl": reverse(
            "coaching:student_language_test_evaluate", args=[session.pk],
        ),
        "listUrl": reverse("coaching:student_language_tests"),
        "loginUrl": reverse("accounts:login"),
    }
    return render(
        request,
        "coaching/language_test_session.html",
        {
            "session": session,
            "exam": EXAMS.get(session.exam_type, {"name": session.exam_type}),
            "language": language,
            "level_label": LEVEL_LABELS.get(session.level, session.level),
            "exercise_label": EXERCISE_LABELS.get(
                session.exercise_type, session.exercise_type,
            ),
            "config": config,
        },
    )


@role_required(Profil.ROLE_ETUDIANT)
def student_language_test_feedback(request, pk):
    student = get_student(request)
    session = get_object_or_404(
        LanguageTestSession, pk=pk, university=request.university, student=student,
    )
    feedback = LanguageTestFeedback.objects.filter(session=session).first()
    if feedback is None:
        if session.status == LanguageTestSession.STATUS_ACTIVE:
            return redirect(
                "coaching:student_language_test_session", pk=session.pk,
            )
        return redirect("coaching:student_language_tests")
    context = _result_context(session, feedback)
    context.update({
        "student_name": display_name(student),
        "list_url": reverse("coaching:student_language_tests"),
        "setup_url": reverse("coaching:student_language_test_setup"),
    })
    return render(request, "coaching/language_test_feedback.html", context)


# ---------------------------------------------------------------------------
# Espace professeur référent
# ---------------------------------------------------------------------------


@role_required(Profil.ROLE_PROF)
def prof_language_tests(request):
    professor = get_professor(request)
    assignments = list(caseload(professor))
    by_student = {item.student_id: item for item in assignments}
    student_ids = list(by_student)

    class_options = []
    seen_classes = set()
    for assignment in assignments:
        if assignment.school_class_id and assignment.school_class_id not in seen_classes:
            seen_classes.add(assignment.school_class_id)
            class_options.append(assignment.school_class)
    class_options.sort(key=lambda item: item.name)

    class_filter = request.GET.get("class") or ""
    if class_filter and class_filter not in {str(item.pk) for item in class_options}:
        class_filter = ""
    student_filter = request.GET.get("student") or ""
    if student_filter and student_filter not in {str(item) for item in student_ids}:
        student_filter = ""

    selected_ids = set(student_ids)
    if class_filter:
        selected_ids = {
            item.student_id for item in assignments
            if item.school_class_id == int(class_filter)
        }
    if student_filter:
        selected_ids &= {int(student_filter)}

    sessions = (
        LanguageTestSession.objects.filter(
            university=request.university,
            student_id__in=selected_ids,
            feedback__isnull=False,
        )
        .select_related("student__membership__user", "feedback")
        .order_by("-started_at")
    )
    rows = []
    for session in sessions:
        assignment = by_student.get(session.student_id)
        row = _session_row(session)
        row["student"] = session.student
        row["student_name"] = display_name(session.student)
        row["initials"] = person_initials(session.student)
        row["class_name"] = (
            assignment.school_class.name
            if assignment and assignment.school_class_id else "—"
        )
        row["feedback_url"] = reverse(
            "coaching:prof_language_test_feedback", args=[session.pk],
        )
        rows.append(row)

    scored = [_score_average(row["feedback"]) for row in rows]
    average = round(sum(scored) / len(scored), 1) if scored else None
    student_options = sorted(
        (
            {
                "id": item.student_id,
                "name": display_name(item.student),
                "class_name": item.school_class.name if item.school_class_id else "",
            }
            for item in assignments
        ),
        key=lambda item: item["name"],
    )
    context = {
        "rows": rows,
        "row_count": len(rows),
        "student_count": len({row["student_id"] for row in rows}),
        "completed_count": len(rows),
        "average_label": fr_decimal(average, 1) if average is not None else "—",
        "last_test_label": fr_day_short(rows[0]["session"].started_at) if rows else "Aucun test",
        "caseload_count": len(assignments),
        "tested_share": percent(len({row["student_id"] for row in rows}), len(assignments)),
        "class_options": class_options,
        "class_filter": class_filter,
        "student_filter": student_filter,
        "student_options": student_options,
        "has_filters": bool(class_filter or student_filter),
    }
    return render(request, "coaching/prof_language_tests.html", context)


@role_required(Profil.ROLE_PROF)
def prof_language_test_feedback(request, pk):
    professor = get_professor(request)
    assignments = list(caseload(professor))
    by_student = {item.student_id: item for item in assignments}
    session = get_object_or_404(
        LanguageTestSession.objects.select_related(
            "student__membership__user", "feedback",
        ),
        pk=pk,
        university=request.university,
        student_id__in=by_student,
        feedback__isnull=False,
    )
    assignment = by_student.get(session.student_id)
    context = _result_context(session, session.feedback)
    context.update({
        "student_name": display_name(session.student),
        "student_number": session.student.student_number or "—",
        "initials": person_initials(session.student),
        "class_name": (
            assignment.school_class.name
            if assignment and assignment.school_class_id else "—"
        ),
        "list_url": reverse("coaching:prof_language_tests"),
    })
    return render(request, "coaching/prof_language_test_feedback.html", context)


# ---------------------------------------------------------------------------
# APIs étudiant
# ---------------------------------------------------------------------------


@require_POST
@_student_api
def student_language_test_start(request):
    payload = _parse_json(request)
    if not isinstance(payload, dict):
        return _error("Corps de requête invalide")

    exam_type = payload.get("examType")
    level = payload.get("level")
    language = payload.get("language")
    exercise_selection = payload.get("exerciseType")

    if exam_type not in EXAMS:
        return _error("Configuration de session invalide")
    if level not in LEVELS:
        return _error("Configuration de session invalide")
    if language not in LANGUAGE_CODES:
        return _error("Configuration de session invalide")
    if exercise_selection not in EXERCISE_SELECTIONS:
        return _error("Configuration de session invalide")

    exercise_type = (
        random.choice(EXERCISE_TYPES)
        if exercise_selection == "random"
        else exercise_selection
    )
    exam = EXAMS[exam_type]
    student = request.language_student

    with transaction.atomic():
        LanguageTestSession.objects.filter(
            university=request.university,
            student=student,
            status=LanguageTestSession.STATUS_ACTIVE,
        ).update(
            status=LanguageTestSession.STATUS_ABANDONED,
            ended_at=timezone.now(),
        )
        session = LanguageTestSession.objects.create(
            university=request.university,
            student=student,
            exam_type=exam_type,
            level=level,
            exercise_type=exercise_type,
            language=language,
            duration_seconds=exam["duration_seconds"],
            status=LanguageTestSession.STATUS_ACTIVE,
        )

    return JsonResponse({
        "data": {
            "sessionId": str(session.pk),
            "sessionUrl": reverse(
                "coaching:student_language_test_session", args=[session.pk],
            ),
            "config": {
                "examType": exam_type,
                "level": level,
                "exerciseType": exercise_type,
                "language": language,
                "durationSeconds": exam["duration_seconds"],
            },
        },
    })


@require_GET
@_student_api
def student_language_test_stt_token(request, pk):
    if _own_session(request, pk, require_active=True) is None:
        return _error("Session introuvable", status=404, code="not_found")
    try:
        token = services.create_realtime_token()
    except services.ProviderError as exc:
        logger.error("STT token error: %s", exc)
        return _error(str(exc), status=502, code="token_failed")
    return JsonResponse({"token": token})


@require_POST
@_student_api
def student_language_test_reply(request, pk):
    payload = _parse_json(request)
    if not isinstance(payload, dict):
        return _error("Corps de requête invalide")

    session = _own_session(request, pk, require_active=True)
    if session is None:
        return _error("Session introuvable", status=404, code="not_found")

    opening = payload.get("opening") is True
    transcript = payload.get("transcript")
    history = payload.get("history", [])

    if not opening:
        if not isinstance(transcript, str) or not transcript.strip():
            return _error("Requête invalide")
        if len(transcript) > TRANSCRIPT_MAX_CHARS:
            return _error("Requête invalide")
    if not isinstance(history, list):
        return _error("Requête invalide")

    cleaned_history = []
    for item in history[:HISTORY_MAX_TURNS]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            cleaned_history.append({"role": role, "content": content[:HISTORY_MAX_CHARS]})

    from .prompts import build_examiner_system_prompt, opening_instruction

    system_prompt = build_examiner_system_prompt(
        session.exam_type,
        session.level,
        session.exercise_type,
        session.pk.int,
        session.language,
    )
    user_content = (
        opening_instruction(session.language) if opening else transcript.strip()
    )

    try:
        stream = services.stream_examiner_reply(
            system_prompt, user_content, cleaned_history,
        )
    except services.ProviderError as exc:
        logger.error("LLM error: %s", exc)
        return _error(str(exc), status=502, code="provider_error")

    response = StreamingHttpResponse(stream, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


@require_POST
@_student_api
def student_language_test_tts(request, pk):
    payload = _parse_json(request)
    if not isinstance(payload, dict):
        return _error("Corps de requête invalide")

    session = _own_session(request, pk, require_active=True)
    if session is None:
        return _error("Session introuvable", status=404, code="not_found")

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return _error("Requête invalide")
    if len(text) > TTS_MAX_CHARS:
        return _error("Requête invalide")

    language = LANGUAGES.get(session.language, LANGUAGES["en"])
    try:
        stream = services.open_tts_stream(
            text.strip(), voice=language["tts_voice"],
        )
    except services.ProviderError as exc:
        logger.error("TTS error: %s", exc)
        return _error(str(exc), status=502, code="provider_error")

    response = StreamingHttpResponse(stream, content_type="audio/mpeg")
    response["Cache-Control"] = "no-store"
    return response


@require_POST
@_student_api
def student_language_test_evaluate(request, pk):
    payload = _parse_json(request)
    if not isinstance(payload, dict):
        return _error("Corps de requête invalide")

    session = _own_session(request, pk)
    if session is None:
        return _error("Session introuvable", status=404, code="not_found")

    existing = LanguageTestFeedback.objects.filter(session=session).first()
    if existing is not None:
        return JsonResponse({
            "data": {
                "feedbackId": str(existing.pk),
                "sessionId": str(session.pk),
                "feedbackUrl": reverse(
                    "coaching:student_language_test_feedback", args=[session.pk],
                ),
            },
        })

    if session.status == LanguageTestSession.STATUS_ABANDONED:
        return _error(
            "Cette session a été abandonnée", status=409, code="session_abandoned",
        )

    transcript = payload.get("transcript")
    if not isinstance(transcript, list):
        return _error("Transcription invalide")

    cleaned_transcript = []
    for entry in transcript[:EVALUATION_MAX_TURNS]:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or entry.get("content")
        if not isinstance(text, str) or not text.strip():
            continue
        cleaned_transcript.append({
            "speaker": str(entry.get("speaker") or entry.get("role") or "user"),
            "text": text.strip()[:4000],
            "timestamp": entry.get("timestamp"),
            "confidence": entry.get("confidence"),
        })

    if not cleaned_transcript:
        return _error("Aucune transcription à évaluer")
    if not any(entry["speaker"] == "user" for entry in cleaned_transcript):
        return _error(
            "Répondez à au moins une question avant de terminer la session.",
        )

    try:
        result = services.evaluate_transcript(session, cleaned_transcript)
    except services.ProviderError as exc:
        logger.error("Evaluation error: %s", exc)
        return _error(str(exc), status=502, code="provider_error")

    with transaction.atomic():
        locked = (
            LanguageTestSession.objects.select_for_update()
            .filter(pk=session.pk)
            .first()
        )
        feedback, _ = LanguageTestFeedback.objects.update_or_create(
            session=locked,
            defaults=result,
        )
        locked.transcript = cleaned_transcript
        locked.status = LanguageTestSession.STATUS_COMPLETED
        locked.ended_at = timezone.now()
        locked.save(update_fields=["transcript", "status", "ended_at"])

    return JsonResponse({
        "data": {
            "feedbackId": str(feedback.pk),
            "sessionId": str(locked.pk),
            "feedbackUrl": reverse(
                "coaching:student_language_test_feedback", args=[locked.pk],
            ),
        },
    })
