import csv
from collections import defaultdict
from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import Profil
from accounts.tenancy import Role

from .forms import (
    AlertHandleForm,
    AppointmentForm,
    DeclineRequestForm,
    DifficultyNoteForm,
    DifficultyPlanForm,
    DifficultySheetForm,
    JournalEntryForm,
    JournalFeedbackForm,
    SessionSummaryForm,
    SlotForm,
    TaskForm,
    TutorAllocationForm,
)
from .models import (
    DifficultyNote,
    DifficultySheet,
    JournalEntry,
    PerseveranceAlert,
    StudentGoal,
    StudentTask,
    StudySession,
    TutorAssignment,
    TutorNotification,
    TutoringSession,
    TutoringSlot,
)
from .services import (
    ALERT_META,
    CATEGORY_META,
    GOAL_STATUS_META,
    PRIORITY_META,
    RISK_META,
    SENTIMENT_META,
    SESSION_STATE_META,
    SESSION_STATUS_META,
    SEVERITY_META,
    academic_year_for,
    active_assignment,
    allocation_rows,
    assign_students,
    assignment_meta,
    auto_assign_class,
    caseload,
    category_distribution,
    class_label,
    display_name,
    enrolled_count,
    get_professor,
    get_student,
    latest_notification_view,
    next_accepted_session,
    next_exam,
    next_professor_slot,
    next_revision,
    open_alerts_for_students,
    person_initials,
    professor_completed_sessions,
    professor_interviews_this_week,
    professor_last_completed,
    professor_name,
    professor_pending_requests,
    professor_week_slots,
    risk_breakdown,
    student_alert_count,
    student_classes,
    student_goal_stats,
    student_name,
    student_task_counts,
    student_tutors,
    student_week_hours,
    upcoming_slots_for_students,
    waiting_students,
    week_slot_groups,
    admin_monitoring_summary,
)
from .utils import (
    best_streak,
    combine,
    fr_date,
    fr_date_cap,
    fr_date_time,
    fr_date_year,
    fr_day_short,
    fr_day_time,
    fr_decimal,
    fr_time,
    hours_label,
    initials,
    minutes_label,
    parse_clock,
    percent,
    relative_day,
    relative_since,
    streak_days,
    week_bounds,
    week_number,
)

PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


