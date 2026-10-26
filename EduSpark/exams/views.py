import csv
import random
import re
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib import messages
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import role_required
from accounts.models import Profil, ProfessorProfile, SchoolClass, StudentProfile
from accounts.tenancy import Role
from courses.models import TeachingAssignment

from .forms import (
    ExamSessionForm, ManualQuizForm, OralGradeForm, OralTopicForm,
    ProjectCriterionForm, ProjectGradeForm, ProjectSubmissionForm,
    QuizGenerateForm,
)
from .models import (
    ExamSession, GradeRecord, OralAttempt, OralTopic, ProjectCriterion,
    ProjectSubmission, Quiz, QuizAnswer, QuizAttempt, QuizChoice,
    QuizQuestion, StudentGrade, semester_for,
)
from .pdf import attestation_pdf, transcript_pdf
from .permissions import (
    professor_classes, professor_courses, professor_teaches, student_classes,
)
from .services.ai_insights import generate_quiz_analysis, generate_student_feedback
from .services.ai_project import (
    ProjectEvaluationError, evaluate_project, format_evaluation_feedback,
)
from .services.ai_quiz import (
    QuizGenerationError, ai_quiz_available, generate_quiz_questions,
    save_generated_quiz,
)

EXAM_SEMESTER = "Semestre 1 · 2025-2026"
QUIZ_ABSENT_COMMENT = "Absent — QCM non passé dans le délai."


def _is_absent_grade(grade):
    return bool(grade and (grade.is_absent or (grade.comment or "").strip().startswith("Absent")))


def _tenant_classes(request):
    return SchoolClass.objects.filter(university=request.university).order_by("name")


def _tenant_sessions(request):
    return (
        ExamSession.objects.filter(university=request.university)
        .select_related("school_class", "created_by", "course_subject", "quiz")
        .order_by("opens_at", "school_class__name")
    )


def _tenant_records(request):
    """Relevés de la session courante, un par classe de l'établissement."""
    records = []
    for school_class in _tenant_classes(request):
        record, _created = GradeRecord.objects.get_or_create(
            school_class=school_class,
            semester=semester_for(school_class),
            defaults={"university": request.university},
        )
        records.append(record)
    return records


_SEMESTER_RE = re.compile(r"\b(?:semestre|s)\s*(\d{1,2})\b", re.IGNORECASE)


def _semester_number(label):
    if not label:
        return None
    match = _SEMESTER_RE.search(str(label))
    return int(match.group(1)) if match else None


def _semester_matches(session_semester, record_semester):
    if not session_semester:
        return True
    if session_semester == record_semester:
        return True
    session_number = _semester_number(session_semester)
    record_number = _semester_number(record_semester)
    return (
        session_number is not None
        and record_number is not None
        and session_number == record_number
    )


def _session_in_record(record, session):
    return _semester_matches(session.semester, record.semester)


def _record_sessions(record):
    return [
        session for session in (
            record.school_class.exam_sessions
            .select_related("course_subject", "quiz")
            .order_by("opens_at")
        )
        if _session_in_record(record, session)
    ]


def _session_matrix_label(session):
    if session.course_subject_id:
        return session.course_subject.name
    return session.title or session.code


def _matrix_columns(sessions):
    return [
        {
            "session": session,
            "label": _session_matrix_label(session),
            "code": session.code,
            "coefficient": session.coefficient,
        }
        for session in sessions
    ]


_MATRIX_STATUS_LABELS = {
    StudentGrade.STATUS_PUBLISHED: (
        "published", "Publiée", "bg-primary-fixed text-primary",
    ),
    StudentGrade.STATUS_VALIDATED: (
        "validated", "Validée", "bg-tertiary-fixed text-on-tertiary-fixed",
    ),
    StudentGrade.STATUS_DRAFT: (
        "draft", "Brouillon", "bg-surface-container text-on-surface-variant",
    ),
}


def _matrix_cell(grade):
    if grade is None:
        return {
            "grade": None,
            "status": "missing",
            "badge_label": "Sans note",
            "badge_class": "bg-surface-container text-on-surface-variant",
            "has_score": False,
            "score_label": "—",
            "is_absent": False,
        }
    status, badge_label, badge_class = _MATRIX_STATUS_LABELS.get(
        grade.status,
        ("draft", grade.get_status_display(), "bg-surface-container text-on-surface-variant"),
    )
    is_absent = _is_absent_grade(grade)
    if is_absent:
        badge_label = "Absent"
        badge_class = "bg-error-container text-on-error-container"
    has_score = grade.score is not None
    return {
        "grade": grade,
        "status": status,
        "badge_label": badge_label,
        "badge_class": badge_class,
        "has_score": has_score,
        "score_label": _format_decimal(grade.score) if has_score else "—",
        "is_absent": is_absent,
    }


def _overview_hint(stats):
    if stats["cells"] == 0:
        return "Aucune épreuve notée pour ce semestre."
    if stats["published"] == 0:
        return "Aucune note publiée par les enseignants."
    if stats["incomplete"]:
        details = []
        if stats["pending"]:
            details.append("%s note(s) en attente" % stats["pending"])
        if stats["missing"]:
            details.append("%s case(s) sans note" % stats["missing"])
        return "Vérification incomplète : %s." % " et ".join(details)
    return "Toutes les notes publiées sont vérifiées."


def _overview_pending_label(stats):
    if stats["cells"] == 0:
        return "Aucune épreuve notée"
    if stats["pending"]:
        return "%s en attente" % stats["pending"]
    return "Toutes publiées"


def _matrix_rows(record, students, sessions, grade_map):
    matrix_sessions = [
        session for session in sessions
        if any(grade_map.get((student.pk, session.pk)) for student in students)
    ]
    stats = Counter()
    stats["students"] = len(students)
    stats["sessions"] = len(matrix_sessions)
    stats["cells"] = len(students) * len(matrix_sessions)
    sessions_with_published = set()
    rows = []
    for student in students:
        cells = []
        published_grades = []
        student_published = 0
        for session in matrix_sessions:
            grade = grade_map.get((student.pk, session.pk))
            cell = _matrix_cell(grade)
            cells.append(cell)
            if cell["status"] == "published":
                if cell["has_score"]:
                    stats["published"] += 1
                    student_published += 1
                    published_grades.append(grade)
                    sessions_with_published.add(session.pk)
                else:
                    stats["published_without_score"] += 1
            elif cell["status"] == "validated":
                stats["validated"] += 1
            elif cell["status"] == "draft":
                stats["draft"] += 1
            else:
                stats["missing"] += 1
        if student_published == 0:
            stats["students_without_published"] += 1
        average, validated, graded_total = _weighted_summary(published_grades)
        if average is None:
            decision = "En attente"
        elif average >= 10:
            decision = "Admis"
        else:
            decision = "Ajourné"
        rows.append({
            "student": student,
            "cells": cells,
            "has_grades": any(cell["grade"] is not None for cell in cells),
            "published_count": student_published,
            "average": average,
            "average_label": _format_decimal(average),
            "validated": validated,
            "graded_total": graded_total,
            "decision": decision,
            "is_absent": any(cell["is_absent"] for cell in cells),
        })
    stats["sessions_without_published"] = len(matrix_sessions) - len(sessions_with_published)
    stats["pending"] = (
        stats["validated"] + stats["draft"] + stats["published_without_score"]
    )
    stats["incomplete"] = (
        stats["pending"] + stats["missing"]
        + stats["students_without_published"]
        + stats["sessions_without_published"]
    )
    stats["can_publish"] = bool(
        record.pv_signed
        and not record.transcript_published
        and stats["published"] > 0
    )
    stats["notes_label"] = "%s / %s" % (stats["published"], stats["cells"])
    stats["pending_label"] = _overview_pending_label(stats)
    stats["hint"] = _overview_hint(stats)
    return rows, matrix_sessions, stats


def _records_overview(records):
    records = list(records)
    if not records:
        return {}
    class_ids = list({record.school_class_id for record in records})
    sessions_by_class = defaultdict(list)
    for session in (
        ExamSession.objects.filter(school_class_id__in=class_ids)
        .select_related("course_subject", "quiz")
        .order_by("opens_at")
    ):
        sessions_by_class[session.school_class_id].append(session)

    students_by_class = defaultdict(dict)
    students = (
        StudentProfile.objects.filter(groups__school_class_id__in=class_ids)
        .distinct()
        .select_related("membership__user")
        .prefetch_related("groups")
        .order_by("membership__user__last_name", "membership__user__first_name")
    )
    for student in students:
        for group in student.groups.all():
            if group.school_class_id in class_ids:
                students_by_class[group.school_class_id][student.pk] = student

    session_ids = [
        session.pk for sessions in sessions_by_class.values() for session in sessions
    ]
    student_ids = [
        student_id for class_students in students_by_class.values()
        for student_id in class_students
    ]
    grade_map = {}
    if session_ids and student_ids:
        grades = StudentGrade.objects.filter(
            session_id__in=session_ids, student_id__in=student_ids,
        ).select_related("session")
        grade_map = {(grade.student_id, grade.session_id): grade for grade in grades}

    overviews = {}
    for record in records:
        class_students = list(students_by_class[record.school_class_id].values())
        class_sessions = [
            session for session in sessions_by_class[record.school_class_id]
            if _session_in_record(record, session)
        ]
        _rows, _matrix_sessions, stats = _matrix_rows(
            record, class_students, class_sessions, grade_map,
        )
        overviews[record.pk] = stats
    return overviews


def _refresh_record_stats(record):
    """Recalcule effectif, admis et moyenne depuis les notes publiées."""
    rows, _sessions, _matrix_sessions, _overview = _deliberation_rows(record)
    averages = [row["average"] for row in rows if row["average"] is not None]
    record.students_count = len(rows)
    record.admitted_count = sum(
        1 for row in rows if row["average"] is not None and row["average"] >= 10
    )
    record.average = (
        sum(averages, Decimal("0")) / len(averages) if averages else Decimal("0")
    )
    record.save(update_fields=[
        "students_count", "admitted_count", "average", "updated_at",
    ])
    return record


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="%s"' % filename
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return response


def _next_or(request, fallback):
    target = request.POST.get("next")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)
    return redirect(fallback)


def _notify_planning(session, request):
    """Notifie les enseignants affectés et les étudiants de la classe."""
    sender = request.user.get_full_name() or request.user.email
    common = (
        "Épreuve : %s\n"
        "Type : %s\n"
        "Classe : %s\n"
        "Ouverture : %s\n"
        "Fermeture : %s\n\n"
        % (
            session.title, session.type_label, session.school_class.name,
            timezone.localtime(session.opens_at).strftime("%d/%m/%Y %H:%M"),
            timezone.localtime(session.closes_at).strftime("%d/%m/%Y %H:%M"),
        )
    )
    assignments = TeachingAssignment.objects.filter(
        school_class=session.school_class,
    ).select_related("professor__membership__user")
    if session.course_subject_id:
        assignments = assignments.filter(subject_id=session.course_subject_id)
    for assignment in assignments:
        user = assignment.professor.membership.user
        send_mail(
            "Nouvelle épreuve à préparer — %s" % session.title,
            "Bonjour %s,\n\n"
            "Une épreuve vous a été assignée :\n\n%s"
            "Préparez-la depuis votre portail « Sessions d'examen ».\n\n"
            "Cordialement,\n%s" % (user.get_full_name() or user.email, common, sender),
            None, [user.email], fail_silently=True,
        )
    for student in _session_students(session).select_related("membership__user"):
        user = student.membership.user
        send_mail(
            "Épreuve planifiée — %s" % session.title,
            "Bonjour %s,\n\n"
            "Une épreuve est planifiée pour votre classe :\n\n%s"
            "Retrouvez-la dans votre espace « Mes Examens ».\n\n"
            "Cordialement,\n%s" % (user.get_full_name() or user.email, common, sender),
            None, [user.email], fail_silently=True,
        )


