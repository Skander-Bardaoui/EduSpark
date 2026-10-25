"""Calculs et référentiels partagés du module Suivi Référent."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from accounts.models import ProfessorProfile, SchoolClass, StudentProfile
from accounts.tenancy import Role

from .models import (
    DifficultySheet,
    PerseveranceAlert,
    StudentGoal,
    StudentTask,
    StudySession,
    TutorAssignment,
    TutoringSession,
    TutoringSlot,
)
from .utils import fr_day_time, initials, percent, week_bounds

ACADEMIC_YEAR_FALLBACK = "2025-2026"

RISK_META = {
    TutorAssignment.RISK_HIGH: {
        "label": "Vigilance haute",
        "short": "Vigilance",
        "badge": "bg-error-container text-on-error-container",
        "border": "border-error/30",
        "icon": "warning",
        "tone": "text-error",
        "box": "bg-error-container/30",
        "box_icon": "bg-error text-on-error",
    },
    TutorAssignment.RISK_WATCH: {
        "label": "Vigilance modérée",
        "short": "À suivre",
        "badge": "bg-tertiary-fixed text-on-tertiary-fixed",
        "border": "border-outline-variant/40",
        "icon": "schedule",
        "tone": "text-tertiary",
        "box": "bg-surface-container-low",
        "box_icon": "bg-tertiary-fixed text-on-tertiary-fixed",
    },
    TutorAssignment.RISK_LOW: {
        "label": "Autonome",
        "short": "Stable",
        "badge": "bg-surface-container-high text-on-surface",
        "border": "border-outline-variant/40",
        "icon": "check",
        "tone": "text-primary",
        "box": "bg-surface-container-lowest",
        "box_icon": "bg-secondary text-on-secondary",
    },
}

SEVERITY_META = {
    DifficultySheet.SEVERITY_HIGH: {
        "label": "Vigilance haute",
        "badge": "bg-error-container text-on-error-container",
        "border": "border-error/30",
        "box": "bg-error-container/20",
        "tone": "text-error",
    },
    DifficultySheet.SEVERITY_MODERATE: {
        "label": "Vigilance modérée",
        "badge": "bg-tertiary-fixed text-on-tertiary-fixed",
        "border": "border-outline-variant/40",
        "box": "bg-surface-container-low",
        "tone": "text-tertiary",
    },
    DifficultySheet.SEVERITY_REGULAR: {
        "label": "Suivi régulier",
        "badge": "bg-surface-container text-on-surface-variant",
        "border": "border-outline-variant/40",
        "box": "bg-surface-container-low",
        "tone": "text-on-surface",
    },
}

CATEGORY_META = {
    DifficultySheet.CATEGORY_METHODOLOGY: {
        "label": "Méthodologie", "bar": "bg-primary",
    },
    DifficultySheet.CATEGORY_ATTENDANCE: {
        "label": "Assiduité", "bar": "bg-error",
    },
    DifficultySheet.CATEGORY_WORKLOAD: {
        "label": "Charge de travail", "bar": "bg-tertiary-fixed-dim",
    },
    DifficultySheet.CATEGORY_ORIENTATION: {
        "label": "Orientation", "bar": "bg-secondary",
    },
}

SENTIMENT_META = {
    "confidence": {
        "label": "Confiance", "icon": "lightbulb",
        "badge": "bg-primary-fixed text-primary",
        "circle": "bg-primary-fixed text-primary",
        "border": "border-primary",
        "date": "text-primary",
    },
    "neutral": {
        "label": "Neutre", "icon": "edit_note",
        "badge": "bg-surface-container text-on-surface-variant",
        "circle": "bg-surface-container text-on-surface-variant",
        "border": "border-outline-variant/60",
        "date": "text-on-surface-variant",
    },
    "attention": {
        "label": "Point d'attention", "icon": "water_drop",
        "badge": "bg-error-container text-on-error-container",
        "circle": "bg-error-container text-on-error-container",
        "border": "border-error",
        "date": "text-error",
    },
    "pride": {
        "label": "Fierté", "icon": "verified",
        "badge": "bg-secondary-fixed text-on-secondary-fixed",
        "circle": "bg-secondary-fixed text-on-secondary-fixed",
        "border": "border-secondary",
        "date": "text-secondary",
    },
}

GOAL_STATUS_META = {
    StudentGoal.STATUS_IN_PROGRESS: {
        "label": "En cours", "icon": "sync", "badge": "bg-surface-container text-primary",
        "progress": "bg-primary", "value": "text-primary",
    },
    StudentGoal.STATUS_AT_RISK: {
        "label": "En retard", "icon": "warning", "badge": "bg-error-container text-on-error-container",
        "progress": "bg-error", "value": "text-error",
    },
    StudentGoal.STATUS_ACHIEVED: {
        "label": "Objectif atteint", "icon": "check_circle", "badge": "bg-surface-variant text-primary",
        "progress": "bg-primary", "value": "text-primary",
    },
    StudentGoal.STATUS_ARCHIVED: {
        "label": "Archivé", "icon": "archive", "badge": "bg-surface-container text-on-surface-variant",
        "progress": "bg-outline", "value": "text-outline",
    },
}

SESSION_STATUS_META = {
    StudySession.STATUS_SCHEDULED: {
        "label": "Programmé", "icon": None, "tone": "text-primary",
        "variant": "bg-primary-fixed text-on-primary-fixed",
    },
    StudySession.STATUS_POSTPONED: {
        "label": "Reporté", "icon": "event_repeat", "tone": "text-on-surface-variant",
        "variant": "bg-secondary-fixed text-on-secondary-fixed",
    },
    StudySession.STATUS_COMPLETED: {
        "label": "Complété", "icon": "check", "tone": "text-primary",
        "variant": "bg-tertiary-fixed text-on-tertiary-fixed",
    },
    StudySession.STATUS_CANCELLED: {
        "label": "Annulé", "icon": "close", "tone": "text-outline",
        "variant": "bg-surface-container text-on-surface-variant",
    },
}

SESSION_STATE_META = {
    TutoringSession.STATUS_PENDING: {
        "label": "En attente", "badge": "bg-secondary-fixed text-on-secondary-fixed",
    },
    TutoringSession.STATUS_ACCEPTED: {
        "label": "Confirmé", "badge": "bg-primary-fixed text-primary",
    },
    TutoringSession.STATUS_DECLINED: {
        "label": "Refusé", "badge": "bg-surface-container text-on-surface-variant",
    },
    TutoringSession.STATUS_COMPLETED: {
        "label": "Passé", "badge": "bg-surface-container text-on-surface-variant",
    },
    TutoringSession.STATUS_CANCELLED: {
        "label": "Annulé", "badge": "bg-surface-container text-on-surface-variant",
    },
}

PRIORITY_META = {
    TutoringSession.PRIORITY_HIGH: {
        "label": "Haute", "badge": "bg-error-container text-on-error-container",
        "dot": "bg-error",
    },
    TutoringSession.PRIORITY_NORMAL: {
        "label": "Normale", "badge": "bg-surface-container text-on-surface-variant",
        "dot": "bg-outline",
    },
    TutoringSession.PRIORITY_LOW: {
        "label": "Basse", "badge": "bg-surface-container text-on-surface-variant",
        "dot": "bg-outline",
    },
}

ALERT_META = {
    PerseveranceAlert.TYPE_ATTENDANCE: {
        "icon": "priority_high",
        "circle": "bg-error-container text-on-error-container",
    },
    PerseveranceAlert.TYPE_ENGAGEMENT: {
        "icon": "psychology_alt",
        "circle": "bg-tertiary-fixed text-on-tertiary-fixed",
    },
    PerseveranceAlert.TYPE_GRADE: {
        "icon": "trending_down",
        "circle": "bg-tertiary-fixed text-on-tertiary-fixed",
    },
    PerseveranceAlert.TYPE_CONFIDENCE: {
        "icon": "psychology_alt",
        "circle": "bg-tertiary-fixed text-on-tertiary-fixed",
    },
    PerseveranceAlert.TYPE_SUBMISSION: {
        "icon": "event_busy",
        "circle": "bg-surface-container-high text-on-surface-variant",
    },
}


def academic_year_for(university=None):
    queryset = SchoolClass.objects.all()
    if university is not None:
        queryset = queryset.filter(university=university)
    return (
        queryset.exclude(academic_year="")
        .order_by("-academic_year")
        .values_list("academic_year", flat=True)
        .first()
        or ACADEMIC_YEAR_FALLBACK
    )


def get_student(request):
    membership = getattr(request, "membership", None)
    if membership is None or membership.role != Role.STUDENT:
        return None
    return membership.ensure_profile()


def get_professor(request):
    membership = getattr(request, "membership", None)
    if membership is None or membership.role != Role.PROFESSOR:
        return None
    return membership.ensure_profile()


def display_name(profile):
    user = profile.membership.user
    return user.get_full_name().strip() or user.email.split("@")[0]


def latest_notification_view(student):
    notification = (
        student.tutor_notifications.select_related("professor__membership__user").first()
    )
    if notification is None:
        return None
    return {
        "notification": notification,
        "tutor_name": professor_name(notification.professor) if notification.professor_id else "",
        "when_label": fr_day_time(notification.created_at),
    }


def student_name(student):
    return display_name(student)


def professor_name(professor):
    return display_name(professor)


def person_initials(profile):
    return initials(display_name(profile))


def class_label(student):
    group = (
        student.groups.select_related("school_class")
        .order_by("school_class__name")
        .first()
    )
    return group.school_class.name if group else ""


def student_classes(student):
    classes = {
        group.school_class
        for group in student.groups.select_related("school_class").all()
    }
    classes.update(
        assignment.school_class
        for assignment in student.tutor_assignments.select_related("school_class").filter(
            status=TutorAssignment.STATUS_ACTIVE, school_class__isnull=False,
        )
        if assignment.school_class_id
    )
    return sorted(classes, key=lambda item: item.name)


def active_assignment(student):
    return (
        student.tutor_assignments.filter(status=TutorAssignment.STATUS_ACTIVE)
        .select_related("professor__membership__user", "school_class")
        .order_by("-academic_year")
        .first()
    )


def student_tutors(student):
    tutors = {}
    for assignment in student.tutor_assignments.filter(
        status=TutorAssignment.STATUS_ACTIVE,
    ).select_related("professor__membership__user"):
        tutors[assignment.professor_id] = assignment.professor
    for school_class in student_classes(student):
        for professor in school_class.professors.select_related("membership__user").all():
            tutors[professor.pk] = professor
    return sorted(tutors.values(), key=lambda item: display_name(item))


def waiting_students(school_class, academic_year):
    enrolled = StudentProfile.objects.filter(groups__school_class=school_class).distinct()
    if not enrolled.exists():
        enrolled = StudentProfile.objects.filter(
            tutor_assignments__school_class=school_class,
            tutor_assignments__status=TutorAssignment.STATUS_ACTIVE,
        ).distinct()
    assigned = TutorAssignment.objects.filter(
        student__in=enrolled,
        academic_year=academic_year,
        status=TutorAssignment.STATUS_ACTIVE,
    ).values_list("student_id", flat=True)
    return enrolled.exclude(pk__in=assigned).select_related("membership__user")


def enrolled_count(school_class):
    count = (
        StudentProfile.objects.filter(groups__school_class=school_class)
        .values("pk").distinct().count()
    )
    if count:
        return count
    return (
        TutorAssignment.objects.filter(
            school_class=school_class, status=TutorAssignment.STATUS_ACTIVE,
        ).values("student_id").distinct().count()
    )


def create_assignment(student, professor, school_class, academic_year, assigned_by=None):
    metrics = {
        "average_grade": None,
        "previous_average": None,
        "attendance_rate": 0,
        "assignments_submitted": 0,
        "assignments_total": 0,
    }
    sheet = (
        DifficultySheet.objects.filter(student=student)
        .exclude(status=DifficultySheet.STATUS_CLOSED)
        .order_by("-opened_at")
        .first()
    )
    if sheet is not None:
        metrics.update({
            "average_grade": sheet.average_grade,
            "attendance_rate": sheet.attendance_rate,
            "assignments_submitted": sheet.assignments_submitted,
            "assignments_total": sheet.assignments_total,
        })
    return TutorAssignment.objects.update_or_create(
        student=student,
        academic_year=academic_year,
        status=TutorAssignment.STATUS_ACTIVE,
        defaults={
            "professor": professor,
            "school_class": school_class,
            "university": student.university,
            "assigned_by": assigned_by,
            **metrics,
        },
    )


def assign_students(school_class, professor, limit, academic_year, assigned_by=None):
    created = 0
    for student in waiting_students(school_class, academic_year)[:max(int(limit or 1), 1)]:
        create_assignment(student, professor, school_class, academic_year, assigned_by)
        created += 1
    return created


def auto_assign_class(school_class, academic_year, assigned_by=None):
    professors = list(school_class.professors.all())
    if not professors:
        return 0
    loads = {professor.pk: 0 for professor in professors}
    existing = TutorAssignment.objects.filter(
        school_class=school_class,
        academic_year=academic_year,
        status=TutorAssignment.STATUS_ACTIVE,
    ).values_list("professor_id", flat=True)
    for professor_id in existing:
        if professor_id in loads:
            loads[professor_id] += 1
    created = 0
    for student in waiting_students(school_class, academic_year):
        professor = min(professors, key=lambda item: (loads[item.pk], display_name(item)))
        create_assignment(student, professor, school_class, academic_year, assigned_by)
        loads[professor.pk] += 1
        created += 1
    return created


def allocation_rows(university, academic_year=None):
    classes = list(
        SchoolClass.objects.filter(university=university)
        .prefetch_related("professors__membership__user")
        .order_by("-academic_year", "name")
    )
    year = academic_year or academic_year_for(university)
    classes = [item for item in classes if item.academic_year == year]
    assignments = (
        TutorAssignment.objects.filter(
            university=university,
            academic_year=year,
            status=TutorAssignment.STATUS_ACTIVE,
        )
        .select_related("student", "professor")
    )
    by_class = defaultdict(list)
    for assignment in assignments:
        if assignment.school_class_id:
            by_class[assignment.school_class_id].append(assignment)
    rows = []
    for school_class in classes:
        class_assignments = by_class.get(school_class.pk, [])
        students = enrolled_count(school_class)
        assigned = len({item.student_id for item in class_assignments})
        if not students:
            students = assigned
        tutors = len({item.professor_id for item in class_assignments})
        waiting = max(students - assigned, 0)
        rate = percent(assigned, students) if students else 0
        if not students:
            status, status_class, tags = "Sans étudiants", "bg-surface-container text-on-surface-variant", ""
        elif rate >= 100:
            status, status_class, tags = "Complet", "bg-primary-fixed text-primary", "a_jour"
        elif rate >= 90:
            status, status_class, tags = "À jour", "bg-primary-fixed text-primary", "a_jour"
        else:
            status, status_class, tags = "À compléter", "bg-error-container text-on-error-container", "a_completer"
        rows.append({
            "school_class": school_class,
            "students": students,
            "tutors": tutors,
            "assigned": assigned,
            "waiting": waiting,
            "rate": rate,
            "status": status,
            "status_class": status_class,
            "tags": tags,
        })
    return rows, year


def student_alert_count(student):
    return PerseveranceAlert.objects.filter(
        student=student,
        status__in=(PerseveranceAlert.STATUS_OPEN, PerseveranceAlert.STATUS_TAKEN),
    ).count()


def open_alerts_for_students(student_ids):
    return PerseveranceAlert.objects.filter(
        student_id__in=student_ids,
        status__in=(PerseveranceAlert.STATUS_OPEN, PerseveranceAlert.STATUS_TAKEN),
    )


def next_accepted_session(student):
    return (
        TutoringSession.objects.filter(
            student=student,
            status=TutoringSession.STATUS_ACCEPTED,
            scheduled_at__gte=timezone.now(),
        )
        .select_related("professor__membership__user")
        .order_by("scheduled_at")
        .first()
    )


def next_revision(student):
    return (
        StudySession.objects.filter(
            student=student,
            starts_at__gte=timezone.now(),
            status__in=(StudySession.STATUS_SCHEDULED, StudySession.STATUS_POSTPONED),
        )
        .order_by("starts_at")
        .first()
    )


def next_exam(student):
    return (
        StudySession.objects.filter(
            student=student,
            kind=StudySession.KIND_EXAM,
            starts_at__gte=timezone.now(),
        )
        .exclude(status=StudySession.STATUS_CANCELLED)
        .order_by("starts_at")
        .first()
    )


def week_study_sessions(student):
    start, end = week_bounds()
    return StudySession.objects.filter(
        student=student,
        starts_at__date__range=(start, end),
    ).order_by("starts_at")


def upcoming_slots_for_students(student, limit=12):
    tutors = student_tutors(student)
    return (
        TutoringSlot.objects.filter(
            professor__in=tutors,
            status=TutoringSlot.STATUS_OPEN,
            starts_at__gte=timezone.now(),
        )
        .select_related("professor__membership__user")
        .order_by("starts_at")[:limit]
    )


def professor_upcoming_slots(professor, days=7):
    now = timezone.now()
    return (
        TutoringSlot.objects.filter(
            professor=professor,
            starts_at__gte=now,
            starts_at__lte=now + timedelta(days=days),
        )
        .select_related("school_class")
        .order_by("starts_at")
    )


def professor_week_slots(professor):
    start, end = week_bounds()
    return (
        TutoringSlot.objects.filter(
            professor=professor,
            starts_at__date__range=(start, end),
        )
        .select_related("school_class")
        .prefetch_related("sessions__student__membership__user")
        .order_by("starts_at")
    )


def next_professor_slot(professor):
    return (
        TutoringSlot.objects.filter(
            professor=professor,
            status=TutoringSlot.STATUS_OPEN,
            starts_at__gte=timezone.now(),
        )
        .order_by("starts_at")
        .first()
    )


def caseload(professor):
    return (
        TutorAssignment.objects.filter(
            professor=professor, status=TutorAssignment.STATUS_ACTIVE,
        )
        .select_related("student__membership__user", "school_class")
        .order_by("student__membership__user__last_name", "student__membership__user__first_name")
    )


def assignment_meta(assignment):
    meta = dict(RISK_META.get(assignment.risk_level, RISK_META[TutorAssignment.RISK_LOW]))
    meta["initials"] = person_initials(assignment.student)
    meta["alerts"] = student_alert_count(assignment.student)
    meta["student_name"] = student_name(assignment.student)
    meta["student_number"] = assignment.student.student_number or "—"
    meta["class_name"] = (
        assignment.school_class.name if assignment.school_class_id else class_label(assignment.student)
    )
    meta["delta"] = assignment.delta
    return meta


def risk_breakdown(assignments):
    counts = {TutorAssignment.RISK_HIGH: 0, TutorAssignment.RISK_WATCH: 0, TutorAssignment.RISK_LOW: 0}
    for assignment in assignments:
        counts[assignment.risk_level] = counts.get(assignment.risk_level, 0) + 1
    return counts


def journal_confidence(student, limit=8):
    entries = list(student.journal_entries.all()[:limit])
    return entries


def category_distribution(sheets):
    total = len(sheets)
    distribution = []
    for key, meta in CATEGORY_META.items():
        count = sum(1 for sheet in sheets if sheet.category == key)
        distribution.append({
            "label": meta["label"],
            "bar": meta["bar"],
            "count": count,
            "percent": percent(count, total),
        })
    return distribution


def student_task_counts(student):
    tasks = student.tasks.all()
    total = tasks.count()
    done = tasks.filter(is_done=True).count()
    today = tasks.filter(is_done=False, horizon=StudentTask.HORIZON_TODAY).count()
    week = tasks.filter(is_done=False, horizon=StudentTask.HORIZON_WEEK).count()
    urgent = tasks.filter(is_done=False, priority=StudentTask.PRIORITY_HIGH).count()
    return {
        "total": total,
        "done": done,
        "today": today,
        "week": week,
        "urgent": urgent,
        "progress": percent(done, total),
    }


def student_week_hours(student):
    sessions = list(week_study_sessions(student))
    completed = sum(
        item.duration_minutes for item in sessions
        if item.status == StudySession.STATUS_COMPLETED
    )
    planned = sum(
        item.duration_minutes for item in sessions
        if item.status in (StudySession.STATUS_SCHEDULED, StudySession.STATUS_POSTPONED)
    )
    return completed, planned, sessions


def student_goal_stats(student):
    goals = list(student.goals.all())
    achieved = sum(1 for goal in goals if goal.status == StudentGoal.STATUS_ACHIEVED)
    return {
        "goals": goals,
        "achieved": achieved,
        "total": len(goals),
        "percent": percent(achieved, len(goals)),
        "average_progress": percent(
            sum(goal.progress for goal in goals), len(goals) * 100,
        ) if goals else 0,
    }


def caseload_alerts(assignments):
    student_ids = [item.student_id for item in assignments]
    return open_alerts_for_students(student_ids)


def professor_completed_sessions(professor):
    return TutoringSession.objects.filter(
        professor=professor,
        status=TutoringSession.STATUS_COMPLETED,
    )


def professor_interviews_this_week(professor):
    start, end = week_bounds()
    return TutoringSession.objects.filter(
        Q(professor=professor, status=TutoringSession.STATUS_ACCEPTED, scheduled_at__date__range=(start, end))
        | Q(professor=professor, status=TutoringSession.STATUS_COMPLETED, completed_at__date__range=(start, end))
    ).distinct()


def professor_pending_requests(professor):
    return (
        TutoringSession.objects.filter(professor=professor, status=TutoringSession.STATUS_PENDING)
        .select_related("student__membership__user", "school_class")
        .order_by("-created_at")
    )


def professor_last_completed(professor):
    return (
        TutoringSession.objects.filter(
            professor=professor,
            status=TutoringSession.STATUS_COMPLETED,
        )
        .select_related("student__membership__user", "school_class")
        .order_by("-completed_at", "-scheduled_at")
        .first()
    )


def week_slot_groups(professor):
    groups = []
    current_day = None
    for slot in professor_week_slots(professor):
        day = timezone.localtime(slot.starts_at).date() if timezone.is_aware(slot.starts_at) else slot.starts_at.date()
        if day != current_day:
            groups.append({"date": day, "slots": []})
            current_day = day
        groups[-1]["slots"].append(slot)
    return groups


def admin_monitoring_summary(university, academic_year=None):
    year = academic_year or academic_year_for(university)
    assignments = list(
        TutorAssignment.objects.filter(
            university=university,
            academic_year=year,
            status=TutorAssignment.STATUS_ACTIVE,
        ).select_related("student", "professor", "school_class")
    )
    student_ids = [item.student_id for item in assignments]
    followed = len(set(student_ids))
    high_risk_students = {
        item.student_id for item in assignments if item.risk_level == TutorAssignment.RISK_HIGH
    }
    alerts = PerseveranceAlert.objects.filter(
        university=university,
        status__in=(PerseveranceAlert.STATUS_OPEN, PerseveranceAlert.STATUS_TAKEN),
    ).select_related("student__membership__user", "school_class")
    active_alerts = sum(1 for alert in alerts if alert.status == PerseveranceAlert.STATUS_OPEN)
    high_alerts = sum(
        1 for alert in alerts
        if alert.status == PerseveranceAlert.STATUS_OPEN
        and alert.priority == PerseveranceAlert.PRIORITY_HIGH
    )
    sheets = DifficultySheet.objects.filter(university=university)
    open_sheets = sheets.exclude(status=DifficultySheet.STATUS_CLOSED).count()
    closed_recent = sheets.filter(
        status=DifficultySheet.STATUS_CLOSED,
        closed_at__gte=timezone.now() - timedelta(days=30),
    ).count()
    perseverance_rate = percent(followed - len(high_risk_students), followed) if followed else 0

    cohorts = []
    classes = list(
        SchoolClass.objects.filter(university=university)
        .prefetch_related("professors")
        .order_by("name")
    )
    for school_class in classes:
        class_assignments = [item for item in assignments if item.school_class_id == school_class.pk]
        class_student_ids = {item.student_id for item in class_assignments}
        if not class_student_ids:
            class_student_ids = set(
                StudentProfile.objects.filter(groups__school_class=school_class)
                .values_list("pk", flat=True)
            )
        if not class_student_ids:
            continue
        class_alerts = [
            alert for alert in alerts
            if alert.student_id in class_student_ids or alert.school_class_id == school_class.pk
        ]
        goals = StudentGoal.objects.filter(student_id__in=class_student_ids)
        goal_count = goals.count()
        class_assignments_all = class_assignments or list(
            TutorAssignment.objects.filter(
                student_id__in=class_student_ids,
                academic_year=year,
                status=TutorAssignment.STATUS_ACTIVE,
            )
        )
        grades = [float(item.average_grade) for item in class_assignments_all if item.average_grade is not None]
        attendance = [item.attendance_rate for item in class_assignments_all if item.attendance_rate]
        high = sum(1 for item in class_assignments_all if item.risk_level == TutorAssignment.RISK_HIGH)
        cohorts.append({
            "school_class": school_class,
            "students": len(class_student_ids),
            "alerts": len(class_alerts),
            "high": high,
            "goal_progress": percent(
                sum(goal.progress for goal in goals), goal_count * 100,
            ) if goal_count else 0,
            "attendance": percent(sum(attendance), len(attendance)) if attendance else 0,
            "average": round(sum(grades) / len(grades), 1) if grades else None,
        })

    activities = build_activity_feed(university)
    return {
        "year": year,
        "followed": followed,
        "assignments": assignments,
        "active_alerts": active_alerts,
        "high_alerts": high_alerts,
        "open_sheets": open_sheets,
        "closed_recent": closed_recent,
        "perseverance_rate": perseverance_rate,
        "cohorts": cohorts[:3],
        "alerts": list(alerts.order_by("status", "-detected_at")[:6]),
        "activities": activities,
    }


def build_activity_feed(university, limit=4):
    activities = []
    for alert in PerseveranceAlert.objects.filter(university=university).select_related(
        "student__membership__user",
    ).order_by("-detected_at")[:4]:
        if alert.status == PerseveranceAlert.STATUS_TAKEN and alert.taken_at:
            activities.append({
                "at": alert.taken_at,
                "label": "Alerte prise en charge",
                "text": "%s · %s" % (alert.title, alert.student and student_name(alert.student) or "classe"),
                "tone": "text-primary",
                "dot": "bg-primary",
                "border": "border-primary/30",
            })
        else:
            activities.append({
                "at": alert.detected_at,
                "label": "Alerte détectée",
                "text": "%s · %s" % (alert.title, alert.student and student_name(alert.student) or "classe"),
                "tone": "text-on-surface-variant",
                "dot": "bg-outline-variant",
                "border": "border-outline-variant/40",
            })
    for sheet in DifficultySheet.objects.filter(university=university).select_related(
        "student__membership__user",
    ).order_by("-opened_at")[:4]:
        activities.append({
            "at": sheet.opened_at,
            "label": "Fiche de difficulté ouverte",
            "text": "%s · %s" % (student_name(sheet.student), sheet.get_category_display()),
            "tone": "text-on-surface-variant",
            "dot": "bg-outline-variant",
            "border": "border-outline-variant/40",
        })
    for session in TutoringSession.objects.filter(
        university=university, status=TutoringSession.STATUS_COMPLETED,
    ).select_related("student__membership__user", "professor__membership__user")[:4]:
        activities.append({
            "at": session.completed_at or session.scheduled_at or session.created_at,
            "label": "Entretien réalisé",
            "text": "%s avec %s" % (student_name(session.student), professor_name(session.professor)),
            "tone": "text-on-surface-variant",
            "dot": "bg-outline-variant",
            "border": "border-outline-variant/40",
        })
    activities.sort(key=lambda item: item["at"] or timezone.now(), reverse=True)
    return activities[:limit]