def _csv_response(filename, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="%s"' % filename
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    for row in rows:
        writer.writerow(row)
    return response


def _redirect_message(request, url_name, message, level=messages.SUCCESS, **kwargs):
    messages.add_message(request, level, message)
    return redirect(url_name, **kwargs)


def _form_error_message(form, fallback):
    """Premier message de validation, préfixé par le libellé du champ."""
    for field_name, errors in form.errors.items():
        if not errors:
            continue
        message = str(errors[0])
        field = form.fields.get(field_name)
        label = getattr(field, "label", "") if field else ""
        return "%s : %s" % (label, message) if label and field_name != "__all__" else message
    return fallback


def _overlapping_session(sessions, start, minutes, exclude_pk=None):
    if exclude_pk:
        sessions = sessions.exclude(pk=exclude_pk)
    end = start + timedelta(minutes=minutes or 30)
    for other in sessions.filter(scheduled_at__isnull=False):
        other_start = other.scheduled_at
        other_end = other_start + timedelta(minutes=other.duration_minutes or 30)
        if other_start < end and other_end > start:
            return other
    return None


def _safe_student_redirect(request, fallback):
    target = (request.POST.get("next") or "").strip()
    if (
        target.startswith("/etudiant/")
        and url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return target
    return reverse(fallback)


# ---------------------------------------------------------------------------
# Pages étudiant
# ---------------------------------------------------------------------------


@role_required(Profil.ROLE_ETUDIANT)
def student_dashboard(request):
    return render(request, "coaching/student_dashboard.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_progress(request):
    student = get_student(request)
    stats = student_goal_stats(student)
    goal_items = []
    for goal in stats["goals"]:
        meta = GOAL_STATUS_META.get(goal.status, GOAL_STATUS_META[StudentGoal.STATUS_IN_PROGRESS])
        goal_items.append({
            "goal": goal,
            "meta": meta,
            "target_label": fr_day_short(goal.target_date) if goal.target_date else "Non planifiée",
            "target_full": fr_date_cap(goal.target_date, year=True) if goal.target_date else "",
            "skills_label": (
                "%d/%d compétences acquises" % (goal.skills_acquired, goal.skills_total)
                if goal.skills_total else ""
            ),
            "grade_label": fr_decimal(goal.grade, 1) if goal.grade is not None else "",
        })
    completed_minutes, planned_minutes, sessions = student_week_hours(student)
    target_minutes = 20 * 60
    session_items = []
    for session in sessions[:3]:
        session_items.append({
            "session": session,
            "meta": SESSION_STATUS_META.get(session.status, SESSION_STATUS_META[StudySession.STATUS_SCHEDULED]),
            "when_label": "%s • %s - %s (%s)" % (
                fr_date_cap(session.starts_at) if session.starts_at else "—",
                fr_time(session.starts_at),
                fr_time(session.starts_at + timedelta(minutes=session.duration_minutes)),
                minutes_label(session.duration_minutes),
            ),
        })
    tasks = list(
        student.tasks.filter(is_done=False).order_by("horizon", "-priority", "due_at")[:3]
    )
    task_items = []
    for task in tasks:
        task_items.append({
            "task": task,
            "detail": "%s%s" % (
                task.context_label or "Tâche personnelle",
                " • %s" % fr_day_short(task.due_at) if task.due_at else "",
            ),
        })
    latest_entry = (
        student.journal_entries.select_related("feedback_by__membership__user").first()
    )
    entry_view = None
    if latest_entry:
        entry_view = {
            "entry": latest_entry,
            "meta": SENTIMENT_META[latest_entry.sentiment],
            "initials": person_initials(student),
            "when_label": "%s à %s" % (fr_date_cap(latest_entry.entry_date), fr_time(latest_entry.created_at)),
            "stars": [index < max(1, round(latest_entry.confidence / 2)) for index in range(5)],
            "score": "%d/5" % max(1, round(latest_entry.confidence / 2)),
        }
        if latest_entry.feedback_by_id:
            entry_view["tutor_name"] = professor_name(latest_entry.feedback_by)
            entry_view["tutor_initials"] = person_initials(latest_entry.feedback_by)
            entry_view["feedback_when"] = (
                fr_day_time(latest_entry.feedback_at) if latest_entry.feedback_at else ""
            )
    notification_view = latest_notification_view(student)
    exam = next_exam(student)
    exam_days = None
    exam_countdown = ""
    exam_when_label = ""
    if exam:
        exam_days = (timezone.localtime(exam.starts_at).date() - timezone.localdate()).days
        exam_countdown = (
            "Aujourd'hui" if exam_days == 0
            else "Demain" if exam_days == 1
            else "Dans %d jours" % exam_days
        )
        exam_when_label = "%s · %s" % (
            fr_day_short(exam.starts_at), fr_time(exam.starts_at),
        )
    achieved_recent = student.goals.filter(
        status=StudentGoal.STATUS_ACHIEVED,
        updated_at__gte=timezone.now() - timedelta(days=15),
    ).count()
    remaining_minutes = max(target_minutes - completed_minutes, 0)
    task_counts = student_task_counts(student)
    sessions_remaining_value = sum(
        1 for item in sessions
        if item.status in (StudySession.STATUS_SCHEDULED, StudySession.STATUS_POSTPONED)
        and item.starts_at >= timezone.now()
    )
    urgent_count = task_counts["urgent"]
    context = {
        "goal_items": goal_items,
        "goal_stats": stats,
        "achieved_recent": achieved_recent,
        "achieved_hint": (
            "+%d complété%s depuis 15 jours" % (
                achieved_recent, "" if achieved_recent == 1 else "s",
            ) if achieved_recent else "Aucun objectif validé récemment"
        ),
        "session_items": session_items,
        "sessions_total": len(sessions),
        "sessions_remaining": sessions_remaining_value,
        "sessions_hint": "%d session%s restante%s cette semaine" % (
            sessions_remaining_value,
            "" if sessions_remaining_value == 1 else "s",
            "" if sessions_remaining_value == 1 else "s",
        ),
        "completed_hours": hours_label(completed_minutes),
        "target_hours": "20h",
        "revision_percent": percent(completed_minutes, target_minutes),
        "remaining_hours": hours_label(remaining_minutes),
        "revision_hint": (
            "Objectif hebdomadaire atteint" if remaining_minutes == 0
            else "%s restantes d'ici dimanche" % hours_label(remaining_minutes)
        ),
        "task_items": task_items,
        "task_counts": task_counts,
        "task_urgent_hint": "%d tâche%s urgente%s active%s" % (
            urgent_count,
            "" if urgent_count == 1 else "s",
            "" if urgent_count == 1 else "s",
            "" if urgent_count == 1 else "s",
        ),
        "exam": exam,
        "exam_days": exam_days,
        "exam_countdown": exam_countdown,
        "exam_when_label": exam_when_label,
        "entry_view": entry_view,
        "tutor_notification": notification_view,
        "week_number": week_number(),
        "week_start": fr_day_short(week_bounds()[0]).rstrip("."),
        "week_end": fr_day_short(week_bounds()[1]),
        "today_label": fr_date(timezone.localdate()),
        "journal_add_url": reverse("coaching:student_journal"),
    }
    return render(request, "coaching/student_progress.html", context)


@role_required(Profil.ROLE_ETUDIANT)
def student_tasks(request):
    student = get_student(request)
    counts = student_task_counts(student)
    tasks = list(student.tasks.all())
    task_items = []
    for task in tasks:
        tags = [task.horizon]
        if task.is_done:
            tags.append("done")
        if task.is_done:
            detail = "%s · Terminée le %s" % (
                task.context_label or "Tâche personnelle",
                fr_day_short(task.completed_at or task.due_at or task.created_at),
            )
        else:
            detail = "%s%s" % (
                task.context_label or "Tâche personnelle",
                " · Avant le %s" % fr_day_short(task.due_at) if task.due_at else "",
            )
        task_items.append({
            "task": task,
            "tags": " ".join(tags),
            "detail": detail,
            "horizon_label": task.get_horizon_display(),
            "horizon_class": (
                "bg-primary-fixed text-primary" if task.horizon == StudentTask.HORIZON_TODAY
                else "bg-secondary-fixed text-on-secondary-fixed"
            ),
        })
    today_urgent = student.tasks.filter(
        is_done=False, horizon=StudentTask.HORIZON_TODAY, priority=StudentTask.PRIORITY_HIGH,
    ).count()
    deadlines = student.tasks.filter(due_at__isnull=False, is_done=False).count()
    context = {
        "task_items": task_items,
        "counts": counts,
        "today_urgent": today_urgent,
        "today_hint": "Dont %d prioritaire%s" % (
            today_urgent, "" if today_urgent == 1 else "s",
        ),
        "deadlines": deadlines,
        "deadlines_hint": "%d échéance%s notée%s" % (
            deadlines, "" if deadlines == 1 else "s", "" if deadlines == 1 else "s",
        ),
        "weekly_target": 75,
    }
    return render(request, "coaching/student_tasks.html", context)


@role_required(Profil.ROLE_ETUDIANT)
def student_appointments(request):
    student = get_student(request)
    tutors = student_tutors(student)
    now = timezone.now()
    slots = (
        TutoringSlot.objects.filter(
            professor__in=tutors,
            status=TutoringSlot.STATUS_OPEN,
            starts_at__gte=now,
        )
        .select_related("professor__membership__user")
        .order_by("starts_at")
    )
    slots_by_tutor = defaultdict(list)
    time_values = set()
    for slot in slots:
        local = timezone.localtime(slot.starts_at)
        time_value = "%02d:%02d" % (local.hour, local.minute)
        time_values.add(time_value)
        slots_by_tutor[slot.professor_id].append({
            "slot": slot,
            "day_label": fr_day_short(local),
            "time_label": fr_time(local),
            "time_value": time_value,
            "date_value": local.date().isoformat(),
        })
    tutor_cards = []
    for tutor in tutors:
        tutor_slots = slots_by_tutor.get(tutor.pk, [])
        if not tutor_slots:
            continue
        tutor_cards.append({
            "professor": tutor,
            "name": professor_name(tutor),
            "initials": person_initials(tutor),
            "speciality": tutor.speciality or tutor.department or "Tuteur référent",
            "slots": tutor_slots,
        })
    time_choices = sorted(time_values | {"09:00", "10:00", "14:30", "15:00", "16:00", "17:00"})
    next_session = next_accepted_session(student)
    next_view = None
    if next_session:
        next_view = {
            "session": next_session,
            "tutor_name": professor_name(next_session.professor),
            "tutor_initials": person_initials(next_session.professor),
            "speciality": next_session.professor.speciality or next_session.professor.department or "Tuteur référent",
            "date_label": fr_date_cap(next_session.scheduled_at),
            "short_date": fr_day_short(next_session.scheduled_at),
            "time_label": "%s – %s" % (
                fr_time(next_session.scheduled_at),
                fr_time(next_session.scheduled_at + timedelta(minutes=next_session.duration_minutes)),
            ),
            "mode_label": next_session.get_mode_display(),
            "topic": next_session.topic,
            "meeting_url": next_session.slot.meeting_url if next_session.slot_id else "",
        }
        next_view["hint"] = "%s · %s" % (next_view["time_label"], next_view["mode_label"])
    sessions = list(
        student.tutoring_sessions.select_related("professor__membership__user").order_by("-created_at")[:12]
    )
    history = []
    for session in sessions:
        status = session.status
        if status == TutoringSession.STATUS_ACCEPTED and session.scheduled_at and session.scheduled_at < now:
            status = TutoringSession.STATUS_COMPLETED
        history.append({
            "session": session,
            "when_label": fr_date_time(session.scheduled_at or session.preferred_at or session.created_at),
            "tutor_name": professor_name(session.professor),
            "mode_label": session.get_mode_display(),
            "place": session.location or ("Visioconférence" if session.mode == TutoringSlot.MODE_VIDEO else "À définir"),
            "status_meta": SESSION_STATE_META.get(status, SESSION_STATE_META[TutoringSession.STATUS_PENDING]),
        })
    completed = student.tutoring_sessions.filter(status=TutoringSession.STATUS_COMPLETED).count()
    total_decided = student.tutoring_sessions.filter(
        status__in=(
            TutoringSession.STATUS_COMPLETED,
            TutoringSession.STATUS_DECLINED,
            TutoringSession.STATUS_CANCELLED,
        )
    ).count()
    upcoming = student.tutoring_sessions.filter(
        status=TutoringSession.STATUS_ACCEPTED, scheduled_at__gte=now,
    ).count()
    week_upcoming = student.tutoring_sessions.filter(
        status=TutoringSession.STATUS_ACCEPTED,
        scheduled_at__date__range=week_bounds(),
    ).count()
    attendance_rate = percent(completed, total_decided) if total_decided else 100
    context = {
        "student": student,
        "tutor_cards": tutor_cards,
        "tutor_options": [
            {"id": tutor.pk, "name": professor_name(tutor)} for tutor in tutors
        ],
        "time_choices": time_choices,
        "next_view": next_view,
        "history": history,
        "upcoming_count": upcoming,
        "upcoming_hint": "%d cette semaine" % week_upcoming,
        "completed_count": completed,
        "attendance_rate": attendance_rate,
        "attendance_hint": "Taux de présence : %d %%" % attendance_rate,
        "open_slots_count": sum(len(card["slots"]) for card in tutor_cards),
        "today_value": timezone.localdate().isoformat(),
        "max_date_value": (timezone.localdate() + timedelta(days=90)).isoformat(),
        "default_slot_time": time_choices[0] if time_choices else "09:00",
    }
    return render(request, "coaching/student_appointments.html", context)


@role_required(Profil.ROLE_ETUDIANT)
def student_journal(request):
    student = get_student(request)
    entries = list(
        student.journal_entries.select_related("feedback_by__membership__user")
    )
    entry_views = []
    for entry in entries:
        entry_views.append({
            "entry": entry,
            "meta": SENTIMENT_META[entry.sentiment],
            "when_label": "%s · %s" % (fr_date_cap(entry.entry_date), fr_time(entry.created_at)),
            "feedback_name": professor_name(entry.feedback_by) if entry.feedback_by_id else "",
            "feedback_initials": person_initials(entry.feedback_by) if entry.feedback_by_id else "",
            "feedback_when": fr_day_time(entry.feedback_at) if entry.feedback_at else "",
        })
    confidence_values = [entry.confidence for entry in entries]
    latest_confidence = confidence_values[0] if confidence_values else None
    average_confidence = (
        round(sum(confidence_values) / len(confidence_values), 1) if confidence_values else None
    )
    delta_confidence = (
        confidence_values[0] - confidence_values[-1] if len(confidence_values) > 1 else 0
    )
    entry_dates = [entry.entry_date for entry in entries]
    streak = streak_days(entry_dates)
    best = best_streak(entry_dates)
    stats = student_goal_stats(student)
    weeks = []
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    for index in range(7, -1, -1):
        start = monday - timedelta(weeks=index)
        end = start + timedelta(days=6)
        week_entries = [item for item in entries if start <= item.entry_date <= end]
        value = (
            int(round(sum(item.confidence for item in week_entries) / len(week_entries) * 10))
            if week_entries else 0
        )
        weeks.append({
            "label": "S%d" % (8 - index),
            "height": value,
            "value": value,
            "current": index == 0,
        })
    next_session = next_accepted_session(student)
    next_study = next_revision(student)
    last_entry = entries[0] if entries else None
    notification_view = latest_notification_view(student)
    if latest_confidence is None:
        confidence_hint = "Aucune auto-évaluation"
    elif len(confidence_values) < 2:
        confidence_hint = "Première évaluation enregistrée"
    elif delta_confidence > 0:
        confidence_hint = "+%d pts depuis la première entrée" % delta_confidence
    elif delta_confidence < 0:
        confidence_hint = "%d pts depuis la première entrée" % delta_confidence
    else:
        confidence_hint = "Stable depuis la première entrée"
    context = {
        "entry_views": entry_views,
        "entry_count": len(entries),
        "latest_confidence": latest_confidence,
        "average_confidence": average_confidence,
        "average_percent": int(round((average_confidence or 0) * 10)),
        "confidence_delta": delta_confidence,
        "confidence_hint": confidence_hint,
        "streak": streak,
        "streak_suffix": " jour" if streak == 1 else " jours",
        "best_streak": best,
        "best_streak_hint": "Meilleure série : %d jour%s" % (
            best, "" if best == 1 else "s",
        ),
        "weeks": weeks,
        "today_percent": int(round((latest_confidence or 0) * 10)),
        "goal_stats": stats,
        "next_study_label": (
            "%s à %s" % (fr_date_cap(next_study.starts_at), fr_time(next_study.starts_at))
            if next_study else "Aucune révision planifiée"
        ),
        "next_session_label": (
            "%s à %s" % (fr_date_cap(next_session.scheduled_at), fr_time(next_session.scheduled_at))
            if next_session else "Aucun rendez-vous"
        ),
        "latest_confidence_label": (
            fr_decimal(latest_confidence, 1) if latest_confidence is not None else "—"
        ),
        "last_entry_label": relative_since(last_entry.created_at) if last_entry else "Aucune entrée",
        "sentiment_choices": JournalEntry.SENTIMENT_CHOICES,
        "today_value": timezone.localdate().isoformat(),
        "goals_target": 75,
        "tutor_notification": notification_view,
    }
    return render(request, "coaching/student_journal.html", context)


# ---------------------------------------------------------------------------
# Pages professeur
# ---------------------------------------------------------------------------


@role_required(Profil.ROLE_PROF)
def prof_dashboard(request):
    return render(request, "coaching/prof_dashboard.html")


@role_required(Profil.ROLE_PROF)
def prof_followup(request):
    professor = get_professor(request)
    assignments = list(caseload(professor))
    rows = []
    student_ids = [item.student_id for item in assignments]
    open_alerts = open_alerts_for_students(student_ids)
    alerts_by_student = defaultdict(list)
    for alert in open_alerts:
        alerts_by_student[alert.student_id].append(alert)
    upcoming_ids = set(
        TutoringSession.objects.filter(
            student_id__in=student_ids,
            professor=professor,
            status=TutoringSession.STATUS_ACCEPTED,
            scheduled_at__gte=timezone.now(),
        ).values_list("student_id", flat=True)
    )
    upcoming_by_student = {}
    for session in TutoringSession.objects.filter(
        student_id__in=student_ids,
        professor=professor,
        status=TutoringSession.STATUS_ACCEPTED,
        scheduled_at__gte=timezone.now(),
    ).select_related("professor__membership__user"):
        upcoming_by_student[session.student_id] = session
    for assignment in assignments:
        meta = assignment_meta(assignment)
        meta["alerts_count"] = len(alerts_by_student.get(assignment.student_id, []))
        meta["last_contact_label"] = relative_since(assignment.last_contact_at) if assignment.last_contact_at else "Aucun échange"
        meta["next_session"] = upcoming_by_student.get(assignment.student_id)
        meta["next_session_label"] = (
            fr_day_time(meta["next_session"].scheduled_at) if meta["next_session"] else ""
        )
        delta = assignment.delta
        if delta is None or delta == 0:
            meta["delta_label"] = "Stable"
            meta["delta_tone"] = "text-outline"
            meta["delta_icon"] = "remove"
        elif delta > 0:
            meta["delta_label"] = "+%s pts" % fr_decimal(delta, 1)
            meta["delta_tone"] = "text-primary"
            meta["delta_icon"] = "trending_up"
        else:
            meta["delta_label"] = "%s pts" % fr_decimal(delta, 1)
            meta["delta_tone"] = "text-error"
            meta["delta_icon"] = "trending_down"
        meta["average_label"] = (
            fr_decimal(assignment.average_grade, 1)
            if assignment.average_grade is not None else "—"
        )
        meta["attendance_label"] = (
            "%d %%" % assignment.attendance_rate
            if assignment.attendance_rate else "—"
        )
        meta["assignments_label"] = assignment.assignments_ratio
        meta["program"] = assignment.student.program or "Filière non renseignée"
        meta["risk_reason"] = assignment.risk_reason or "Aucun signalement actif."
        rows.append({"assignment": assignment, "meta": meta})
    classes = {}
    for assignment in assignments:
        if assignment.school_class_id:
            classes[assignment.school_class_id] = assignment.school_class
    cohort_options = sorted(classes.values(), key=lambda item: item.name)
    query = (request.GET.get("q") or "").strip()[:100]
    cohort = request.GET.get("cohort") or ""
    if cohort and cohort not in {str(item.pk) for item in cohort_options}:
        cohort = ""
    focus = request.GET.get("risk") or ""
    if focus not in {"high", "pending", "progress"}:
        focus = ""
    if query:
        lowered = query.lower()
        rows = [
            row for row in rows
            if lowered in display_name(row["assignment"].student).lower()
            or lowered in (row["assignment"].student.student_number or "").lower()
        ]
    if cohort:
        try:
            cohort_id = int(cohort)
        except (TypeError, ValueError):
            cohort_id = 0
        rows = [row for row in rows if row["assignment"].school_class_id == cohort_id]
    if focus == "high":
        rows = [row for row in rows if row["assignment"].risk_level in (TutorAssignment.RISK_HIGH, TutorAssignment.RISK_WATCH)]
    elif focus == "pending":
        rows = [row for row in rows if row["assignment"].student_id not in upcoming_ids]
    elif focus == "progress":
        rows = [
            row for row in rows
            if row["assignment"].delta is not None and row["assignment"].delta > 0
        ]
    rows.sort(key=lambda row: (
        PRIORITY_ORDER.get("high", 0)
        if row["assignment"].risk_level == TutorAssignment.RISK_HIGH
        else (1 if row["assignment"].risk_level == TutorAssignment.RISK_WATCH else 2),
        row["assignment"].student.membership.user.last_name.lower(),
    ))
    risk_counts = risk_breakdown(assignments)
    high_alerts = sum(
        1 for alert in open_alerts if alert.priority == PerseveranceAlert.PRIORITY_HIGH
    )
    completed = professor_completed_sessions(professor).count()
    interviews = professor_interviews_this_week(professor).count()
    next_slot = next_professor_slot(professor)
    grades = [float(item.average_grade) for item in assignments if item.average_grade is not None]
    deltas = [float(item.delta) for item in assignments if item.delta is not None]
    average = round(sum(grades) / len(grades), 1) if grades else None
    average_delta = round(sum(deltas) / len(deltas), 1) if deltas else None
    dispersion = None
    if grades:
        mean = sum(grades) / len(grades)
        dispersion = round((sum((grade - mean) ** 2 for grade in grades) / len(grades)) ** 0.5, 1)
    class_counts = defaultdict(int)
    for assignment in assignments:
        label = assignment.school_class.name if assignment.school_class_id else class_label(assignment.student) or "Sans classe"
        class_counts[label] += 1
    class_hint = " · ".join(
        "%s (%d)" % (label, count)
        for label, count in sorted(class_counts.items(), key=lambda item: -item[1])[:2]
    ) or "Aucun étudiant référent"
    progress_count = sum(
        1 for item in assignments if item.delta is not None and item.delta > 0
    )
    agenda = []
    for slot in list(professor_week_slots(professor))[:4]:
        session = None
        for candidate in slot.sessions.all():
            if candidate.status in (TutoringSession.STATUS_ACCEPTED, TutoringSession.STATUS_COMPLETED):
                session = candidate
                break
        agenda.append({
            "slot": slot,
            "session": session,
            "student_name": student_name(session.student) if session else "",
            "time_label": "%s - %s" % (
                fr_time(slot.starts_at),
                fr_time(slot.ends_at),
            ),
            "mode_label": slot.get_mode_display(),
            "mode_icon": "videocam" if slot.mode == TutoringSlot.MODE_VIDEO else "room",
            "place": slot.location or ("Visio" if slot.mode == TutoringSlot.MODE_VIDEO else "Bureau"),
            "priority_label": session.get_priority_display() if session else "",
            "is_priority": bool(session and session.priority == TutoringSession.PRIORITY_HIGH),
        })
    week_slots = list(professor_week_slots(professor))
    context = {
        "rows": rows,
        "row_count": len(rows),
        "total_rows": len(assignments),
        "query": query,
        "cohort": cohort,
        "cohort_options": cohort_options,
        "focus": focus,
        "risk_counts": risk_counts,
        "vigilance_count": risk_counts.get(TutorAssignment.RISK_HIGH, 0) + risk_counts.get(TutorAssignment.RISK_WATCH, 0),
        "vigilance_share": percent(
            risk_counts.get(TutorAssignment.RISK_HIGH, 0) + risk_counts.get(TutorAssignment.RISK_WATCH, 0),
            len(assignments),
        ),
        "pending_interviews": sum(1 for item in assignments if item.student_id not in upcoming_ids),
        "progress_count": progress_count,
        "caseload_count": len(assignments),
        "alert_count": open_alerts.count(),
        "high_alerts": high_alerts,
        "completed_interviews": completed,
        "interviews_this_week": interviews,
        "completion_rate": percent(completed, len(assignments)),
        "next_slot_label": fr_day_time(next_slot.starts_at) if next_slot else "Aucun créneau",
        "average": fr_decimal(average, 1) if average is not None else "—",
        "dispersion": fr_decimal(dispersion, 1) if dispersion is not None else "—",
        "average_delta_label": (
            "+%s pt%s" % (fr_decimal(average_delta, 1), "" if average_delta in (1, -1) else "s")
            if average_delta is not None
            else "Aucune évolution"
        ),
        "average_delta_tone": (
            "text-primary" if average_delta is not None and average_delta > 0
            else ("text-error" if average_delta is not None and average_delta < 0 else "text-outline")
        ),
        "average_delta_icon": (
            "trending_up" if average_delta is not None and average_delta > 0
            else ("trending_down" if average_delta is not None and average_delta < 0 else "remove")
        ),
        "class_hint": class_hint,
        "agenda": agenda,
        "week_booked": sum(1 for slot in week_slots if slot.status == TutoringSlot.STATUS_BOOKED),
        "week_total": len(week_slots),
        "week_slot_target": 6,
        "week_label": "Semaine du %s au %s" % (
            fr_day_short(week_bounds()[0]), fr_day_short(week_bounds()[1]),
        ),
        "today_label": fr_date_cap(timezone.localdate()),
        "export_url": reverse("coaching:prof_followup_export"),
        "tutoring_url": reverse("coaching:prof_tutoring"),
        "journal_url": reverse("coaching:prof_student_journal"),
    }
    return render(request, "coaching/prof_followup.html", context)


@role_required(Profil.ROLE_PROF)
def prof_tutoring(request):
    professor = get_professor(request)
    requests_qs = professor_pending_requests(professor)
    request_rows = []
    for item in requests_qs:
        meta = PRIORITY_META.get(item.priority, PRIORITY_META[TutoringSession.PRIORITY_NORMAL])
        request_rows.append({
            "session": item,
            "student_name": student_name(item.student),
            "student_initials": person_initials(item.student),
            "student_email": item.student.membership.user.email,
            "class_name": item.school_class.name if item.school_class_id else class_label(item.student) or "—",
            "preferred_label": fr_day_time(item.preferred_at) if item.preferred_at else "À définir",
            "priority_meta": meta,
        })
    groups = []
    for group in week_slot_groups(professor):
        slots = []
        for slot in group["slots"]:
            session = None
            for candidate in slot.sessions.all():
                if candidate.status in (TutoringSession.STATUS_ACCEPTED, TutoringSession.STATUS_COMPLETED):
                    session = candidate
                    break
            slots.append({
                "slot": slot,
                "session": session,
                "student_name": student_name(session.student) if session else "",
                "time_label": "%s – %s" % (fr_time(slot.starts_at), fr_time(slot.ends_at)),
                "is_booked": slot.status == TutoringSlot.STATUS_BOOKED,
            })
        groups.append({
            "date": group["date"],
            "label": fr_date_cap(group["date"]),
            "slots": slots,
        })
    week_slots = list(professor_week_slots(professor))
    interviews = list(professor_interviews_this_week(professor))
    individual = sum(1 for item in interviews if item.mode == TutoringSlot.MODE_INDIVIDUAL)
    group_count = sum(1 for item in interviews if item.mode == TutoringSlot.MODE_GROUP)
    assignments = list(caseload(professor))
    last_completed = professor_last_completed(professor)
    last_view = None
    if last_completed:
        last_view = {
            "session": last_completed,
            "student_name": student_name(last_completed.student),
            "when_label": fr_date_cap(last_completed.completed_at or last_completed.scheduled_at),
            "duration": minutes_label(last_completed.duration_minutes),
            "place": last_completed.location or last_completed.get_mode_display(),
        }
    session_rows = []
    for item in (
        TutoringSession.objects.filter(
            professor=professor,
            university=request.university,
            status=TutoringSession.STATUS_ACCEPTED,
        )
        .select_related("student__membership__user", "school_class")
        .order_by("scheduled_at")[:12]
    ):
        session_rows.append({
            "session": item,
            "student_name": student_name(item.student),
            "student_initials": person_initials(item.student),
            "student_email": item.student.membership.user.email,
            "class_name": item.school_class.name if item.school_class_id else class_label(item.student) or "—",
            "when_label": fr_day_time(item.scheduled_at) if item.scheduled_at else "À définir",
            "mode_label": item.get_mode_display(),
            "mode_icon": "videocam" if item.mode == TutoringSlot.MODE_VIDEO else "room",
        })
    context = {
        "request_rows": request_rows,
        "pending_count": len(request_rows),
        "session_rows": session_rows,
        "session_count": len(session_rows),
        "groups": groups,
        "week_slots": week_slots,
        "open_slots": sum(1 for slot in week_slots if slot.status == TutoringSlot.STATUS_OPEN),
        "booked_slots": sum(1 for slot in week_slots if slot.status == TutoringSlot.STATUS_BOOKED),
        "interviews_this_week": len(interviews),
        "individual_count": individual,
        "group_count": group_count,
        "interviews_hint": "%d individuel%s · %d collectif%s" % (
            individual, "" if individual == 1 else "s",
            group_count, "" if group_count == 1 else "s",
        ),
        "caseload_count": len(assignments),
        "reinforced_count": sum(1 for item in assignments if item.risk_level == TutorAssignment.RISK_HIGH),
        "caseload_hint": "%d en suivi renforcé" % sum(
            1 for item in assignments if item.risk_level == TutorAssignment.RISK_HIGH
        ),
        "last_view": last_view,
        "week_label": "Semaine du %s" % fr_day_short(week_bounds()[0]),
        "today_label": fr_date_cap(timezone.localdate()),
        "today_value": timezone.localdate().isoformat(),
        "max_date_value": (timezone.localdate() + timedelta(days=90)).isoformat(),
        "default_slot_date": (timezone.localdate() + timedelta(days=3)).isoformat(),
        "slot_time_choices": ["09:00", "09:30", "14:00", "14:30", "15:00", "15:30", "16:00", "17:00"],
        "mode_choices": TutoringSlot.MODE_CHOICES,
    }
    return render(request, "coaching/prof_tutoring.html", context)


@role_required(Profil.ROLE_PROF)
def prof_followup_cards(request):
    professor = get_professor(request)
    sheets = list(
        DifficultySheet.objects.filter(professor=professor)
        .select_related("student__membership__user", "school_class")
        .prefetch_related("notes")
    )
    sheet_rows = []
    for sheet in sheets:
        severity = SEVERITY_META.get(sheet.severity, SEVERITY_META[DifficultySheet.SEVERITY_MODERATE])
        sheet_rows.append({
            "sheet": sheet,
            "severity": severity,
            "initials": person_initials(sheet.student),
            "student_name": student_name(sheet.student),
            "student_program": sheet.student.program or (
                sheet.school_class.name if sheet.school_class_id else "Filière non renseignée"
            ),
            "student_number": sheet.student.student_number or "—",
            "class_name": sheet.school_class.name if sheet.school_class_id else class_label(sheet.student),
            "category_label": sheet.get_category_display(),
            "category_tags": sheet.category,
            "average_label": fr_decimal(sheet.average_grade, 1) if sheet.average_grade is not None else "—",
            "attendance_label": "%d %%" % sheet.attendance_rate if sheet.attendance_rate else "—",
            "assignments_label": sheet.assignments_ratio or "—",
            "last_contact_label": relative_since(sheet.last_contact_at) if sheet.last_contact_at else "Aucun échange",
            "note_url": reverse("coaching:prof_sheet_note", args=[sheet.pk]),
            "plan_url": reverse("coaching:prof_sheet_plan", args=[sheet.pk]),
            "notes_count": len(sheet.notes.all()),
        })
    active = [item for item in sheets if item.status != DifficultySheet.STATUS_CLOSED]
    closed_recent = sum(
        1 for item in sheets
        if item.status == DifficultySheet.STATUS_CLOSED
        and item.closed_at
        and item.closed_at >= timezone.now() - timedelta(days=30)
    )
    assignment_options = []
    for assignment in caseload(professor):
        assignment_options.append({
            "student": assignment.student,
            "label": "%s · %s" % (
                student_name(assignment.student),
                assignment.school_class.name if assignment.school_class_id else class_label(assignment.student) or "Sans classe",
            ),
        })
    upcoming = (
        TutoringSession.objects.filter(
            professor=professor,
            status=TutoringSession.STATUS_ACCEPTED,
            scheduled_at__gte=timezone.now(),
        )
        .select_related("student__membership__user")
        .order_by("scheduled_at")[:3]
    )
    context = {
        "sheet_rows": sheet_rows,
        "active_count": len(active),
        "high_count": sum(1 for item in active if item.severity == DifficultySheet.SEVERITY_HIGH),
        "in_progress_count": sum(1 for item in active if item.status == DifficultySheet.STATUS_IN_PROGRESS),
        "closed_recent": closed_recent,
        "distribution": category_distribution(sheets),
        "next_appointments": [
            {
                "name": student_name(item.student),
                "when": "%s · %s" % (fr_day_short(item.scheduled_at), fr_time(item.scheduled_at)),
            }
            for item in upcoming
        ],
        "assignment_options": assignment_options,
        "category_choices": DifficultySheet.CATEGORY_CHOICES,
        "severity_choices": DifficultySheet.SEVERITY_CHOICES,
        "export_url": reverse("coaching:prof_sheets_export"),
    }
    return render(request, "coaching/prof_followup_cards.html", context)


@role_required(Profil.ROLE_PROF)
def prof_student_journal(request):
    professor = get_professor(request)
    assignments = list(caseload(professor))
    panel_rows = []
    all_confidences = []
    entries_this_week = 0
    week_start, week_end = week_bounds()
    for assignment in assignments:
        student = assignment.student
        entries = list(
            student.journal_entries.select_related("feedback_by__membership__user")[:4]
        )
        latest = entries[0] if entries else None
        confidence = latest.confidence if latest else None
        if confidence is not None:
            all_confidences.append(confidence)
        entries_this_week += sum(1 for item in entries if week_start <= item.entry_date <= week_end)
        goals = []
        for goal in student.goals.all()[:4]:
            meta = GOAL_STATUS_META.get(goal.status, GOAL_STATUS_META[StudentGoal.STATUS_IN_PROGRESS])
            goals.append({"goal": goal, "meta": meta})
        tone = "text-primary"
        if confidence is not None and confidence < 5:
            tone = "text-error"
        elif confidence is not None and confidence < 7:
            tone = "text-tertiary"
        panel_rows.append({
            "assignment": assignment,
            "student": student,
            "initials": person_initials(student),
            "name": student_name(student),
            "program": student.program or (
                assignment.school_class.name if assignment.school_class_id else "Filière non renseignée"
            ),
            "class_name": assignment.school_class.name if assignment.school_class_id else "",
            "confidence": confidence,
            "confidence_label": fr_decimal(confidence, 1) if confidence is not None else "—",
            "confidence_tone": tone,
            "last_entry_label": relative_day(latest.entry_date) if latest else "Aucune entrée",
            "has_today_entry": bool(latest and latest.entry_date == timezone.localdate()),
            "latest_at": latest.created_at if latest else None,
            "entries": [
                {
                    "entry": item,
                    "meta": SENTIMENT_META[item.sentiment],
                    "when_label": "%s · %s" % (fr_date_cap(item.entry_date), fr_time(item.created_at)),
                    "feedback_name": professor_name(item.feedback_by) if item.feedback_by_id else "",
                    "feedback_when": fr_day_time(item.feedback_at) if item.feedback_at else "",
                    "feedback_url": reverse("coaching:prof_journal_feedback", args=[item.pk]),
                }
                for item in entries[:3]
            ],
            "goals": goals,
            "alert_count": student_alert_count(student),
            "attendance_label": "%d %%" % assignment.attendance_rate if assignment.attendance_rate else "—",
            "average_label": fr_decimal(assignment.average_grade, 1) if assignment.average_grade is not None else "—",
        })
    requested = (request.GET.get("student") or "").strip()
    if not requested.isdigit() or len(requested) > 9:
        requested = ""
    selected = None
    for row in panel_rows:
        if str(row["student"].pk) == str(requested):
            selected = row
            break
    if selected is None and panel_rows:
        with_entries = [row for row in panel_rows if row["latest_at"] is not None]
        selected = max(with_entries, key=lambda row: row["latest_at"]) if with_entries else panel_rows[0]
    average_confidence = (
        round(sum(all_confidences) / len(all_confidences), 1) if all_confidences else None
    )
    class_ids = {item.school_class_id for item in assignments if item.school_class_id}
    open_alert_count = 0
    for row in panel_rows:
        open_alert_count += row["alert_count"]
    reinforced = sum(1 for item in assignments if item.risk_level == TutorAssignment.RISK_HIGH)
    context = {
        "panel_rows": panel_rows,
        "selected_id": str(selected["student"].pk) if selected else "",
        "student_count": len(panel_rows),
        "classes_count": len(class_ids),
        "students_hint": "%d classe%s suivie%s" % (
            len(class_ids), "" if len(class_ids) == 1 else "s",
            "" if len(class_ids) == 1 else "s",
        ),
        "entries_this_week": entries_this_week,
        "average_confidence": fr_decimal(average_confidence, 1) if average_confidence is not None else "—",
        "alert_count": open_alert_count,
        "reinforced_count": reinforced,
        "alerts_hint": "%d suivi%s renforcé%s" % (
            reinforced, "" if reinforced == 1 else "s", "" if reinforced == 1 else "s",
        ),
        "tutoring_url": reverse("coaching:prof_tutoring"),
    }
    return render(request, "coaching/prof_student_journal.html", context)


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_journal_feedback(request, pk):
    professor = get_professor(request)
    student_ids = caseload(professor).values_list("student_id", flat=True)
    entry = get_object_or_404(
        JournalEntry,
        pk=pk,
        university=request.university,
        student_id__in=student_ids,
    )
    form = JournalFeedbackForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(form, "Rédigez un retour avant de l'enregistrer."),
        )
        return redirect("%s?student=%s" % (reverse("coaching:prof_student_journal"), entry.student_id))
    entry.feedback = form.cleaned_data["feedback"]
    entry.feedback_by = professor
    entry.feedback_at = timezone.now()
    entry.save(update_fields=["feedback", "feedback_by", "feedback_at"])
    messages.success(
        request,
        "Retour publié sur l'entrée de %s." % student_name(entry.student),
    )
    return redirect("%s?student=%s" % (reverse("coaching:prof_student_journal"), entry.student_id))


# ---------------------------------------------------------------------------
# Pages administration université
# ---------------------------------------------------------------------------


@role_required(Profil.ROLE_ADMIN)
def admin_dashboard(request):
    return render(request, "coaching/admin_dashboard.html")


@role_required(Profil.ROLE_ADMIN)
def admin_perseverance(request):
    rows, year = allocation_rows(request.university)
    students_total = sum(row["students"] for row in rows)
    assigned_total = sum(row["assigned"] for row in rows)
    waiting_total = sum(row["waiting"] for row in rows)
    rate = percent(assigned_total, students_total) if students_total else 0
    tutor_ids = set()
    for row in rows:
        tutor_ids.update(
            TutorAssignment.objects.filter(
                school_class=row["school_class"],
                academic_year=year,
                status=TutorAssignment.STATUS_ACTIVE,
            ).values_list("professor_id", flat=True)
        )
    tutor_options = [
        {
            "id": profile.pk,
            "name": professor_name(profile),
            "label": "%s · %s" % (
                professor_name(profile),
                profile.speciality or profile.department or "Enseignant référent",
            ),
        }
        for profile in request.university.professor_profiles.select_related("membership__user").order_by(
            "membership__user__last_name", "membership__user__first_name",
        )
    ] if hasattr(request.university, "professor_profiles") else []
    if not tutor_options:
        from accounts.models import ProfessorProfile

        tutor_options = [
            {
                "id": profile.pk,
                "name": professor_name(profile),
                "label": "%s · %s" % (
                    professor_name(profile),
                    profile.speciality or profile.department or "Enseignant référent",
                ),
            }
            for profile in ProfessorProfile.objects.filter(
                university=request.university,
            ).select_related("membership__user").order_by(
                "membership__user__last_name", "membership__user__first_name",
            )
        ]
    context = {
        "rows": rows,
        "row_count": len(rows),
        "assigned_total": assigned_total,
        "waiting_total": waiting_total,
        "students_hint": "Sur %d étudiants inscrits" % students_total,
        "waiting_hint": "%d étudiant%s en attente d'affectation" % (
            waiting_total, "" if waiting_total == 1 else "s",
        ),
        "tutor_total": len(tutor_ids),
        "allocation_rate_label": "%d %%" % rate,
        "tutor_options": tutor_options,
        "academic_year": year,
        "export_url": reverse("coaching:admin_perseverance_export"),
    }
    return render(request, "coaching/admin_perseverance.html", context)


@role_required(Profil.ROLE_ADMIN)
def admin_monitoring(request):
    summary = admin_monitoring_summary(request.university)
    alerts = []
    for alert in summary["alerts"]:
        meta = ALERT_META.get(alert.alert_type, ALERT_META[PerseveranceAlert.TYPE_ENGAGEMENT])
        alerts.append({
            "alert": alert,
            "meta": meta,
            "student_name": student_name(alert.student) if alert.student_id else "Classe",
            "class_name": (
                alert.school_class.name if alert.school_class_id
                else (class_label(alert.student) if alert.student_id else "—")
            ),
            "priority_label": alert.get_priority_display(),
            "is_open": alert.status == PerseveranceAlert.STATUS_OPEN,
            "status_label": alert.get_status_display(),
            "detected_label": fr_date_cap(alert.detected_at),
        })
    cohorts = []
    for cohort in summary["cohorts"]:
        high = cohort["high"]
        if high:
            status, status_class = "Vigilance", "bg-error-container text-on-error-container"
        elif cohort["alerts"]:
            status, status_class = "Sous surveillance", "bg-tertiary-fixed text-on-tertiary-fixed"
        else:
            status, status_class = "Stable", "bg-primary-fixed text-primary"
        cohorts.append({**cohort, "status": status, "status_class": status_class})
    activities = []
    for index, activity in enumerate(summary["activities"]):
        activities.append({
            **activity,
            "when": relative_day(activity["at"]) if activity["at"] else "—",
            "time": fr_time(activity["at"]) if activity["at"] else "",
            "first": index == 0,
        })
    context = {
        "summary": summary,
        "cohorts": cohorts,
        "alert_rows": alerts,
        "activities": activities,
        "year": summary["year"],
        "followed_hint": "Avec un référent actif · année %s" % summary["year"],
        "alerts_hint": "%d priorité%s haute%s" % (
            summary["high_alerts"],
            "" if summary["high_alerts"] == 1 else "s",
            "" if summary["high_alerts"] == 1 else "s",
        ),
        "perseverance_hint": "Étudiants hors vigilance haute",
        "remediation_hint": "%d clôturée%s sur 30 jours" % (
            summary["closed_recent"],
            "" if summary["closed_recent"] == 1 else "s",
        ),
        "report_url": reverse("coaching:admin_monitoring_export"),
    }
    return render(request, "coaching/admin_monitoring.html", context)


# ---------------------------------------------------------------------------
# Actions étudiant
# ---------------------------------------------------------------------------


@require_POST
@role_required(Profil.ROLE_ETUDIANT)
def student_task_add(request):
    student = get_student(request)
    form = TaskForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(form, "Vérifiez l'intitulé et l'horizon de la tâche."),
        )
        return redirect("coaching:student_tasks")
    title = form.cleaned_data["title"]
    if StudentTask.objects.filter(
        student=student, title__iexact=title, is_done=False,
    ).exists():
        messages.error(request, "Une tâche active porte déjà ce titre.")
        return redirect("coaching:student_tasks")
    horizon = form.cleaned_data["horizon"]
    due = timezone.localdate() if horizon == StudentTask.HORIZON_TODAY else timezone.localdate() + timedelta(days=4)
    StudentTask.objects.create(
        student=student,
        title=title,
        horizon=horizon,
        priority=StudentTask.PRIORITY_NORMAL,
        due_at=due,
        context_label="Ajoutée depuis le portail",
    )
    messages.success(request, "Tâche ajoutée à votre liste.")
    return redirect("coaching:student_tasks")


@require_POST
@role_required(Profil.ROLE_ETUDIANT)
def student_task_toggle(request, pk):
    student = get_student(request)
    task = get_object_or_404(StudentTask, pk=pk, student=student, university=request.university)
    task.is_done = not task.is_done
    task.save()
    if task.is_done:
        messages.success(request, "Tâche marquée comme terminée.")
    else:
        messages.info(request, "Tâche réouverte.")
    return redirect(_safe_student_redirect(request, "coaching:student_tasks"))


@require_POST
@role_required(Profil.ROLE_ETUDIANT)
def student_appointment_request(request):
    student = get_student(request)
    form = AppointmentForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(
                form, "Complétez le tuteur, la date, l'heure et le motif de la demande.",
            ),
        )
        return redirect("coaching:student_appointments")
    tutors = {tutor.pk: tutor for tutor in student_tutors(student)}
    professor = tutors.get(form.cleaned_data["professor"])
    if professor is None:
        messages.error(request, "Ce tuteur ne fait pas partie de votre encadrement.")
        return redirect("coaching:student_appointments")
    preferred_at = combine(form.cleaned_data["date"], parse_clock(form.cleaned_data["time"]))
    if _overlapping_session(
        student.tutoring_sessions.filter(status=TutoringSession.STATUS_ACCEPTED),
        preferred_at,
        30,
    ):
        messages.error(request, "Vous avez déjà un rendez-vous confirmé sur ce créneau.")
        return redirect("coaching:student_appointments")
    if _overlapping_session(
        TutoringSession.objects.filter(
            professor=professor, status=TutoringSession.STATUS_ACCEPTED,
        ),
        preferred_at,
        30,
    ):
        messages.error(request, "Ce tuteur a déjà un rendez-vous confirmé sur ce créneau.")
        return redirect("coaching:student_appointments")
    try:
        with transaction.atomic():
            TutoringSession.objects.create(
                university=request.university,
                student=student,
                professor=professor,
                school_class=next(iter(student_classes(student)), None),
                preferred_at=preferred_at,
                topic=form.cleaned_data["topic"],
                mode=TutoringSlot.MODE_VIDEO,
                created_by=request.user,
            )
    except IntegrityError:
        messages.error(request, "Vous avez déjà une demande en attente avec ce tuteur.")
        return redirect("coaching:student_appointments")
    messages.success(request, "Votre demande de rendez-vous a bien été envoyée.")
    return redirect("coaching:student_appointments")