def _sessions_context(request, *, create_form=None, edit_form=None,
                      edit_session=None, open_modal=None):
    sessions = list(_tenant_sessions(request))
    if create_form is None:
        create_form = ExamSessionForm(
            university=request.university, prefix="create", multi=True,
        )
    return {
        "semester": EXAM_SEMESTER,
        "sessions": sessions,
        "session_count": len(sessions),
        "qcm_count": sum(1 for session in sessions if session.is_qcm),
        "project_count": sum(1 for session in sessions if session.is_project),
        "oral_count": sum(1 for session in sessions if session.is_oral),
        "published_quiz_count": sum(
            1 for session in sessions
            if getattr(session, "quiz", None) is not None and session.quiz.is_published
        ),
        "quiz_pending_count": sum(
            1 for session in sessions
            if session.is_qcm and getattr(session, "quiz", None) is None
        ),
        "create_form": create_form,
        "edit_form": edit_form,
        "edit_session": edit_session,
        "open_modal": open_modal,
    }


# ---------------------------------------------------------------------------
# Étudiant
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_ETUDIANT)
def student_exams(request):
    student = _student_profile(request)
    classes = _student_classes(request)
    sessions = list(
        ExamSession.objects.filter(school_class__in=classes)
        .select_related("school_class", "school_class__university", "course_subject", "quiz")
        .order_by("opens_at")
    )

    for session in sessions:
        quiz = getattr(session, "quiz", None)
        if quiz is not None:
            _finalize_quiz_absences(quiz)

    attempts = {
        attempt.quiz.session_id: attempt
        for attempt in QuizAttempt.objects.filter(
            student=student, quiz__session__in=sessions,
        ).select_related("quiz")
    }
    project_submissions = {
        submission.session_id: submission
        for submission in ProjectSubmission.objects.filter(
            student=student, session__in=sessions,
        )
    }
    oral_attempts = {
        attempt.session_id: attempt
        for attempt in OralAttempt.objects.filter(
            student=student, session__in=sessions,
        ).select_related("topic")
    }
    session_rows = []
    for session in sessions:
        quiz = getattr(session, "quiz", None)
        attempt = attempts.get(session.pk)
        project_submission = project_submissions.get(session.pk)
        oral_attempt = oral_attempts.get(session.pk)
        row = {
            "session": session,
            "quiz": quiz,
            "quiz_attempt": attempt,
            "quiz_submitted": bool(attempt and attempt.is_submitted),
            "quiz_absent": bool(attempt and attempt.is_absent),
            "can_start": bool(
                quiz and quiz.is_open and not (attempt and attempt.is_submitted)
                and not (attempt and attempt.is_absent)
            ),
            "question_total": quiz.question_total if quiz else 0,
            "duration_minutes": quiz.duration_minutes if quiz else 0,
            "project_submission": project_submission,
            "project_submitted": bool(project_submission),
            "project_graded": bool(project_submission and project_submission.is_graded),
            "project_can_submit": session.is_open,
            "project_score": (
                project_submission.score_label if project_submission else "-"
            ),
            "oral_attempt": oral_attempt,
            "oral_drawn": bool(oral_attempt),
            "oral_graded": bool(oral_attempt and oral_attempt.is_graded),
            "oral_can_draw": session.is_open and oral_attempt is None,
            "oral_score": oral_attempt.score_label if oral_attempt else "-",
        }
        session_rows.append(row)

    published_grades = (
        StudentGrade.objects.filter(
            student=student, status=StudentGrade.STATUS_PUBLISHED,
        )
        .select_related("session", "session__school_class")
        .order_by("-session__opens_at")
    )

    transcript_available = GradeRecord.objects.filter(
        school_class__in=classes, transcript_published=True,
    ).exists()

    return render(request, "exams/student_exams.html", {
        "semester_label": _current_semester_label(classes),
        "session_rows": session_rows,
        "published_grades": published_grades,
        "transcript_available": transcript_available,
        "has_sessions": bool(session_rows),
        "quiz_submitted_count": sum(
            1 for row in session_rows if row["quiz_submitted"]
        ),
        "quiz_absent_count": sum(
            1 for row in session_rows if row["quiz_absent"]
        ),
        "project_submitted_count": sum(
            1 for row in session_rows if row["project_submitted"]
        ),
        "project_graded_count": sum(
            1 for row in session_rows if row["project_graded"]
        ),
        "oral_drawn_count": sum(
            1 for row in session_rows if row["oral_drawn"]
        ),
        "oral_graded_count": sum(
            1 for row in session_rows if row["oral_graded"]
        ),
    })


@role_required(Profil.ROLE_ETUDIANT)
def student_transcript(request):
    student = _student_profile(request)
    classes = _student_classes(request)
    grades, record_index = _student_transcript_grades(student, classes)
    published_records = _published_records(classes)
    transcript_available = bool(record_index)
    pending_classes = [
        school_class for school_class in classes
        if school_class.pk not in record_index
    ]

    semester_rows = []
    for semester, rows in _group_grades_by_semester(grades).items():
        coefficient_total = sum(g.session.coefficient for g in rows)
        average = (
            sum((g.score * g.session.coefficient for g in rows), Decimal("0"))
            / coefficient_total if coefficient_total else None
        )
        semester_rows.append({
            "label": semester,
            "rows": rows,
            "validated": sum(1 for g in rows if g.score >= 10),
            "average": average,
            "average_label": _format_decimal(average),
        })

    average, validated, graded_total = _weighted_summary(grades)
    rank = (
        _compute_rank(student, average, record_index)
        if average is not None and transcript_available else None
    )
    mention = _mention_for(average) if average is not None else None
    promotion_size = _promotion_size(record_index)

    if not transcript_available:
        mention_hint = "Relevé en attente de publication"
    elif average is None:
        mention_hint = "Aucune note publiée pour le moment"
    elif average >= 10:
        mention_hint = "Semestre validé"
    else:
        mention_hint = "En attente de validation"

    return render(request, "exams/student_transcript.html", {
        "semester_rows": semester_rows,
        "transcript_available": transcript_available,
        "pending_classes": pending_classes,
        "published_records": published_records,
        "grade_count": graded_total,
        "average": average,
        "average_label": _format_decimal(average),
        "validated": validated,
        "rank": rank,
        "promotion_size": promotion_size,
        "mention": mention,
        "mention_label": mention or "—",
        "mention_hint": mention_hint,
        "suffix_validated": "/%s" % graded_total,
        "rank_label": rank or "—",
        "rank_suffix": ("e / %s" % promotion_size) if rank else "",
    })


@role_required(Profil.ROLE_ETUDIANT)
def student_transcript_pdf(request):
    student = _student_profile(request)
    grades, record_index = _student_transcript_grades(
        student, _student_classes(request),
    )
    if not record_index:
        messages.error(
            request,
            "Le relevé de votre classe n'est pas encore publié par l'administration.",
        )
        return redirect("exams:student_transcript")
    average, _validated, _total = _weighted_summary(grades)
    semester_rows = [
        {"label": semester, "rows": rows}
        for semester, rows in _group_grades_by_semester(grades).items()
    ]
    return _pdf_response(
        transcript_pdf(
            request.university, student, semester_rows, average,
            _mention_for(average) if average is not None else None,
        ),
        "releve-notes.pdf",
    )


@role_required(Profil.ROLE_ETUDIANT)
def student_attestation_pdf(request):
    student = _student_profile(request)
    grades, record_index = _student_transcript_grades(
        student, _student_classes(request),
    )
    if not record_index:
        messages.error(
            request,
            "Le relevé de votre classe n'est pas encore publié par l'administration.",
        )
        return redirect("exams:student_transcript")
    average, _validated, _total = _weighted_summary(grades)
    if average is None or average < 10:
        messages.error(
            request,
            "L'attestation de réussite est disponible uniquement lorsque la "
            "moyenne générale atteint 10/20.",
        )
        return redirect("exams:student_transcript")
    return _pdf_response(
        attestation_pdf(request.university, student, average, _mention_for(average)),
        "attestation-reussite.pdf",
    )


# ---------------------------------------------------------------------------
# Projet / Oral : parcours étudiant
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_ETUDIANT)
def student_project_exam(request, pk):
    session = _student_session(request, pk)
    if not session.is_project:
        messages.error(request, "Cette session n'est pas une épreuve de projet.")
        return redirect("exams:student_exams")

    student = _student_profile(request)
    submission = ProjectSubmission.objects.filter(
        session=session, student=student,
    ).first()
    ai_result = (
        submission.ai_result
        if submission and isinstance(submission.ai_result, dict)
        else {}
    )
    ai_feedback = (
        ai_result.get("feedback")
        or format_evaluation_feedback(ai_result)
    )
    form = ProjectSubmissionForm(
        request.POST or None, request.FILES or None, instance=submission,
    )

    if request.method == "POST":
        if not session.is_open:
            messages.error(
                request,
                "La fenêtre de dépôt est fermée : le projet ne peut plus être envoyé.",
            )
            return redirect("exams:student_project_exam", pk=session.pk)
        if form.is_valid():
            upload = form.cleaned_data["file"]
            old_name = submission.file.name if submission and submission.file else ""
            project = form.save(commit=False)
            project.session = session
            project.student = student
            project.university = request.university
            project.original_name = Path(upload.name).name
            project.size = upload.size
            project.submitted_at = timezone.now()
            project.status = ProjectSubmission.STATUS_SUBMITTED
            project.ai_result = {}
            project.ai_score = None
            project.ai_model = ""
            project.ai_evaluated_at = None
            project.final_score = None
            project.feedback = ""
            project.graded_by = None
            project.graded_at = None
            project.save()
            if old_name and old_name != project.file.name:
                project.file.storage.delete(old_name)
            messages.success(
                request,
                "Projet déposé. Votre enseignant pourra le consulter et le noter.",
            )
            return redirect("exams:student_project_exam", pk=session.pk)

    return render(request, "exams/student_project_exam.html", {
        "session": session,
        "submission": submission,
        "form": form,
        "ai_feedback": ai_feedback,
        "criteria": session.project_criteria.all(),
        "grade": StudentGrade.objects.filter(
            session=session, student=student,
        ).first(),
        "can_submit": session.is_open,
        "is_late": session.access_status == "after",
    })


@role_required(Profil.ROLE_ETUDIANT)
def student_oral_exam(request, pk):
    session = _student_session(request, pk)
    if not session.is_oral:
        messages.error(request, "Cette session n'est pas une épreuve orale.")
        return redirect("exams:student_exams")

    student = _student_profile(request)
    attempt = (
        OralAttempt.objects.filter(session=session, student=student)
        .select_related("topic")
        .first()
    )

    if request.method == "POST" and request.POST.get("action") == "draw":
        if not session.is_open:
            messages.error(request, "La fenêtre de tirage est fermée.")
            return redirect("exams:student_oral_exam", pk=session.pk)
        if attempt is not None:
            messages.info(request, "Vous avez déjà tiré votre sujet.")
            return redirect("exams:student_oral_exam", pk=session.pk)
        topics = list(session.oral_topics.filter(is_active=True))
        if not topics:
            messages.error(
                request,
                "Aucun sujet n'est disponible pour le moment. Contactez votre enseignant.",
            )
            return redirect("exams:student_oral_exam", pk=session.pk)
        topic = random.choice(topics)
        deadline = timezone.now() + timedelta(minutes=topic.duration_minutes)
        if deadline > session.closes_at:
            deadline = session.closes_at
        attempt, created = OralAttempt.objects.get_or_create(
            session=session, student=student,
            defaults={
                "university": request.university,
                "topic": topic,
                "drawn_at": timezone.now(),
                "preparation_deadline": deadline,
                "status": OralAttempt.STATUS_DRAWN,
            },
        )
        if created:
            messages.success(
                request,
                "Sujet tiré : « %s ». Temps de préparation : %s minutes."
                % (topic.title, topic.duration_minutes),
            )
        else:
            messages.info(request, "Vous avez déjà tiré votre sujet.")
        return redirect("exams:student_oral_exam", pk=session.pk)

    topics = session.oral_topics.filter(is_active=True)
    return render(request, "exams/student_oral_exam.html", {
        "session": session,
        "attempt": attempt,
        "topics_count": topics.count(),
        "can_draw": session.is_open and attempt is None and topics.exists(),
        "grade": StudentGrade.objects.filter(
            session=session, student=student,
        ).first(),
    })


# ---------------------------------------------------------------------------
# QCM : parcours étudiant
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_ETUDIANT)
def student_quiz_start(request, pk):
    session = _student_session(request, pk)
    quiz = getattr(session, "quiz", None)
    if quiz is None or not quiz.is_published:
        messages.error(request, "Le QCM de cette session n'est pas encore publié.")
        return redirect("exams:student_exams")

    student = _student_profile(request)
    attempt = QuizAttempt.objects.filter(quiz=quiz, student=student).first()
    if attempt is not None and attempt.is_submitted:
        return redirect("exams:student_quiz_result", pk=attempt.pk)
    if not quiz.is_open:
        messages.error(request, _quiz_unavailable_message(quiz))
        return redirect("exams:student_exams")
    if attempt is not None:
        return redirect("exams:student_quiz_take", pk=attempt.pk)

    if request.method == "POST":
        attempt = _start_quiz_attempt(quiz, student)
        messages.success(
            request,
            "QCM démarré : vous avez %s minutes pour répondre." % quiz.duration_minutes,
        )
        return redirect("exams:student_quiz_take", pk=attempt.pk)

    return render(request, "exams/student_quiz_start.html", {
        "session": session,
        "quiz": quiz,
        "question_total": quiz.questions.count(),
        "total_points": quiz.total_points,
    })


@role_required(Profil.ROLE_ETUDIANT)
@require_GET
def student_quiz_take(request, pk):
    attempt = _student_quiz_attempt(request, pk)
    if attempt.is_submitted:
        return redirect("exams:student_quiz_result", pk=attempt.pk)
    if attempt.is_expired:
        _grade_quiz_attempt(attempt)
        messages.info(
            request,
            "Le temps imparti est écoulé : votre QCM a été soumis automatiquement.",
        )
        return redirect("exams:student_quiz_result", pk=attempt.pk)

    questions = _attempt_questions(attempt)
    answers = {
        answer.question_id: answer.selected_choice_id
        for answer in attempt.answers.all()
    }
    question_rows = [
        {"question": question, "selected": answers.get(question.pk)}
        for question in questions
    ]
    return render(request, "exams/student_quiz_take.html", {
        "attempt": attempt,
        "quiz": attempt.quiz,
        "question_rows": question_rows,
        "remaining_seconds": attempt.remaining_seconds(),
        "deadline_iso": attempt.deadline_at.isoformat(),
    })


@role_required(Profil.ROLE_ETUDIANT)
@require_POST
def student_quiz_save(request, pk):
    attempt = _student_quiz_attempt(request, pk)
    if attempt.is_submitted:
        return JsonResponse({"submitted": True, "remaining_seconds": 0})
    if attempt.is_expired:
        _grade_quiz_attempt(attempt)
        return JsonResponse({"submitted": True, "remaining_seconds": 0})

    saved = _store_answers(attempt, request.POST)
    return JsonResponse({
        "saved": saved,
        "submitted": False,
        "remaining_seconds": attempt.remaining_seconds(),
    })


@role_required(Profil.ROLE_ETUDIANT)
@require_POST
def student_quiz_submit(request, pk):
    attempt = _student_quiz_attempt(request, pk)
    if attempt.is_submitted:
        messages.info(request, "Votre QCM a déjà été soumis.")
    else:
        expired = attempt.is_expired
        if not expired:
            _collect_attempt_answers(attempt, request.POST)
        _grade_quiz_attempt(attempt)
        if expired:
            messages.info(
                request,
                "Le temps imparti est écoulé : seules les réponses sauvegardées "
                "ont été prises en compte.",
            )
        else:
            messages.success(
                request,
                "QCM soumis : votre note est enregistrée.",
            )
    return redirect("exams:student_quiz_result", pk=attempt.pk)


@role_required(Profil.ROLE_ETUDIANT)
def student_quiz_result(request, pk):
    attempt = _student_quiz_attempt(request, pk)
    if not attempt.is_submitted:
        if attempt.is_expired:
            _grade_quiz_attempt(attempt)
        else:
            return redirect("exams:student_quiz_take", pk=attempt.pk)

    answers = {
        answer.question_id: answer
        for answer in attempt.answers.select_related("selected_choice")
    }
    rows = []
    for question in _attempt_questions(attempt):
        answer = answers.get(question.pk)
        selected = answer.selected_choice if answer else None
        correct = question.correct_choices.first()
        rows.append({
            "question": question,
            "selected": selected,
            "correct": correct,
            "is_correct": bool(selected and selected.is_correct),
        })

    feedback = attempt.ai_feedback or generate_student_feedback(attempt)
    return render(request, "exams/student_quiz_result.html", {
        "attempt": attempt,
        "quiz": attempt.quiz,
        "session": attempt.quiz.session,
        "rows": rows,
        "score_20": attempt.score_20,
        "score_label": _format_decimal(attempt.score_20),
        "passed": attempt.passed,
        "is_absent": attempt.is_absent,
        "feedback": feedback,
    })


@role_required(Profil.ROLE_ETUDIANT)
@require_POST
def student_quiz_feedback(request, pk):
    attempt = _student_quiz_attempt(request, pk)
    if not attempt.is_submitted:
        messages.info(request, "Soumettez d'abord votre QCM.")
    else:
        generate_student_feedback(attempt, force=True)
        messages.success(request, "Feedback personnalisé actualisé.")
    return redirect("exams:student_quiz_result", pk=attempt.pk)


# ---------------------------------------------------------------------------
# QCM : parcours professeur
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_PROF)
def prof_exam_sessions(request):
    classes = _prof_classes(request)
    sessions = list(
        ExamSession.objects.filter(school_class__in=classes)
        .select_related("school_class", "course_subject", "quiz")
        .annotate(
            project_submission_count=Count(
                "project_submissions", distinct=True,
            ),
            project_graded_count=Count(
                "project_submissions",
                filter=Q(project_submissions__final_score__isnull=False),
                distinct=True,
            ),
            oral_attempt_count=Count("oral_attempts", distinct=True),
            oral_graded_count=Count(
                "oral_attempts",
                filter=Q(oral_attempts__score__isnull=False),
                distinct=True,
            ),
        )
        .order_by("opens_at")
    )
    professor = _prof_profile(request)
    for session in sessions:
        session.teaching_ok = professor_teaches(professor, session)
        session.has_course = bool(
            session.teaching_ok and professor_courses(professor, session).exists()
        )
        session.can_create_quiz = (
            session.is_qcm and session.teaching_ok and session.has_course
        )
        session.project_pending_count = max(
            0, session.project_submission_count - session.project_graded_count,
        )
        session.oral_pending_count = max(
            0, session.oral_attempt_count - session.oral_graded_count,
        )

    return render(request, "exams/prof_exam_sessions.html", {
        "semester": _current_semester_label(classes),
        "sessions": sessions,
        "session_count": len(sessions),
        "qcm_count": sum(1 for session in sessions if session.is_qcm),
        "project_count": sum(1 for session in sessions if session.is_project),
        "oral_count": sum(1 for session in sessions if session.is_oral),
        "published_quiz_count": sum(
            1 for session in sessions
            if getattr(session, "quiz", None) is not None and session.quiz.is_published
        ),
        "quiz_pending_count": sum(
            1 for session in sessions
            if session.is_qcm and getattr(session, "quiz", None) is None
            and session.can_create_quiz
        ),
        "project_pending_count": sum(
            session.project_pending_count for session in sessions
            if session.is_project
        ),
        "oral_pending_count": sum(
            session.oral_pending_count for session in sessions
            if session.is_oral
        ),
    })


# ---------------------------------------------------------------------------
# Projet / Oral : parcours professeur
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_PROF)
def prof_project_exam(request, pk):
    session = _prof_session(request, pk)
    if session is None:
        return redirect("exams:prof_exam_sessions")
    if not session.is_project:
        messages.error(request, "Cette session n'est pas une épreuve de projet.")
        return redirect("exams:prof_exam_sessions")

    criterion_form = ProjectCriterionForm()
    edit_criterion = None
    edit_criterion_form = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "seed_criteria":
            ProjectCriterion.ensure_defaults(session)
            messages.success(request, "Grille d'évaluation par défaut créée.")
            return redirect("exams:prof_project_exam", pk=session.pk)
        if action == "add_criterion":
            criterion_form = ProjectCriterionForm(request.POST)
            if criterion_form.is_valid():
                criterion = criterion_form.save(commit=False)
                criterion.session = session
                criterion.save()
                messages.success(request, "Critère ajouté à la grille.")
                return redirect("exams:prof_project_exam", pk=session.pk)
        elif action == "edit_criterion":
            edit_criterion = get_object_or_404(
                ProjectCriterion, pk=request.POST.get("criterion_id"),
                session=session,
            )
            edit_criterion_form = ProjectCriterionForm(
                request.POST, instance=edit_criterion,
            )
            if edit_criterion_form.is_valid():
                edit_criterion_form.save()
                messages.success(request, "Critère modifié.")
                return redirect("exams:prof_project_exam", pk=session.pk)
            messages.error(request, "La grille contient des erreurs à corriger.")
        elif action == "delete_criterion":
            criterion = get_object_or_404(
                ProjectCriterion, pk=request.POST.get("criterion_id"),
                session=session,
            )
            criterion.delete()
            messages.success(request, "Critère supprimé.")
            return redirect("exams:prof_project_exam", pk=session.pk)

    criteria = list(session.project_criteria.all())
    submissions = list(
        session.project_submissions.select_related(
            "student__membership__user",
        )
    )
    graded_count = sum(1 for submission in submissions if submission.is_graded)
    students_count = _session_students(session).count()
    return render(request, "exams/prof_project_exam.html", {
        "session": session,
        "criteria": criteria,
        "criterion_form": criterion_form,
        "edit_criterion": edit_criterion,
        "edit_criterion_form": edit_criterion_form,
        "submissions": submissions,
        "students_count": students_count,
        "submission_count": len(submissions),
        "graded_count": graded_count,
        "pending_count": max(0, len(submissions) - graded_count),
        "submission_rate": (
            round(len(submissions) * 100 / students_count) if students_count else 0
        ),
        "criteria_weight": sum(criterion.weight for criterion in criteria),
        "can_ai": ai_quiz_available(),
    })