@require_POST
@role_required(Profil.ROLE_ETUDIANT)
def student_appointment_reschedule(request, pk):
    student = get_student(request)
    session = get_object_or_404(
        TutoringSession, pk=pk, student=student, university=request.university,
    )
    if session.status == TutoringSession.STATUS_PENDING:
        messages.info(request, "Une demande est déjà en attente avec ce tuteur.")
        return redirect("coaching:student_appointments")
    if session.status not in (
        TutoringSession.STATUS_ACCEPTED,
        TutoringSession.STATUS_DECLINED,
    ):
        messages.error(request, "Ce rendez-vous ne peut plus être reporté.")
        return redirect("coaching:student_appointments")
    base = session.scheduled_at or session.preferred_at or timezone.now()
    if base < timezone.now():
        base = timezone.now()
    preferred_at = base + timedelta(days=7)
    if preferred_at > timezone.now() + timedelta(days=90):
        messages.error(request, "La nouvelle date dépasse la fenêtre de réservation de 90 jours.")
        return redirect("coaching:student_appointments")
    try:
        with transaction.atomic():
            TutoringSession.objects.create(
                university=request.university,
                student=student,
                professor=session.professor,
                school_class=session.school_class,
                preferred_at=preferred_at,
                topic=("Report · %s" % session.topic)[:200],
                priority=session.priority,
                mode=session.mode,
                created_by=request.user,
            )
    except IntegrityError:
        messages.error(request, "Une demande est déjà en attente avec ce tuteur.")
        return redirect("coaching:student_appointments")
    messages.success(request, "Demande de report envoyée à votre tuteur.")
    return redirect("coaching:student_appointments")