@role_required(Profil.ROLE_PROF)
def prof_project_submission(request, pk):
    submission = get_object_or_404(
        ProjectSubmission.objects.select_related(
            "session", "session__school_class", "session__course_subject",
            "student__membership__user",
        ),
        pk=pk, session__school_class__in=_prof_classes(request),
    )
    session = submission.session
    if not session.is_project or not professor_teaches(
        _prof_profile(request), session,
    ):
        messages.error(request, "Ce dépôt ne relève pas de vos enseignements.")
        return redirect("exams:prof_exam_sessions")

    ai_result = submission.ai_result if isinstance(submission.ai_result, dict) else {}
    ai_feedback = (
        ai_result.get("feedback")
        or format_evaluation_feedback(ai_result)
    )
    initial_score = (
        submission.final_score
        if submission.final_score is not None
        else submission.ai_score
    )
    grade_form = ProjectGradeForm(initial={
        "score": initial_score,
        "feedback": submission.feedback or ai_feedback,
    })
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "evaluate_ai":
            try:
                result = evaluate_project(submission)
            except ProjectEvaluationError as exc:
                submission.status = ProjectSubmission.STATUS_MANUAL_REQUIRED
                submission.save(update_fields=["status", "updated_at"])
                messages.error(request, str(exc))
            else:
                submission.ai_result = result
                submission.ai_score = Decimal(str(result.get("score_20", 0)))
                submission.ai_model = result.get("model", "")
                submission.ai_evaluated_at = timezone.now()
                submission.status = ProjectSubmission.STATUS_AI_EVALUATED
                submission.save(update_fields=[
                    "ai_result", "ai_score", "ai_model", "ai_evaluated_at",
                    "status", "updated_at",
                ])
                messages.success(
                    request,
                    "Évaluation IA terminée : note proposée %s/20. "
                    "L'explication selon la grille est préremplie ci-dessous."
                    % _format_decimal(submission.ai_score),
                )
            return redirect("exams:prof_project_submission", pk=submission.pk)
        if action == "apply_ai":
            if submission.ai_score is None:
                messages.error(request, "Lancez d'abord l'évaluation IA.")
            else:
                feedback = (
                    (submission.ai_result or {}).get("feedback")
                    or format_evaluation_feedback(submission.ai_result or {})
                    or "Note proposée par l'évaluation IA selon la grille."
                )
                with transaction.atomic():
                    submission.final_score = submission.ai_score
                    submission.feedback = feedback
                    submission.status = ProjectSubmission.STATUS_GRADED
                    submission.graded_by = request.user
                    submission.graded_at = timezone.now()
                    submission.save(update_fields=[
                        "final_score", "feedback", "status", "graded_by",
                        "graded_at", "updated_at",
                    ])
                    _sync_exam_grade(
                        session, submission.student, submission.ai_score,
                        comment=feedback, graded_by=request.user,
                    )
                messages.success(
                    request,
                    "Note IA appliquée et publiée pour l'étudiant.",
                )
            return redirect("exams:prof_project_submission", pk=submission.pk)
        if action == "grade":
            grade_form = ProjectGradeForm(request.POST)
            if grade_form.is_valid():
                score = grade_form.cleaned_data["score"]
                feedback = grade_form.cleaned_data["feedback"].strip()
                submission.final_score = score
                submission.feedback = feedback
                submission.status = ProjectSubmission.STATUS_GRADED
                submission.graded_by = request.user
                submission.graded_at = timezone.now()
                submission.save(update_fields=[
                    "final_score", "feedback", "status", "graded_by",
                    "graded_at", "updated_at",
                ])
                _sync_exam_grade(
                    session, submission.student, score,
                    comment=feedback or "Projet noté par le professeur.",
                    graded_by=request.user,
                )
                messages.success(request, "Note du projet enregistrée.")
                return redirect("exams:prof_project_submission", pk=submission.pk)
        elif action == "absent":
            submission.final_score = Decimal("0")
            submission.feedback = "Absent : aucun projet exploitable déposé."
            submission.status = ProjectSubmission.STATUS_GRADED
            submission.graded_by = request.user
            submission.graded_at = timezone.now()
            submission.save()
            _sync_exam_grade(
                session, submission.student, Decimal("0"),
                comment=submission.feedback, graded_by=request.user,
                absent=True,
            )
            messages.success(request, "Absence enregistrée pour ce projet.")
            return redirect("exams:prof_project_submission", pk=submission.pk)

    criteria = list(session.project_criteria.all())
    return render(request, "exams/prof_project_submission.html", {
        "submission": submission,
        "session": session,
        "criteria": criteria,
        "grade_form": grade_form,
        "ai_result": ai_result,
        "ai_rows": ai_result.get("criteria", []),
        "ai_feedback": ai_feedback,
        "can_evaluate": ai_quiz_available(),
        "is_graded": submission.is_graded,
    })


@role_required(Profil.ROLE_PROF)
def prof_project_download(request, pk):
    submission = get_object_or_404(
        ProjectSubmission.objects.select_related("session", "session__school_class"),
        pk=pk, session__school_class__in=_prof_classes(request),
    )
    if not professor_teaches(_prof_profile(request), submission.session):
        messages.error(request, "Ce dépôt ne relève pas de vos enseignements.")
        return redirect("exams:prof_exam_sessions")
    try:
        handle = submission.file.open("rb")
    except (OSError, ValueError):
        messages.error(request, "Le fichier du projet est introuvable sur le serveur.")
        return redirect("exams:prof_project_submission", pk=submission.pk)
    filename = (
        submission.original_name
        or Path(submission.file.name).name
        or "projet.zip"
    )
    return FileResponse(handle, as_attachment=True, filename=filename)


@role_required(Profil.ROLE_PROF)
def prof_oral_exam(request, pk):
    session = _prof_session(request, pk)
    if session is None:
        return redirect("exams:prof_exam_sessions")
    if not session.is_oral:
        messages.error(request, "Cette session n'est pas une épreuve orale.")
        return redirect("exams:prof_exam_sessions")

    topic_form = OralTopicForm()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "seed_topics":
            OralTopic.ensure_defaults(session)
            messages.success(request, "Sujets d'oral par défaut créés.")
            return redirect("exams:prof_oral_exam", pk=session.pk)
        if action == "add_topic":
            topic_form = OralTopicForm(request.POST)
            if topic_form.is_valid():
                topic = topic_form.save(commit=False)
                topic.session = session
                topic.save()
                messages.success(request, "Sujet d'oral ajouté.")
                return redirect("exams:prof_oral_exam", pk=session.pk)
        elif action == "delete_topic":
            topic = get_object_or_404(
                OralTopic, pk=request.POST.get("topic_id"), session=session,
            )
            if topic.attempts.exists():
                topic.is_active = False
                topic.save(update_fields=["is_active"])
                messages.success(
                    request,
                    "Ce sujet a déjà été tiré : il est désactivé au lieu d'être supprimé.",
                )
            else:
                topic.delete()
                messages.success(request, "Sujet supprimé.")
            return redirect("exams:prof_oral_exam", pk=session.pk)
        elif action == "grade":
            attempt = get_object_or_404(
                OralAttempt, pk=request.POST.get("attempt_id"), session=session,
            )
            grade_form = OralGradeForm(request.POST)
            if grade_form.is_valid():
                score = grade_form.cleaned_data["score"]
                feedback = grade_form.cleaned_data["feedback"].strip()
                attempt.score = score
                attempt.feedback = feedback
                attempt.status = OralAttempt.STATUS_GRADED
                attempt.graded_by = request.user
                attempt.graded_at = timezone.now()
                attempt.save()
                _sync_exam_grade(
                    session, attempt.student, score,
                    comment=feedback or "Oral noté par le professeur.",
                    graded_by=request.user,
                )
                messages.success(
                    request,
                    "Note d'oral enregistrée pour %s."
                    % (attempt.student.membership.user.get_full_name()
                       or attempt.student.membership.user.email),
                )
            else:
                messages.error(
                    request,
                    "La note d'oral doit être comprise entre 0 et 20.",
                )
            return redirect("exams:prof_oral_exam", pk=session.pk)
        elif action == "mark_absent":
            attempt = get_object_or_404(
                OralAttempt, pk=request.POST.get("attempt_id"), session=session,
            )
            attempt.score = Decimal("0")
            attempt.feedback = "Absent à l'épreuve orale."
            attempt.status = OralAttempt.STATUS_ABSENT
            attempt.graded_by = request.user
            attempt.graded_at = timezone.now()
            attempt.save()
            _sync_exam_grade(
                session, attempt.student, Decimal("0"),
                comment=attempt.feedback, graded_by=request.user, absent=True,
            )
            messages.success(request, "Absence enregistrée pour cet oral.")
            return redirect("exams:prof_oral_exam", pk=session.pk)

    topics = list(session.oral_topics.all())
    attempts = list(
        session.oral_attempts.select_related(
            "student__membership__user", "topic",
        )
    )
    graded_count = sum(1 for attempt in attempts if attempt.is_graded)
    return render(request, "exams/prof_oral_exam.html", {
        "session": session,
        "topics": topics,
        "topic_form": topic_form,
        "attempts": attempts,
        "topics_count": len(topics),
        "active_topics_count": sum(1 for topic in topics if topic.is_active),
        "attempt_count": len(attempts),
        "graded_count": graded_count,
        "pending_count": max(0, len(attempts) - graded_count),
        "students_count": _session_students(session).count(),
    })


@role_required(Profil.ROLE_PROF)
def prof_quiz_create(request, pk):
    session = _prof_session(request, pk)
    if session is None:
        return redirect("exams:prof_exam_sessions")
    quiz = getattr(session, "quiz", None)
    if quiz is not None:
        messages.info(request, "Un QCM existe déjà pour cette session.")
        return redirect("exams:prof_quiz_edit", pk=quiz.pk)
    if not session.course_subject_id:
        messages.error(
            request,
            "Cette session n'est pas rattachée à une matière : impossible de créer un QCM.",
        )
        return redirect("exams:prof_exam_sessions")

    professor = _prof_profile(request)
    if not professor_teaches(professor, session):
        messages.error(
            request,
            "Vous n'enseignez pas « %s » dans la classe « %s »."
            % (session.course_subject, session.school_class.name),
        )
        return redirect("exams:prof_exam_sessions")

    courses = professor_courses(professor, session)
    duration = int((session.closes_at - session.opens_at).total_seconds() // 60)
    form = ManualQuizForm(
        request.POST or None,
        course_queryset=courses,
        initial={"duration_minutes": max(5, min(480, duration or 60)), "pass_score": 10},
    )
    if request.method == "POST" and form.is_valid():
        quiz = form.save(commit=False)
        quiz.session = session
        quiz.university = request.university
        quiz.created_by = request.user
        quiz.question_count = 0
        quiz.status = Quiz.STATUS_DRAFT
        quiz.save()
        messages.success(
            request,
            "QCM créé pour « %s ». Ajoutez vos questions puis publiez-le." % session.title,
        )
        return redirect("exams:prof_quiz_edit", pk=quiz.pk)

    return render(request, "exams/prof_quiz_manual.html", {
        "session": session,
        "form": form,
        "course_count": courses.count(),
    })


@role_required(Profil.ROLE_PROF)
def prof_quiz_generate(request, pk):
    session = _prof_session(request, pk)
    if session is None:
        return redirect("exams:prof_exam_sessions")
    quiz = getattr(session, "quiz", None)
    if quiz is not None and quiz.attempts.exists():
        messages.error(
            request,
            "Des étudiants ont déjà passé ce QCM : il ne peut plus être régénéré.",
        )
        return redirect("exams:prof_quiz_edit", pk=quiz.pk)
    if not session.course_subject_id:
        messages.error(
            request,
            "Cette session n'est pas rattachée à une matière : impossible de générer un QCM.",
        )
        return redirect("exams:prof_exam_sessions")

    professor = _prof_profile(request)
    if not professor_teaches(professor, session):
        messages.error(
            request,
            "Vous n'enseignez pas « %s » dans la classe « %s »."
            % (session.course_subject, session.school_class.name),
        )
        return redirect("exams:prof_exam_sessions")

    courses = professor_courses(professor, session)
    if request.method == "POST":
        form = QuizGenerateForm(request.POST, course_queryset=courses, instance=quiz)
        if form.is_valid():
            course = form.cleaned_data["course"]
            try:
                questions, metadata = generate_quiz_questions(
                    course,
                    count=form.cleaned_data["question_count"],
                    difficulty=form.cleaned_data["difficulty"],
                )
            except QuizGenerationError as exc:
                form.add_error(None, str(exc))
            else:
                with transaction.atomic():
                    if quiz is None:
                        quiz = Quiz(
                            session=session, university=request.university,
                            created_by=request.user,
                        )
                    for field in (
                        "course", "question_count", "duration_minutes", "pass_score",
                        "shuffle_questions", "instructions",
                    ):
                        setattr(quiz, field, form.cleaned_data[field])
                    quiz.save()
                    save_generated_quiz(quiz, questions, metadata)
                messages.success(
                    request,
                    "QCM généré : %s question(s) sur %s demandée(s). Relisez-le "
                    "puis publiez-le." % (metadata["generated"], metadata["requested"]),
                )
                return redirect("exams:prof_quiz_edit", pk=quiz.pk)
    else:
        form = QuizGenerateForm(course_queryset=courses, instance=quiz)

    return render(request, "exams/prof_quiz_generate.html", {
        "session": session,
        "quiz": quiz,
        "form": form,
        "ai_available": ai_quiz_available(),
        "course_count": courses.count(),
    })


@role_required(Profil.ROLE_PROF)
def prof_quiz_edit(request, pk):
    quiz = _prof_quiz(request, pk)
    if quiz is None:
        return redirect("exams:prof_exam_sessions")
    action = request.POST.get("action") if request.method == "POST" else None
    has_attempts = quiz.attempts.exists()
    if has_attempts and action and action != "close":
        messages.error(
            request,
            "Des étudiants ont déjà passé ce QCM : les questions et le barème "
            "sont verrouillés. Vous pouvez seulement le fermer.",
        )
        return redirect("exams:prof_quiz_edit", pk=quiz.pk)

    if action in ("save", "add", "publish"):
        saved, save_errors = _update_quiz_questions(quiz, request.POST)
        if saved:
            messages.success(request, "%s question(s) enregistrée(s)." % saved)
        for error in save_errors:
            messages.error(request, error)
        if action == "save" or save_errors:
            return redirect("exams:prof_quiz_edit", pk=quiz.pk)

    if action == "add":
        last = quiz.questions.order_by("-order").first()
        order = (last.order if last else 0) + 1
        question = QuizQuestion.objects.create(
            quiz=quiz, order=order, prompt="Nouvelle question", points=1,
        )
        for index in range(4):
            QuizChoice.objects.create(
                question=question, order=index + 1,
                label="Proposition %s" % "ABCD"[index],
                is_correct=index == 0,
            )
        messages.info(request, "Question ajoutée : complétez son énoncé et ses choix.")
        return redirect("exams:prof_quiz_edit", pk=quiz.pk)

    if action == "delete":
        question = quiz.questions.filter(pk=request.POST.get("question")).first()
        if question is not None:
            question.delete()
            messages.success(request, "Question supprimée.")
        return redirect("exams:prof_quiz_edit", pk=quiz.pk)

    if action == "publish":
        errors = _publish_quiz(quiz)
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            messages.success(
                request,
                "QCM « %s » publié : les étudiants peuvent y accéder pendant "
                "la fenêtre d'ouverture." % quiz.session.title,
            )
            return redirect("exams:prof_exam_sessions")

    if action == "close":
        quiz.status = Quiz.STATUS_CLOSED
        quiz.save(update_fields=["status", "updated_at"])
        absent = _finalize_quiz_absences(quiz)
        message = "QCM fermé : plus aucune tentative possible."
        if absent:
            message += " %s étudiant(s) sans participation marqué(s) absent(s)." % absent
        messages.success(request, message)
        return redirect("exams:prof_exam_sessions")

    questions = list(
        quiz.questions.prefetch_related("choices").order_by("order", "pk")
    )
    return render(request, "exams/prof_quiz_edit.html", {
        "quiz": quiz,
        "session": quiz.session,
        "questions": questions,
        "correct_count": sum(
            1 for question in questions
            if question.choices.filter(is_correct=True).count() == 1
        ),
        "window": quiz.window(),
        "has_attempts": has_attempts,
    })


@role_required(Profil.ROLE_PROF)
@require_GET
def prof_quiz_results(request, pk):
    quiz = _prof_quiz(request, pk)
    if quiz is None:
        return redirect("exams:prof_exam_sessions")
    _finalize_quiz_absences(quiz)
    attempts = list(
        quiz.attempts.select_related(
            "student__membership__user", "student__membership",
        ).order_by("-started_at")
    )
    submitted = [
        attempt for attempt in attempts
        if attempt.is_submitted and not attempt.is_absent
    ]
    scores = [
        attempt.score_20 for attempt in submitted
        if attempt.score_20 is not None
    ]
    average = (sum(scores) / len(scores)) if scores else None
    analysis = quiz.ai_analysis or generate_quiz_analysis(quiz, attempts)
    return render(request, "exams/prof_quiz_results.html", {
        "quiz": quiz,
        "session": quiz.session,
        "attempts": attempts,
        "submitted_count": len(submitted),
        "absent_count": sum(1 for attempt in attempts if attempt.is_absent),
        "average": average,
        "average_label": _format_decimal(average),
        "passed_count": sum(1 for attempt in submitted if attempt.passed),
        "analysis": analysis,
    })


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_quiz_analysis(request, pk):
    quiz = _prof_quiz(request, pk)
    if quiz is None:
        return redirect("exams:prof_exam_sessions")
    _finalize_quiz_absences(quiz)
    attempts = list(quiz.attempts.select_related("student__membership__user"))
    generate_quiz_analysis(quiz, attempts, force=True)
    messages.success(request, "Analyse pédagogique actualisée.")
    return redirect("exams:prof_quiz_results", pk=quiz.pk)


# ---------------------------------------------------------------------------
# Historique et tableau de bord des examens
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_PROF, Profil.ROLE_ADMIN)
def prof_exam_history(request):
    is_admin = request.university_role == Role.UNIVERSITY_ADMIN
    if is_admin:
        session_qs = ExamSession.objects.filter(university=request.university)
    else:
        session_qs = ExamSession.objects.filter(
            school_class__in=_prof_classes(request),
        )
    sessions = list(
        session_qs
        .select_related("school_class", "course_subject", "quiz")
        .annotate(
            project_submission_count=Count(
                "project_submissions", distinct=True,
            ),
            project_graded_count=Count(
                "project_submissions",
                filter=Q(project_submissions__final_score__isnull=False),
                distinct=True,
            ),
            project_average=Avg(
                "project_submissions__final_score",
                filter=Q(project_submissions__final_score__isnull=False),
            ),
            oral_attempt_count=Count("oral_attempts", distinct=True),
            oral_graded_count=Count(
                "oral_attempts",
                filter=Q(oral_attempts__score__isnull=False),
                distinct=True,
            ),
            oral_average=Avg(
                "oral_attempts__score",
                filter=Q(oral_attempts__score__isnull=False),
            ),
            quiz_attempt_count=Count(
                "quiz__attempts",
                filter=Q(quiz__attempts__submitted_at__isnull=False),
                distinct=True,
            ),
        )
        .order_by("-opens_at")
    )
    now = timezone.now()
    for session in sessions:
        session.is_past = session.closes_at < now
        if session.is_project:
            session.result_count = session.project_submission_count
            session.result_graded = session.project_graded_count
            session.result_average = session.project_average
            session.result_link = "exams:prof_project_exam"
            session.result_arg = session.pk
        elif session.is_oral:
            session.result_count = session.oral_attempt_count
            session.result_graded = session.oral_graded_count
            session.result_average = session.oral_average
            session.result_link = "exams:prof_oral_exam"
            session.result_arg = session.pk
        else:
            session.result_count = session.quiz_attempt_count
            session.result_graded = session.quiz_attempt_count
            session.result_average = None
            if getattr(session, "quiz", None) is not None:
                session.result_link = "exams:prof_quiz_results"
                session.result_arg = session.quiz.pk
            else:
                session.result_link = "exams:prof_exam_sessions"
                session.result_arg = None
        if is_admin:
            session.result_link = "exams:admin_exam_sessions"
            session.result_arg = None
        session.result_average_label = _format_decimal(session.result_average)

    return render(request, "exams/prof_exam_history.html", {
        "sessions": sessions,
        "is_admin": is_admin,
        "session_count": len(sessions),
        "qcm_count": sum(1 for session in sessions if session.is_qcm),
        "project_count": sum(1 for session in sessions if session.is_project),
        "oral_count": sum(1 for session in sessions if session.is_oral),
        "past_count": sum(1 for session in sessions if session.is_past),
    })