@require_POST
@role_required(Profil.ROLE_ETUDIANT)
def student_journal_add(request):
    student = get_student(request)
    form = JournalEntryForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(
                form, "Complétez le titre, le ressenti et la réflexion.",
            ),
        )
        return redirect("coaching:student_journal")
    sentiment = form.cleaned_data["sentiment"]
    try:
        with transaction.atomic():
            JournalEntry.objects.create(
                university=request.university,
                student=student,
                title=form.cleaned_data["title"],
                reflection=form.cleaned_data["reflection"],
                sentiment=sentiment,
                confidence=JournalEntry.SENTIMENT_CONFIDENCE_SCORE.get(sentiment, 6),
                entry_date=timezone.localdate(),
            )
    except IntegrityError:
        messages.error(request, "Une entrée avec ce titre existe déjà aujourd'hui.")
        return redirect("coaching:student_journal")
    messages.success(request, "Entrée ajoutée à votre journal.")
    return redirect("coaching:student_journal")


@require_POST
@role_required(Profil.ROLE_ETUDIANT)
def student_goal_postpone(request, pk):
    student = get_student(request)
    goal = get_object_or_404(StudentGoal, pk=pk, student=student, university=request.university)
    if goal.status not in (StudentGoal.STATUS_IN_PROGRESS, StudentGoal.STATUS_AT_RISK):
        messages.error(request, "Seuls les objectifs en cours ou en retard peuvent être reprogrammés.")
        return redirect("coaching:student_progress")
    base = goal.target_date or timezone.localdate()
    new_target = base + timedelta(days=7)
    if new_target > timezone.localdate() + timedelta(days=365):
        messages.error(request, "L'échéance ne peut pas être repoussée au-delà d'un an.")
        return redirect("coaching:student_progress")
    goal.target_date = new_target
    goal.save(update_fields=["target_date", "updated_at"])
    messages.success(request, "Échéance reportée d'une semaine.")
    return redirect("coaching:student_progress")