@role_required(Profil.ROLE_ADMIN, Profil.ROLE_PROF, Profil.ROLE_ETUDIANT)
def exam_dashboard(request):
    membership = getattr(request, "membership", None)
    role = getattr(membership, "role", None)
    student = None
    classes = None
    base_template = "portal/base_student.html"

    if role == Role.STUDENT:
        student = _student_profile(request)
        classes = _student_classes(request)
    elif role == Role.PROFESSOR:
        classes = _prof_classes(request)
        base_template = "portal/base_prof.html"
    else:
        base_template = "portal/base_admin.html"

    sessions_qs = ExamSession.objects.select_related(
        "school_class", "course_subject", "quiz",
    )
    if classes is not None:
        sessions_qs = sessions_qs.filter(school_class__in=classes)
    else:
        sessions_qs = sessions_qs.filter(university=request.university)
    sessions = list(sessions_qs.order_by("opens_at"))
    now = timezone.now()
    for session in sessions:
        session.is_live = session.opens_at <= now <= session.closes_at
        session.is_upcoming = session.opens_at > now
        session.is_past = session.closes_at < now

    def pct(part, total):
        return int(round(part * 100 / total)) if total else 0

    live_sessions = [session for session in sessions if session.is_live]
    upcoming_sessions = [session for session in sessions if session.is_upcoming]
    past_sessions = [session for session in sessions if session.is_past]
    agenda_sessions = (live_sessions + upcoming_sessions)[:6]
    next_session = (
        agenda_sessions[0] if agenda_sessions
        else (past_sessions[-1] if past_sessions else None)
    )
    session_count = len(sessions)
    qcm_count = sum(1 for session in sessions if session.is_qcm)
    project_count = sum(1 for session in sessions if session.is_project)
    oral_count = sum(1 for session in sessions if session.is_oral)

    if role == Role.STUDENT:
        role_label = "Étudiant"
    elif role == Role.PROFESSOR:
        role_label = "Professeur"
    else:
        role_label = "Administration"

    context = {
        "base_template": base_template,
        "role": role,
        "role_label": role_label,
        "is_student": role == Role.STUDENT,
        "is_prof": role == Role.PROFESSOR,
        "is_admin": role not in (Role.STUDENT, Role.PROFESSOR),
        "sessions": sessions,
        "recent_sessions": sessions[:8],
        "agenda_sessions": agenda_sessions,
        "next_session": next_session,
        "now": now,
        "session_count": session_count,
        "qcm_count": qcm_count,
        "project_count": project_count,
        "oral_count": oral_count,
        "open_count": len(live_sessions),
        "upcoming_count": len(upcoming_sessions),
        "past_count": len(past_sessions),
        "open_pct": pct(len(live_sessions), session_count),
        "upcoming_pct": pct(len(upcoming_sessions), session_count),
        "past_pct": pct(len(past_sessions), session_count),
        "qcm_pct": pct(qcm_count, session_count),
        "project_pct": pct(project_count, session_count),
        "oral_pct": pct(oral_count, session_count),
    }

    if student is not None:
        quiz_attempts = {
            attempt.quiz.session_id: attempt
            for attempt in QuizAttempt.objects.filter(
                student=student, quiz__session__in=sessions,
            ).select_related("quiz")
        }
        project_submissions = {
            submission.session_id: submission
            for submission in ProjectSubmission.objects.filter(
                student=student, session__in=sessions,
            )
        }
        oral_attempts = {
            attempt.session_id: attempt
            for attempt in OralAttempt.objects.filter(
                student=student, session__in=sessions,
            )
        }

        def has_participation(session):
            if session.is_qcm:
                return session.pk in quiz_attempts
            if session.is_project:
                return session.pk in project_submissions
            return session.pk in oral_attempts

        todo = []
        for session in sessions:
            if session.is_past:
                continue
            if session.is_project and session.pk not in project_submissions:
                todo.append({
                    "kind": "project", "session": session,
                    "title": "Déposer votre projet",
                    "meta": "Dépôt ZIP ouvert" if session.is_live else "Ouverture à venir",
                })
            elif (
                session.is_oral and session.is_live
                and session.pk not in oral_attempts
            ):
                todo.append({
                    "kind": "oral", "session": session,
                    "title": "Tirer votre sujet d’oral",
                    "meta": "Tirage ouvert",
                })
            elif (
                session.is_qcm and session.is_live
                and getattr(session, "quiz", None)
                and session.pk not in quiz_attempts
            ):
                todo.append({
                    "kind": "qcm", "session": session,
                    "title": "Commencer le QCM",
                    "meta": "%s question(s)" % session.quiz.question_total,
                })

        done_count = sum(1 for session in sessions if has_participation(session))
        recent_grades = list(
            StudentGrade.objects.filter(
                student=student, session__in=sessions,
                status=StudentGrade.STATUS_PUBLISHED,
            )
            .select_related("session", "session__course_subject")
            .order_by("-updated_at")[:4]
        )
        context.update({
            "student_project_submissions": len(project_submissions),
            "student_oral_attempts": len(oral_attempts),
            "student_grades": StudentGrade.objects.filter(
                student=student, session__in=sessions,
                status=StudentGrade.STATUS_PUBLISHED,
            ).count(),
            "student_todo": todo[:4],
            "student_done_count": done_count,
            "student_progress": pct(done_count, session_count),
            "recent_grades": recent_grades,
        })
    else:
        project_submissions = ProjectSubmission.objects.filter(
            session__in=sessions,
        )
        oral_attempts = OralAttempt.objects.filter(session__in=sessions)
        project_pending_count = project_submissions.filter(
            final_score__isnull=True,
        ).count()
        oral_pending_count = oral_attempts.filter(
            score__isnull=True,
        ).count()
        pending_projects = list(
            project_submissions.filter(final_score__isnull=True)
            .select_related("student__membership__user", "session")
            .order_by("-submitted_at")[:4]
        )
        pending_orals = list(
            oral_attempts.filter(score__isnull=True)
            .select_related(
                "student__membership__user", "session", "topic",
            )
            .order_by("-drawn_at")[:4]
        )
        prof_pending_items = (
            [{"kind": "project", "submission": item} for item in pending_projects]
            + [{"kind": "oral", "attempt": item} for item in pending_orals]
        )[:5]
        total_to_grade = project_submissions.count() + oral_attempts.count()
        graded_count = (
            project_submissions.filter(final_score__isnull=False).count()
            + oral_attempts.filter(score__isnull=False).count()
        )
        context.update({
            "project_submission_count": project_submissions.count(),
            "project_pending_count": project_pending_count,
            "oral_attempt_count": oral_attempts.count(),
            "oral_pending_count": oral_pending_count,
            "prof_pending_items": prof_pending_items,
            "prof_progress": pct(graded_count, total_to_grade),
            "prof_done_count": graded_count,
            "prof_total_count": total_to_grade,
            "admin_qcm_missing": sum(
                1 for session in sessions
                if session.is_qcm and getattr(session, "quiz", None) is None
            ),
            "admin_pending_total": project_pending_count + oral_pending_count,
        })

    return render(request, "exams/exam_dashboard.html", context)


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_ADMIN)
def admin_exam_sessions(request):
    edit_session = None
    edit_form = None
    open_modal = None

    edit_id = request.GET.get("edit")
    if edit_id:
        edit_session = (
            ExamSession.objects.filter(pk=edit_id, university=request.university)
            .select_related("school_class", "course_subject")
            .first()
        )
        if edit_session is not None:
            edit_form = ExamSessionForm(
                instance=edit_session,
                university=request.university,
                prefix="edit",
            )
            open_modal = "edit"

    return render(request, "exams/admin_exam_sessions.html",
                  _sessions_context(request, edit_form=edit_form,
                                    edit_session=edit_session, open_modal=open_modal))


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_exam_session_create(request):
    form = ExamSessionForm(
        request.POST, university=request.university, prefix="create", multi=True,
    )
    if form.is_valid():
        sessions = form.save_sessions(
            university=request.university, user=request.user,
        )
        for session in sessions:
            _notify_planning(session, request)
        if len(sessions) == 1:
            session = sessions[0]
            messages.success(
                request,
                "Session « %s » (%s) planifiée pour %s — enseignants et étudiants notifiés."
                % (session.title, session.type_label, session.school_class.name),
            )
        else:
            messages.success(
                request,
                "Session « %s » (%s) planifiée pour %s classes — enseignants et "
                "étudiants notifiés."
                % (sessions[0].title, sessions[0].type_label, len(sessions)),
            )
        return redirect("exams:admin_exam_sessions")
    return render(request, "exams/admin_exam_sessions.html",
                  _sessions_context(request, create_form=form, open_modal="create"))


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_exam_session_update(request, pk):
    session = get_object_or_404(ExamSession, pk=pk, university=request.university)
    form = ExamSessionForm(
        request.POST, instance=session, university=request.university, prefix="edit",
    )
    if form.is_valid():
        form.save()
        messages.success(request, "Session « %s » mise à jour." % session.title)
        return redirect("exams:admin_exam_sessions")
    return render(request, "exams/admin_exam_sessions.html",
                  _sessions_context(request, edit_form=form,
                                    edit_session=session, open_modal="edit"))


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_exam_session_delete(request, pk):
    session = get_object_or_404(ExamSession, pk=pk, university=request.university)
    title = session.title
    session.delete()
    messages.success(request, "Session « %s » supprimée." % title)
    return redirect("exams:admin_exam_sessions")


def _session_export_status(session):
    if session.is_project:
        total = session.project_submissions.count()
        graded = session.project_submissions.filter(
            final_score__isnull=False,
        ).count()
        return "%s dépôt(s), %s noté(s)" % (total, graded)
    if session.is_oral:
        total = session.oral_attempts.count()
        graded = session.oral_attempts.filter(score__isnull=False).count()
        return "%s passage(s), %s noté(s)" % (total, graded)
    quiz = getattr(session, "quiz", None)
    return "Publié" if quiz is not None and quiz.is_published else "En attente"


@role_required(Profil.ROLE_ADMIN)
def admin_exam_sessions_export(request):
    rows = (
        (
            timezone.localtime(session.opens_at).strftime("%Y-%m-%d %H:%M"),
            timezone.localtime(session.closes_at).strftime("%Y-%m-%d %H:%M"),
            session.school_class.name,
            (
                "%s · %s" % (session.course_subject.code, session.course_subject.name)
                if session.course_subject else ""
            ),
            session.title,
            session.type_label,
            _session_export_status(session),
        )
        for session in _tenant_sessions(request)
    )
    return _csv_response(
        "sessions-examen.csv",
        ("Ouverture", "Fermeture", "Classe", "Matière", "Session", "Type", "Statut"),
        rows,
    )


@role_required(Profil.ROLE_ADMIN)
def admin_statistics(request):
    records = _tenant_records(request)
    for record in records:
        _refresh_record_stats(record)
    evaluated = [record for record in records if record.students_count]
    students_total = sum(record.students_count for record in evaluated)
    admitted_total = sum(record.admitted_count for record in evaluated)
    weighted_average = sum(
        (record.average * record.students_count for record in evaluated),
        Decimal("0"),
    )
    average_label = (
        ("%.1f" % (weighted_average / students_total)).replace(".", ",")
        if students_total else "—"
    )
    return render(request, "exams/admin_statistics.html", {
        "semester": EXAM_SEMESTER,
        "records": records,
        "class_count": len(evaluated),
        "students_total": students_total,
        "admitted_total": admitted_total,
        "success_rate": round(admitted_total * 100 / students_total) if students_total else 0,
        "average_label": average_label,
        "qcm_count": sum(
            1 for session in _tenant_sessions(request) if session.is_qcm
        ),
        "project_count": sum(
            1 for session in _tenant_sessions(request) if session.is_project
        ),
        "oral_count": sum(
            1 for session in _tenant_sessions(request) if session.is_oral
        ),
    })


@role_required(Profil.ROLE_ADMIN)
def admin_statistics_export(request):
    records = _tenant_records(request)
    for record in records:
        _refresh_record_stats(record)
    rows = (
        (
            record.school_class.name,
            record.school_class.level,
            record.students_count,
            record.admitted_count,
            record.average_label,
            record.rate_label,
        )
        for record in records
    )
    return _csv_response(
        "statistiques-reussite.csv",
        ("Classe", "Niveau", "Inscrits", "Admis", "Moyenne", "Taux de réussite"),
        rows,
    )


@role_required(Profil.ROLE_ADMIN)
def admin_official_records(request):
    records = _tenant_records(request)
    for record in records:
        _refresh_record_stats(record)
    overviews = _records_overview(records)
    for record in records:
        record.overview = overviews[record.pk]
    pending_records = [record for record in records if not record.pv_signed]
    return render(request, "exams/admin_official_records.html", {
        "semester": EXAM_SEMESTER,
        "records": records,
        "pending_records": pending_records,
        "record_count": len(records),
        "published_count": sum(1 for record in records if record.transcript_published),
        "pending_count": len(pending_records),
        "incomplete_count": sum(
            1 for overview in overviews.values() if overview["incomplete"]
        ),
    })


@role_required(Profil.ROLE_ADMIN)
def admin_official_records_export(request):
    records = _tenant_records(request)
    for record in records:
        _refresh_record_stats(record)
    rows = (
        (
            record.school_class.name,
            record.semester,
            record.students_count,
            record.average_label,
            "Signé" if record.pv_signed else "En attente",
            "Publié" if record.transcript_published else "En attente",
        )
        for record in records
    )
    return _csv_response(
        "releves-officiels.csv",
        ("Classe", "Semestre", "Étudiants", "Moyenne", "PV", "Relevé"),
        rows,
    )


@role_required(Profil.ROLE_ADMIN)
def admin_grade_record_detail(request, pk):
    record = get_object_or_404(
        GradeRecord.objects.select_related("school_class"), pk=pk,
        university=request.university,
    )
    if request.method == "POST" and request.POST.get("action") == "recalculate":
        _refresh_record_stats(record)
        messages.success(
            request,
            "PV de %s recalculé depuis les notes QCM publiées." % record.school_class.name,
        )
        return redirect("exams:admin_grade_record_detail", pk=record.pk)

    _refresh_record_stats(record)
    deliberation_rows, sessions, matrix_sessions, grade_overview = _deliberation_rows(record)
    return render(request, "exams/admin_grade_record_detail.html", {
        "record": record,
        "semester": record.semester,
        "sessions": sessions,
        "matrix_columns": _matrix_columns(matrix_sessions),
        "grade_overview": grade_overview,
        "deliberation_rows": deliberation_rows,
        "deliberation_count": len(deliberation_rows),
        "deliberation_admitted": sum(
            1 for row in deliberation_rows if row["decision"] == "Admis"
        ),
        "deliberation_pending": sum(
            1 for row in deliberation_rows if row["decision"] == "En attente"
        ),
    })


def _sign_record(record, user):
    if record.pv_signed:
        return False
    record.pv_signed = True
    record.pv_signed_at = timezone.now()
    record.pv_signed_by = user
    record.save(update_fields=["pv_signed", "pv_signed_at", "pv_signed_by", "updated_at"])
    return True


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_grade_record_sign(request, pk):
    record = get_object_or_404(GradeRecord, pk=pk, university=request.university)
    if _sign_record(record, request.user):
        messages.success(request, "PV de %s signé." % record.school_class.name)
    else:
        messages.info(request, "Le PV de %s est déjà signé." % record.school_class.name)
    return _next_or(request, "exams:admin_official_records")


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_grade_record_sign_selected(request):
    record_id = request.POST.get("record")
    record = (
        GradeRecord.objects.filter(pk=record_id, university=request.university).first()
        if record_id else None
    )
    if record is None:
        messages.error(request, "Sélectionnez un PV à signer.")
    elif _sign_record(record, request.user):
        messages.success(request, "PV de %s signé." % record.school_class.name)
    else:
        messages.info(request, "Le PV de %s est déjà signé." % record.school_class.name)
    return redirect("exams:admin_official_records")


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_grade_record_publish(request, pk):
    record = get_object_or_404(GradeRecord, pk=pk, university=request.university)
    if not record.pv_signed:
        messages.error(
            request,
            "Signez le PV de %s avant de publier le relevé." % record.school_class.name,
        )
    elif record.transcript_published:
        messages.info(request, "Le relevé de %s est déjà publié." % record.school_class.name)
    else:
        _refresh_record_stats(record)
        overview = _records_overview([record])[record.pk]
        if overview["published"] == 0:
            messages.error(
                request,
                "Publication impossible : aucune note publiée dans la classe %s."
                % record.school_class.name,
            )
        else:
            record.transcript_published = True
            record.published_at = timezone.now()
            record.save(update_fields=["transcript_published", "published_at", "updated_at"])
            if overview["incomplete"]:
                messages.warning(
                    request,
                    "Relevé de %s publié. %s Les notes non publiées n'apparaîtront "
                    "pas dans le relevé." % (record.school_class.name, overview["hint"]),
                )
            else:
                messages.success(
                    request, "Relevé de %s publié." % record.school_class.name,
                )
    return _next_or(request, "exams:admin_official_records")


# ---------------------------------------------------------------------------
# Helpers prof / étudiant
# ---------------------------------------------------------------------------

_PROFILE_RELATED_NAMES = {
    ProfessorProfile: "professor_profile",
    StudentProfile: "student_profile",
}


def _membership_profile(request, profile_class):
    membership = getattr(request, "membership", None)
    if membership is None:
        return None
    try:
        return getattr(membership, _PROFILE_RELATED_NAMES[profile_class])
    except profile_class.DoesNotExist:
        return None


def _prof_profile(request):
    return _membership_profile(request, ProfessorProfile)


def _student_profile(request):
    return _membership_profile(request, StudentProfile)


def _prof_classes(request):
    return professor_classes(_prof_profile(request), request.university)


def _student_classes(request):
    return student_classes(_student_profile(request), request.university)


def _published_records(classes):
    return list(
        GradeRecord.objects.filter(
            school_class__in=classes, transcript_published=True,
        )
        .select_related("school_class")
        .order_by("school_class__name", "semester")
    )


def _published_record_index(classes):
    index = defaultdict(list)
    for record in _published_records(classes):
        index[record.school_class_id].append(record.semester)
    return index


def _grade_matches_record_index(grade, record_index):
    semesters = record_index.get(grade.session.school_class_id)
    if not semesters:
        return False
    return any(
        _semester_matches(grade.session.semester, semester)
        for semester in semesters
    )


def _student_transcript_grades(student, classes):
    record_index = _published_record_index(classes)
    if not record_index:
        return [], record_index
    grades = (
        StudentGrade.objects.filter(
            student=student,
            status=StudentGrade.STATUS_PUBLISHED,
            score__isnull=False,
            session__school_class__in=classes,
        )
        .select_related("session", "session__school_class", "session__course_subject")
        .order_by("session__opens_at")
    )
    return [
        grade for grade in grades
        if _grade_matches_record_index(grade, record_index)
    ], record_index


def _session_students(session):
    return (
        StudentProfile.objects.filter(groups__school_class=session.school_class)
        .distinct()
        .order_by("membership__user__last_name", "membership__user__first_name")
    )


def _class_students(school_class):
    return (
        StudentProfile.objects.filter(groups__school_class=school_class)
        .distinct()
        .select_related("membership__user")
        .order_by("membership__user__last_name", "membership__user__first_name")
    )


def _deliberation_rows(record):
    students = list(_class_students(record.school_class))
    sessions = _record_sessions(record)
    grades = (
        StudentGrade.objects.filter(session__in=sessions, student__in=students)
        .select_related("session")
    )
    by_key = {(grade.student_id, grade.session_id): grade for grade in grades}
    rows, matrix_sessions, stats = _matrix_rows(
        record, students, sessions, by_key,
    )
    return rows, sessions, matrix_sessions, stats


def _student_session(request, pk):
    return get_object_or_404(
        ExamSession, pk=pk, university=request.university,
        school_class__in=_student_classes(request),
    )


def _prof_session(request, pk):
    session = get_object_or_404(
        ExamSession.objects.select_related("school_class", "course_subject", "quiz"),
        pk=pk, school_class__in=_prof_classes(request),
    )
    if not professor_teaches(_prof_profile(request), session):
        messages.error(request, "Cette session ne relève pas de vos enseignements.")
        return None
    return session


def _prof_quiz(request, pk):
    quiz = get_object_or_404(
        Quiz.objects.select_related("session", "session__school_class", "course"),
        pk=pk, session__school_class__in=_prof_classes(request),
    )
    if not professor_teaches(_prof_profile(request), quiz.session):
        messages.error(request, "Ce QCM ne relève pas de vos enseignements.")
        return None
    return quiz


def _quiz_unavailable_message(quiz):
    status = quiz.access_status
    opens_at, closes_at = quiz.window()
    if status == "before":
        return "Le QCM s'ouvre le %s à %s." % (
            timezone.localtime(opens_at).strftime("%d/%m/%Y"),
            timezone.localtime(opens_at).strftime("%H:%M"),
        )
    if status == "after":
        return "Le QCM est terminé depuis le %s à %s." % (
            timezone.localtime(closes_at).strftime("%d/%m/%Y"),
            timezone.localtime(closes_at).strftime("%H:%M"),
        )
    if status == "closed":
        return "Ce QCM a été fermé par l'enseignant."
    return "Le QCM n'est pas encore publié."


def _start_quiz_attempt(quiz, student):
    now = timezone.now()
    _opens_at, closes_at = quiz.window()
    deadline = now + timedelta(minutes=quiz.duration_minutes)
    if closes_at and deadline > closes_at:
        deadline = closes_at

    question_ids = list(
        quiz.questions.order_by("order", "pk").values_list("pk", flat=True)
    )
    if quiz.shuffle_questions:
        random.shuffle(question_ids)

    with transaction.atomic():
        attempt, _created = QuizAttempt.objects.get_or_create(
            quiz=quiz, student=student,
            defaults={
                "deadline_at": deadline,
                "question_order": question_ids,
                "status": QuizAttempt.STATUS_IN_PROGRESS,
            },
        )
    return attempt


def _student_quiz_attempt(request, pk):
    return get_object_or_404(
        QuizAttempt.objects.select_related(
            "quiz", "quiz__session", "quiz__session__school_class",
        ),
        pk=pk, student=_student_profile(request), university=request.university,
        quiz__session__school_class__in=_student_classes(request),
    )