@role_required(Profil.ROLE_ETUDIANT)
def student_progress_export(request):
    student = get_student(request)
    rows = [["Rapport de progression", display_name(student), fr_date_year(timezone.localdate())]]
    rows.append([])
    rows.append(["Objectif", "Statut", "Avancement (%)", "Échéance", "Note"])
    for goal in student.goals.all():
        rows.append([
            goal.title,
            goal.get_status_display(),
            goal.progress,
            goal.target_date.isoformat() if goal.target_date else "",
            fr_decimal(goal.grade, 2) if goal.grade is not None else "",
        ])
    rows.append([])
    rows.append(["Session", "Type", "Début", "Durée (min)", "Statut"])
    for session in student.study_sessions.all():
        rows.append([
            session.title,
            session.get_kind_display(),
            fr_date_time(session.starts_at),
            session.duration_minutes,
            session.get_status_display(),
        ])
    rows.append([])
    rows.append(["Tâche", "Horizon", "Échéance", "Terminée"])
    for task in student.tasks.all():
        rows.append([
            task.title,
            task.get_horizon_display(),
            task.due_at.isoformat() if task.due_at else "",
            "Oui" if task.is_done else "Non",
        ])
    return _csv_response("progression-%s.csv" % student.pk, rows)


# ---------------------------------------------------------------------------
# Actions professeur
# ---------------------------------------------------------------------------


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_slot_create(request):
    professor = get_professor(request)
    form = SlotForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(
                form, "Renseignez une date, une heure et une modalité valides.",
            ),
        )
        return redirect("coaching:prof_tutoring")
    starts_at = combine(form.cleaned_data["date"], parse_clock(form.cleaned_data["time"]))
    ends_at = starts_at + timedelta(minutes=30)
    if TutoringSlot.objects.filter(
        professor=professor,
        university=request.university,
        status__in=(TutoringSlot.STATUS_OPEN, TutoringSlot.STATUS_BOOKED),
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).exists():
        messages.error(request, "Un créneau chevauche déjà cet horaire dans votre permanence.")
        return redirect("coaching:prof_tutoring")
    mode = form.cleaned_data["mode"]
    try:
        with transaction.atomic():
            slot = TutoringSlot.objects.create(
                university=request.university,
                professor=professor,
                school_class=professor.classes.first(),
                starts_at=starts_at,
                ends_at=ends_at,
                mode=mode,
                location="" if mode == TutoringSlot.MODE_VIDEO else "Bureau du référent",
                meeting_url=(
                    "https://visio.eduspark.example/%s-%s"
                    % (professor.pk, starts_at.strftime("%Y%m%d%H%M"))
                ) if mode == TutoringSlot.MODE_VIDEO else "",
                reference="%s-%s" % (professor.pk, starts_at.strftime("%Y%m%d%H%M")),
                created_by=request.user,
            )
    except IntegrityError:
        messages.error(request, "Un créneau existe déjà à cette date pour ce tuteur.")
        return redirect("coaching:prof_tutoring")
    messages.success(request, "Créneau du %s à %s publié." % (fr_day_short(slot.starts_at), fr_time(slot.starts_at)))
    return redirect("coaching:prof_tutoring")


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_request_accept(request, pk):
    professor = get_professor(request)
    session = get_object_or_404(
        TutoringSession,
        pk=pk,
        professor=professor,
        university=request.university,
        status=TutoringSession.STATUS_PENDING,
    )
    slot = session.slot
    if slot is not None:
        if slot.university_id != request.university.pk or slot.professor_id != professor.pk:
            messages.error(request, "Ce créneau n'appartient pas à votre permanence.")
            return redirect("coaching:prof_tutoring")
        if slot.status != TutoringSlot.STATUS_OPEN:
            messages.error(request, "Ce créneau vient d'être réservé. Choisissez-en un autre.")
            return redirect("coaching:prof_tutoring")
        scheduled_at = slot.starts_at
        duration = max(int((slot.ends_at - slot.starts_at).total_seconds() // 60), 15)
    elif session.preferred_at:
        scheduled_at = session.preferred_at
        duration = session.duration_minutes or 30
    else:
        scheduled_at = timezone.now() + timedelta(days=3)
        duration = session.duration_minutes or 30
    if scheduled_at <= timezone.now():
        messages.error(
            request,
            "Ce créneau est déjà passé. Refusez la demande et proposez une nouvelle date.",
        )
        return redirect("coaching:prof_tutoring")
    if _overlapping_session(
        TutoringSession.objects.filter(
            professor=professor, status=TutoringSession.STATUS_ACCEPTED,
        ),
        scheduled_at,
        duration,
        exclude_pk=session.pk,
    ):
        messages.error(request, "Un autre rendez-vous occupe déjà ce créneau.")
        return redirect("coaching:prof_tutoring")
    with transaction.atomic():
        if slot is not None:
            session.scheduled_at = scheduled_at
            session.duration_minutes = duration
            session.mode = slot.mode
            session.location = slot.location
            slot.status = TutoringSlot.STATUS_BOOKED
            slot.save(update_fields=["status"])
        else:
            session.scheduled_at = scheduled_at
        session.status = TutoringSession.STATUS_ACCEPTED
        session.decided_by = request.user
        session.decided_at = timezone.now()
        session.save()
    messages.success(
        request,
        "Rendez-vous accepté pour %s. L'étudiant a été notifié."
        % fr_day_time(session.scheduled_at),
    )
    return redirect("coaching:prof_tutoring")


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_request_decline(request, pk):
    professor = get_professor(request)
    session = get_object_or_404(
        TutoringSession,
        pk=pk,
        professor=professor,
        university=request.university,
        status=TutoringSession.STATUS_PENDING,
    )
    form = DeclineRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form, "Vérifiez le motif du refus."))
        return redirect("coaching:prof_tutoring")
    with transaction.atomic():
        if session.slot_id and session.slot.status == TutoringSlot.STATUS_BOOKED:
            session.slot.status = TutoringSlot.STATUS_OPEN
            session.slot.save(update_fields=["status"])
        session.status = TutoringSession.STATUS_DECLINED
        session.decision_note = form.cleaned_data.get("note") or ""
        session.decided_by = request.user
        session.decided_at = timezone.now()
        session.save()
    messages.info(request, "Demande refusée, une proposition alternative sera suggérée.")
    return redirect("coaching:prof_tutoring")


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_session_complete(request, pk):
    professor = get_professor(request)
    session = get_object_or_404(
        TutoringSession,
        pk=pk,
        professor=professor,
        university=request.university,
        status=TutoringSession.STATUS_ACCEPTED,
    )
    form = SessionSummaryForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(form, "Résumez les points abordés avant de clôturer l'entretien."),
        )
        return redirect("coaching:prof_tutoring")
    now = timezone.now()
    with transaction.atomic():
        session.status = TutoringSession.STATUS_COMPLETED
        session.summary_points = form.cleaned_data["summary_points"]
        session.summary_actions = form.cleaned_data.get("summary_actions") or ""
        session.completed_at = now
        session.save(update_fields=[
            "status", "summary_points", "summary_actions", "completed_at", "updated_at",
        ])
        TutorAssignment.objects.filter(
            professor=professor,
            student=session.student,
            university=request.university,
            status=TutorAssignment.STATUS_ACTIVE,
        ).update(last_contact_at=now, updated_at=now)
    messages.success(
        request,
        "Entretien avec %s clôturé et compte-rendu enregistré." % student_name(session.student),
    )
    return redirect("coaching:prof_tutoring")


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_sheet_create(request):
    professor = get_professor(request)
    form = DifficultySheetForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(
                form, "Complétez l'étudiant, le type de difficulté et le constat.",
            ),
        )
        return redirect("coaching:prof_followup_cards")
    assignment = (
        TutorAssignment.objects.filter(
            professor=professor,
            student_id=form.cleaned_data["student"],
            university=request.university,
            status=TutorAssignment.STATUS_ACTIVE,
        )
        .select_related("student", "school_class")
        .first()
    )
    if assignment is None:
        messages.error(request, "Cet étudiant ne fait pas partie de votre portefeuille.")
        return redirect("coaching:prof_followup_cards")
    try:
        with transaction.atomic():
            DifficultySheet.objects.create(
                university=request.university,
                student=assignment.student,
                professor=professor,
                school_class=assignment.school_class,
                category=form.cleaned_data["category"],
                severity=form.cleaned_data.get("severity") or DifficultySheet.SEVERITY_MODERATE,
                observation=form.cleaned_data["observation"],
                action_plan=form.cleaned_data.get("action_plan") or "",
                average_grade=assignment.average_grade,
                attendance_rate=assignment.attendance_rate,
                assignments_submitted=assignment.assignments_submitted,
                assignments_total=assignment.assignments_total,
                last_contact_at=assignment.last_contact_at,
            )
    except IntegrityError:
        messages.error(request, "Une fiche ouverte existe déjà pour ce type de difficulté.")
        return redirect("coaching:prof_followup_cards")
    messages.success(request, "Fiche de difficulté créée. L'étudiant sera notifié de l'ouverture du suivi.")
    return redirect("coaching:prof_followup_cards")


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_sheet_note(request, pk):
    professor = get_professor(request)
    sheet = get_object_or_404(
        DifficultySheet, pk=pk, professor=professor, university=request.university,
    )
    form = DifficultyNoteForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(form, "Écrivez une note avant d'enregistrer le suivi."),
        )
        return redirect("coaching:prof_followup_cards")
    if sheet.status == DifficultySheet.STATUS_CLOSED:
        messages.error(request, "Cette fiche est clôturée : aucune note ne peut être ajoutée.")
        return redirect("coaching:prof_followup_cards")
    with transaction.atomic():
        DifficultyNote.objects.create(
            sheet=sheet,
            author=request.user,
            note=form.cleaned_data["note"],
        )
        sheet.last_contact_at = timezone.now()
        if sheet.status == DifficultySheet.STATUS_OPEN:
            sheet.status = DifficultySheet.STATUS_IN_PROGRESS
        sheet.save(update_fields=["last_contact_at", "status", "updated_at"])
    messages.success(request, "Suivi enregistré et partagé avec l'équipe référente.")
    return redirect("coaching:prof_followup_cards")


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_sheet_plan(request, pk):
    professor = get_professor(request)
    sheet = get_object_or_404(
        DifficultySheet, pk=pk, professor=professor, university=request.university,
    )
    form = DifficultyPlanForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(form, "Rédigez le plan d'accompagnement avant de l'enregistrer."),
        )
        return redirect("coaching:prof_followup_cards")
    sheet.action_plan = form.cleaned_data["action_plan"]
    fields = ["action_plan", "updated_at"]
    if sheet.status == DifficultySheet.STATUS_OPEN:
        sheet.status = DifficultySheet.STATUS_IN_PROGRESS
        fields.append("status")
    sheet.save(update_fields=fields)
    messages.success(
        request,
        "Plan d'accompagnement mis à jour pour %s." % student_name(sheet.student),
    )
    return redirect("coaching:prof_followup_cards")


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_student_relance(request, student_id):
    professor = get_professor(request)
    assignment = get_object_or_404(
        TutorAssignment,
        professor=professor,
        student_id=student_id,
        university=request.university,
        status=TutorAssignment.STATUS_ACTIVE,
    )
    if (
        assignment.last_contact_at
        and timezone.now() - assignment.last_contact_at < timedelta(minutes=2)
    ):
        messages.info(
            request,
            "Une relance vient d'être envoyée à %s. Patientez avant de relancer."
            % student_name(assignment.student),
        )
        return redirect("coaching:prof_followup")
    assignment.last_contact_at = timezone.now()
    with transaction.atomic():
        assignment.save(update_fields=["last_contact_at", "updated_at"])
        TutorNotification.objects.create(
            university=request.university,
            student=assignment.student,
            professor=professor,
            kind=TutorNotification.KIND_RELANCE,
            title="Relance de votre tuteur référent",
            message=(
                "%s vous invite à faire le point sur votre progression. %s"
                % (
                    professor_name(professor),
                    assignment.risk_reason
                    or "Consultez votre journal et reprenez contact avec votre tuteur.",
                )
            ),
        )
    messages.success(
        request,
        "Notification ENT envoyée à %s." % student_name(assignment.student),
    )
    return redirect("coaching:prof_followup")