def _attempt_questions(attempt):
    questions = {
        question.pk: question
        for question in attempt.quiz.questions.prefetch_related("choices")
    }
    order = attempt.question_order or []
    ordered = [questions[pk] for pk in order if pk in questions]
    if len(ordered) != len(questions):
        ordered = list(questions.values())
    return ordered


def _store_answers(attempt, data):
    questions = {
        question.pk: question
        for question in attempt.quiz.questions.prefetch_related("choices")
    }
    saved = 0
    for key, raw_value in data.items():
        if not key.startswith("q_"):
            continue
        try:
            question_id = int(key[2:])
        except ValueError:
            continue
        question = questions.get(question_id)
        if question is None:
            continue
        raw_value = (raw_value or "").strip()
        if not raw_value:
            QuizAnswer.objects.filter(attempt=attempt, question=question).delete()
            saved += 1
            continue
        try:
            choice = question.choices.get(pk=raw_value)
        except (QuizChoice.DoesNotExist, ValueError):
            continue
        QuizAnswer.objects.update_or_create(
            attempt=attempt, question=question,
            defaults={"selected_choice": choice},
        )
        saved += 1
    return saved


def _collect_attempt_answers(attempt, data):
    return _store_answers(attempt, data)


def _grade_quiz_attempt(attempt):
    if attempt.is_submitted:
        return attempt

    questions = list(
        attempt.quiz.questions.prefetch_related("choices").order_by("order", "pk")
    )
    answers = {
        answer.question_id: answer
        for answer in attempt.answers.select_related("selected_choice", "question")
    }
    max_score = sum((question.points for question in questions), Decimal("0"))
    score = Decimal("0")
    for question in questions:
        answer = answers.get(question.pk)
        if answer and answer.selected_choice_id and answer.selected_choice.is_correct:
            score += question.points

    with transaction.atomic():
        attempt.score = score
        attempt.max_score = max_score
        attempt.submitted_at = timezone.now()
        attempt.status = QuizAttempt.STATUS_SUBMITTED
        attempt.save(update_fields=[
            "score", "max_score", "submitted_at", "status", "updated_at",
        ])
        _sync_quiz_grade(attempt, score, max_score)
    record = attempt.quiz.session.school_class.grade_records.filter(
        semester=semester_for(attempt.quiz.session.school_class),
    ).first()
    if record is not None:
        _refresh_record_stats(record)
    return attempt


def _finalize_quiz_absences(quiz):
    if not quiz.published_at or quiz.access_status not in ("after", "closed"):
        return 0
    if not quiz.questions.exists():
        return 0

    attempts = {attempt.student_id: attempt for attempt in quiz.attempts.all()}
    for attempt in attempts.values():
        if not attempt.is_submitted and attempt.is_expired:
            _grade_quiz_attempt(attempt)

    max_score = quiz.total_points
    closed_at = quiz.ends_at
    created = 0
    for student in _class_students(quiz.session.school_class):
        if student.pk in attempts:
            continue
        already_graded = StudentGrade.objects.filter(
            session=quiz.session, student=student, score__isnull=False,
        ).exclude(is_absent=True).exists()
        if already_graded:
            continue
        with transaction.atomic():
            attempt, attempt_created = QuizAttempt.objects.get_or_create(
                quiz=quiz, student=student,
                defaults={
                    "started_at": closed_at,
                    "deadline_at": closed_at,
                    "question_order": [],
                    "submitted_at": timezone.now(),
                    "score": Decimal("0"),
                    "max_score": max_score,
                    "status": QuizAttempt.STATUS_EXPIRED,
                },
            )
            if not attempt_created:
                continue
            _sync_quiz_grade(attempt, Decimal("0"), max_score, absent=True)
        created += 1
    if created:
        record = quiz.session.school_class.grade_records.filter(
            semester=semester_for(quiz.session.school_class),
        ).first()
        if record is not None:
            _refresh_record_stats(record)
    return created


def _sync_quiz_grade(attempt, score, max_score, *, absent=False):
    score_20 = (
        (score * Decimal("20") / max_score).quantize(Decimal("0.01"))
        if max_score else Decimal("0")
    )
    grade, _created = StudentGrade.objects.get_or_create(
        session=attempt.quiz.session,
        student=attempt.student,
        defaults={"university": attempt.university},
    )
    grade.university = attempt.university
    grade.score = score_20
    grade.max_score = Decimal("20")
    grade.is_absent = absent
    if absent:
        grade.comment = QUIZ_ABSENT_COMMENT
    else:
        grade.comment = "QCM noté automatiquement (%s/%s points)." % (
            _format_decimal(score), _format_decimal(max_score),
        )
    grade.status = StudentGrade.STATUS_PUBLISHED
    grade.graded_by = attempt.quiz.created_by
    grade.save()


def _sync_exam_grade(session, student, score, *, comment="",
                     graded_by=None, absent=False):
    """Enregistre la note officielle d'une épreuve projet ou oral."""
    grade, _created = StudentGrade.objects.get_or_create(
        session=session, student=student,
        defaults={"university": session.university},
    )
    grade.university = session.university
    grade.score = Decimal("0") if absent else score
    grade.max_score = Decimal("20")
    grade.is_absent = absent
    grade.comment = comment or (
        "Absence enregistrée." if absent else "Note enregistrée par le professeur."
    )
    grade.status = StudentGrade.STATUS_PUBLISHED
    grade.graded_by = graded_by
    grade.save()
    record = GradeRecord.objects.filter(
        school_class=session.school_class,
        semester=semester_for(session.school_class),
    ).first()
    if record is not None:
        _refresh_record_stats(record)
    return grade


def _update_quiz_questions(quiz, data):
    saved = 0
    errors = []
    questions = list(quiz.questions.prefetch_related("choices"))
    for question in questions:
        prompt_key = "q_%s_prompt" % question.pk
        if prompt_key not in data:
            continue
        prompt = (data.get(prompt_key) or "").strip()
        explanation = (data.get("q_%s_explanation" % question.pk) or "").strip()
        points = _to_decimal(data.get("q_%s_points" % question.pk, "1"))
        choices = list(question.choices.all())
        labels = {
            choice.pk: (data.get("choice_%s_label" % choice.pk) or "").strip()
            for choice in choices
        }
        correct_raw = (data.get("q_%s_correct" % question.pk) or "").strip()

        local_errors = []
        if len(prompt) < 3:
            local_errors.append("Énoncé manquant.")
        if points <= 0:
            local_errors.append("Les points doivent être supérieurs à 0.")
        if any(not label for label in labels.values()):
            local_errors.append("Toutes les propositions doivent être renseignées.")
        try:
            correct_pk = int(correct_raw)
        except (TypeError, ValueError):
            correct_pk = None
        if correct_pk not in labels:
            local_errors.append("Sélectionnez la bonne réponse.")
        if local_errors:
            errors.append(
                "Question %s : %s" % (question.order, " ".join(local_errors))
            )
            continue

        with transaction.atomic():
            question.prompt = prompt
            question.explanation = explanation
            question.points = points
            question.save(update_fields=["prompt", "explanation", "points"])
            for choice in choices:
                choice.label = labels[choice.pk]
                choice.is_correct = choice.pk == correct_pk
                choice.save(update_fields=["label", "is_correct"])
        saved += 1

    if saved:
        quiz.question_count = quiz.questions.count()
        quiz.save(update_fields=["question_count", "updated_at"])
    return saved, errors


def _publish_quiz(quiz):
    questions = list(quiz.questions.prefetch_related("choices").order_by("order", "pk"))
    if not questions:
        return ["Ajoutez au moins une question avant de publier le QCM."]

    errors = []
    for question in questions:
        choices = list(question.choices.all())
        prefix = "Question %s" % question.order
        if len(question.prompt.strip()) < 3:
            errors.append("%s : énoncé manquant." % prefix)
        if question.points <= 0:
            errors.append("%s : points invalides." % prefix)
        if len(choices) < 2:
            errors.append("%s : au moins deux propositions sont nécessaires." % prefix)
        elif any(not choice.label.strip() for choice in choices):
            errors.append("%s : une proposition est vide." % prefix)
        if sum(1 for choice in choices if choice.is_correct) != 1:
            errors.append("%s : sélectionnez exactement une bonne réponse." % prefix)
    if errors:
        return errors[:10]

    quiz.question_count = len(questions)
    quiz.status = Quiz.STATUS_PUBLISHED
    quiz.published_at = timezone.now()
    quiz.save(update_fields=[
        "question_count", "status", "published_at", "updated_at",
    ])
    return []


def _pick_by_pk(items, raw_pk):
    for item in items:
        if str(item.pk) == str(raw_pk):
            return item
    return None


def _display_name(profile):
    name = profile.membership.user.get_full_name().strip()
    return name or profile.membership.user.email


def _format_decimal(value):
    if value is None:
        return "—"
    return ("%.2f" % value).rstrip("0").rstrip(".").replace(".", ",")


def _weighted_summary(grades):
    if not grades:
        return None, 0, 0
    coefficient_total = sum((g.session.coefficient for g in grades), Decimal("0"))
    average = (
        sum((g.score * g.session.coefficient for g in grades), Decimal("0"))
        / coefficient_total
    )
    validated = sum(1 for g in grades if g.score >= 10)
    return average, validated, len(grades)


def _group_grades_by_semester(grades):
    grouped = {}
    for grade in grades:
        label = grade.session.semester or "Semestre 1"
        grouped.setdefault(label, []).append(grade)
    return grouped


def _mention_for(average):
    if average >= 16:
        return "Très Bien"
    if average >= 14:
        return "Bien"
    if average >= 12:
        return "Assez Bien"
    if average >= 10:
        return "Passable"
    return "Ajourné"


def _promotion_size(record_index):
    if not record_index:
        return 0
    return (
        StudentProfile.objects.filter(
            groups__school_class_id__in=list(record_index.keys()),
        )
        .distinct().count()
    )


def _compute_rank(student, own_average, record_index):
    if not record_index:
        return None
    class_ids = list(record_index.keys())
    classmate_ids = (
        StudentProfile.objects.filter(groups__school_class_id__in=class_ids)
        .exclude(pk=student.pk).distinct().values_list("pk", flat=True)
    )
    grades = (
        StudentGrade.objects.filter(
            student_id__in=classmate_ids,
            status=StudentGrade.STATUS_PUBLISHED,
            score__isnull=False,
            session__school_class_id__in=class_ids,
        )
        .select_related("session")
    )
    by_student = defaultdict(list)
    for grade in grades:
        if _grade_matches_record_index(grade, record_index):
            by_student[grade.student_id].append(grade)
    better = 0
    for student_grades in by_student.values():
        average, _validated, _total = _weighted_summary(student_grades)
        if average is not None and average > own_average:
            better += 1
    return better + 1


def _current_semester_label(classes):
    first = classes.order_by("name").first()
    return semester_for(first) if first is not None else EXAM_SEMESTER


def _to_decimal(raw):
    try:
        return Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _pdf_response(buffer, filename):
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="%s"' % filename
    return response