@require_POST
@role_required(Profil.ROLE_PROF)
def prof_student_alert(request, student_id):
    professor = get_professor(request)
    assignment = get_object_or_404(
        TutorAssignment,
        professor=professor,
        student_id=student_id,
        university=request.university,
        status=TutorAssignment.STATUS_ACTIVE,
    )
    priority = (
        PerseveranceAlert.PRIORITY_HIGH
        if assignment.risk_level == TutorAssignment.RISK_HIGH
        else PerseveranceAlert.PRIORITY_NORMAL
    )
    detail = assignment.risk_reason or "Signalement du professeur référent."
    alert = PerseveranceAlert.objects.filter(
        student=assignment.student,
        alert_type=PerseveranceAlert.TYPE_ENGAGEMENT,
        status=PerseveranceAlert.STATUS_OPEN,
    ).first()
    if alert is None:
        PerseveranceAlert.objects.create(
            university=request.university,
            student=assignment.student,
            school_class=assignment.school_class,
            alert_type=PerseveranceAlert.TYPE_ENGAGEMENT,
            title="Signalement pédagogique · %s" % student_name(assignment.student),
            detail=detail,
            priority=priority,
            detected_at=timezone.now(),
        )
        messages.success(
            request,
            "Alerte transmise au référent scolarité pour %s." % student_name(assignment.student),
        )
        return redirect("coaching:prof_followup")
    updates = []
    if alert.priority != PerseveranceAlert.PRIORITY_HIGH:
        alert.priority = PerseveranceAlert.PRIORITY_HIGH
        updates.append("priority")
    if detail and alert.detail != detail:
        alert.detail = detail
        updates.append("detail")
    if alert.school_class_id is None and assignment.school_class_id:
        alert.school_class = assignment.school_class
        updates.append("school_class")
    if updates:
        alert.save(update_fields=updates + ["updated_at"])
        messages.success(
            request,
            "Alerte existante renforcée en priorité haute pour %s."
            % student_name(assignment.student),
        )
    else:
        messages.info(
            request,
            "Une alerte prioritaire est déjà ouverte pour %s."
            % student_name(assignment.student),
        )
    return redirect("coaching:prof_followup")


@role_required(Profil.ROLE_PROF)
def prof_followup_export(request):
    professor = get_professor(request)
    rows = [["Étudiant", "Classe", "Moyenne", "Moyenne précédente", "Évolution", "Assiduité (%)",
             "Devoirs rendus", "Devoirs attendus", "Risque", "Alertes", "Dernier contact"]]
    for assignment in caseload(professor):
        rows.append([
            student_name(assignment.student),
            assignment.school_class.name if assignment.school_class_id else class_label(assignment.student),
            fr_decimal(assignment.average_grade, 2) if assignment.average_grade is not None else "",
            fr_decimal(assignment.previous_average, 2) if assignment.previous_average is not None else "",
            fr_decimal(assignment.delta, 1) if assignment.delta is not None else "",
            assignment.attendance_rate,
            assignment.assignments_submitted,
            assignment.assignments_total,
            assignment.get_risk_level_display(),
            student_alert_count(assignment.student),
            fr_date_time(assignment.last_contact_at) if assignment.last_contact_at else "",
        ])
    return _csv_response("suivi-etudiants-%s.csv" % professor.pk, rows)


@role_required(Profil.ROLE_PROF)
def prof_sheets_export(request):
    professor = get_professor(request)
    rows = [[
        "Étudiant", "Classe", "Type", "Gravité", "Statut", "Constat", "Plan d'accompagnement",
        "Moyenne", "Assiduité (%)", "Devoirs rendus", "Devoirs attendus", "Ouverte le",
    ]]
    for sheet in DifficultySheet.objects.filter(professor=professor).select_related(
        "student__membership__user", "school_class",
    ):
        rows.append([
            student_name(sheet.student),
            sheet.school_class.name if sheet.school_class_id else "",
            sheet.get_category_display(),
            sheet.get_severity_display(),
            sheet.get_status_display(),
            sheet.observation,
            sheet.action_plan,
            fr_decimal(sheet.average_grade, 2) if sheet.average_grade is not None else "",
            sheet.attendance_rate,
            sheet.assignments_submitted,
            sheet.assignments_total,
            fr_date_time(sheet.opened_at),
        ])
    return _csv_response("fiches-difficultes-%s.csv" % professor.pk, rows)


# ---------------------------------------------------------------------------
# Actions administration
# ---------------------------------------------------------------------------


@require_POST
@role_required(Profil.ROLE_ADMIN)
def admin_assign_tutor(request):
    form = TutorAllocationForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _form_error_message(
                form, "Sélectionnez une classe, un tuteur et un nombre d'étudiants valide.",
            ),
        )
        return redirect("coaching:admin_perseverance")
    from accounts.models import ProfessorProfile, SchoolClass

    school_class = get_object_or_404(
        SchoolClass, pk=form.cleaned_data["school_class"], university=request.university,
    )
    professor = get_object_or_404(
        ProfessorProfile, pk=form.cleaned_data["professor"], university=request.university,
    )
    if not professor.membership.is_active:
        messages.error(request, "Ce tuteur est inactif et ne peut pas recevoir d'étudiants.")
        return redirect("coaching:admin_perseverance")
    year = school_class.academic_year or academic_year_for(request.university)
    waiting_count = waiting_students(school_class, year).count()
    if waiting_count == 0:
        messages.info(request, "Aucun étudiant en attente dans cette classe.")
        return redirect("coaching:admin_perseverance")
    if form.cleaned_data["count"] > waiting_count:
        messages.error(
            request,
            "Cette classe ne compte que %d étudiant%s en attente : ajustez le nombre."
            % (waiting_count, "" if waiting_count == 1 else "s"),
        )
        return redirect("coaching:admin_perseverance")
    created = assign_students(
        school_class, professor, form.cleaned_data["count"], year, request.user,
    )
    remaining = waiting_students(school_class, year).count()
    messages.success(
        request,
        "%d étudiant%s affecté%s à %s. %d encore en attente."
        % (created, "" if created == 1 else "s", "" if created == 1 else "s",
           professor_name(professor), remaining),
    )
    return redirect("coaching:admin_perseverance")


@require_POST
@role_required(Profil.ROLE_ADMIN)
def admin_auto_assign(request):
    rows, year = allocation_rows(request.university)
    created = 0
    skipped = 0
    for row in rows:
        if row["waiting"] <= 0:
            continue
        if not row["school_class"].professors.exists():
            skipped += 1
            continue
        created += auto_assign_class(row["school_class"], year, request.user)
    if created:
        messages.success(
            request,
            "Attribution automatique : %d étudiant%s réparti%s sur les tuteurs des classes."
            % (created, "" if created == 1 else "s", "" if created == 1 else "s"),
        )
    elif skipped:
        messages.warning(request, "Aucun tuteur n'est rattaché aux classes en attente.")
    else:
        messages.info(request, "Aucun étudiant en attente d'affectation.")
    return redirect("coaching:admin_perseverance")


@role_required(Profil.ROLE_ADMIN)
def admin_perseverance_export(request):
    rows, year = allocation_rows(request.university)
    output = [["Année universitaire", year], []]
    output.append(["Classe", "Niveau", "Étudiants", "Tuteurs", "Affectés", "En attente", "Taux (%)", "Statut"])
    for row in rows:
        output.append([
            row["school_class"].name,
            row["school_class"].level,
            row["students"],
            row["tutors"],
            row["assigned"],
            row["waiting"],
            row["rate"],
            row["status"],
        ])
    return _csv_response("attribution-tuteurs-%s.csv" % year, output)


@require_POST
@role_required(Profil.ROLE_ADMIN)
def admin_alert_take(request, pk):
    alert = get_object_or_404(PerseveranceAlert, pk=pk, university=request.university)
    if alert.status != PerseveranceAlert.STATUS_OPEN:
        messages.info(request, "Cette alerte est déjà prise en charge.")
        return redirect("coaching:admin_monitoring")
    form = AlertHandleForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form, "Vérifiez la note de résolution."))
        return redirect("coaching:admin_monitoring")
    alert.status = PerseveranceAlert.STATUS_TAKEN
    alert.taken_by = request.user
    alert.taken_at = timezone.now()
    alert.resolution_note = form.cleaned_data.get("resolution_note") or ""
    alert.save(update_fields=["status", "taken_by", "taken_at", "resolution_note", "updated_at"])
    messages.success(request, "Alerte assignée à un référent pédagogique.")
    return redirect("coaching:admin_monitoring")


@role_required(Profil.ROLE_ADMIN)
def admin_monitoring_export(request):
    summary = admin_monitoring_summary(request.university)
    rows = [
        ["Rapport de pilotage", summary["year"]],
        ["Étudiants suivis", summary["followed"]],
        ["Alertes actives", summary["active_alerts"]],
        ["Alertes prioritaires", summary["high_alerts"]],
        ["Taux de persévérance (%)", summary["perseverance_rate"]],
        ["Actions de remédiation ouvertes", summary["open_sheets"]],
        ["Actions clôturées (30 j)", summary["closed_recent"]],
        [],
        ["Cohorte", "Étudiants", "Alertes", "Vigilance haute", "Progression objectifs (%)", "Assiduité (%)", "Moyenne"],
    ]
    for cohort in summary["cohorts"]:
        rows.append([
            cohort["school_class"].name,
            cohort["students"],
            cohort["alerts"],
            cohort["high"],
            cohort["goal_progress"],
            cohort["attendance"],
            fr_decimal(cohort["average"], 1) if cohort["average"] is not None else "",
        ])
    rows.append([])
    rows.append(["Alerte", "Étudiant", "Classe", "Priorité", "Statut", "Détectée le"])
    for alert in summary["alerts"]:
        rows.append([
            alert.title,
            student_name(alert.student) if alert.student_id else "",
            alert.school_class.name if alert.school_class_id else "",
            alert.get_priority_display(),
            alert.get_status_display(),
            fr_date_time(alert.detected_at),
        ])
    return _csv_response("pilotage-perseverance-%s.csv" % summary["year"], rows)
