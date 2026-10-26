"""Calculs et référentiels partagés du module Suivi Référent."""

from collections import defaultdict
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import ProfessorProfile, SchoolClass, StudentProfile
from accounts.tenancy import Role
from courses.models import ScheduleSlot

from .models import (
    AttendanceRecord,
    AttendanceSession,
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

TUTORING_WEEKDAY_TIMES = (
    "18:00", "18:30", "19:00", "19:30", "20:00", "20:30",
)
TUTORING_SATURDAY_TIMES = (
    "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30",
)
TUTORING_TIME_CHOICES = TUTORING_WEEKDAY_TIMES + TUTORING_SATURDAY_TIMES
TUTORING_WINDOW_HINT = (
    "En semaine de 18:00 à 21:00, le samedi de 09:00 à 13:00. "
    "Le dimanche est fermé."
)


def tutoring_window_error(start, end):
    """Vérifie que le rendez-vous a lieu hors des heures de cours."""
    local_start = timezone.localtime(start)
    local_end = timezone.localtime(end)
    if local_start.weekday() == 6:
        return "Le tutorat n'est pas proposé le dimanche."
    if local_end.date() != local_start.date():
        return "Le rendez-vous doit se terminer le même jour."
    if local_start.weekday() == 5:
        open_minutes, close_minutes = 9 * 60, 13 * 60
    else:
        open_minutes, close_minutes = 18 * 60, 21 * 60
    start_minutes = local_start.hour * 60 + local_start.minute
    end_minutes = local_end.hour * 60 + local_end.minute
    if start_minutes < open_minutes or end_minutes > close_minutes:
        return (
            "Les rendez-vous de tutorat ont lieu en dehors des heures de cours : "
            "en semaine de 18:00 à 21:00, le samedi de 09:00 à 13:00. "
            "Le dimanche est fermé."
        )
    return None


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


def enrolled_students(school_class):
    students = StudentProfile.objects.filter(
        groups__school_class=school_class,
    ).distinct()
    if not students.exists():
        students = StudentProfile.objects.filter(
            tutor_assignments__school_class=school_class,
            tutor_assignments__status=TutorAssignment.STATUS_ACTIVE,
        ).distinct()
    return students


def class_tutoring_students(school_class, academic_year):
    """Étudiants réellement rattachés à la classe pour le tutorat.

    La population réunit les étudiants des groupes de la classe et ceux qui
    possèdent déjà une affectation active sur cette classe pour l'année.
    """
    return (
        StudentProfile.objects.filter(
            Q(groups__school_class=school_class)
            | Q(
                tutor_assignments__school_class=school_class,
                tutor_assignments__academic_year=academic_year,
                tutor_assignments__status=TutorAssignment.STATUS_ACTIVE,
            )
        )
        .distinct()
        .select_related("membership__user")
    )


def waiting_students(school_class, academic_year):
    enrolled = enrolled_students(school_class)
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


def attendance_metrics(student):
    """Taux d'assiduité calculé à partir des présences réellement saisies.

    Les retards comptent comme une présence. Les absences justifiées sont
    exclues du calcul (elles ne pénalisent pas l'étudiant). Les séances
    annulées ne sont jamais comptabilisées; une séance sans relevé non plus.
    """
    records = AttendanceRecord.objects.filter(student=student).exclude(
        session__status=AttendanceSession.STATUS_CANCELLED,
    )
    stats = records.aggregate(
        attended=Count(
            "pk", filter=Q(status__in=AttendanceRecord.ATTENDED_STATUSES),
        ),
        counted=Count(
            "pk", filter=Q(status__in=AttendanceRecord.COUNTED_STATUSES),
        ),
        absent=Count(
            "pk", filter=Q(status=AttendanceRecord.STATUS_ABSENT),
        ),
        excused=Count(
            "pk", filter=Q(status=AttendanceRecord.STATUS_EXCUSED),
        ),
        total=Count("pk"),
    )
    stats["rate"] = percent(stats["attended"], stats["counted"]) if stats["counted"] else None
    return stats


def sync_student_attendance(student):
    """Propage le taux calculé vers les tutorats et fiches encore ouverts."""
    rate = attendance_metrics(student)["rate"] or 0
    for assignment in TutorAssignment.objects.filter(
        student=student, status=TutorAssignment.STATUS_ACTIVE,
    ):
        if assignment.attendance_rate != rate:
            assignment.attendance_rate = rate
            assignment.save(update_fields=["attendance_rate", "updated_at"])
    for sheet in DifficultySheet.objects.filter(student=student).exclude(
        status=DifficultySheet.STATUS_CLOSED,
    ):
        if sheet.attendance_rate != rate:
            sheet.attendance_rate = rate
            sheet.save(update_fields=["attendance_rate", "updated_at"])
    return rate


def ensure_attendance_alert(student):
    """Ouvre une alerte de persévérance quand l'assiduité passe sous 75 %.

    Idempotent : une seule alerte ouverte par étudiant et par type. Retourne
    l'alerte créée, ou ``None`` si aucune alerte n'était nécessaire.
    """
    rate = attendance_metrics(student)["rate"]
    if rate is None or rate >= 75:
        return None
    assignment = active_assignment(student)
    alert, created = PerseveranceAlert.objects.get_or_create(
        student=student,
        alert_type=PerseveranceAlert.TYPE_ATTENDANCE,
        status=PerseveranceAlert.STATUS_OPEN,
        defaults={
            "university": student.university,
            "school_class": assignment.school_class if assignment else None,
            "title": "Assiduité faible · %s" % student_name(student),
            "detail": (
                "Le taux de présence est descendu à %d %% après le dernier relevé. "
                "Un contact avec le référent pédagogique est recommandé." % rate
            ),
            "priority": (
                PerseveranceAlert.PRIORITY_HIGH if rate < 60
                else PerseveranceAlert.PRIORITY_NORMAL
            ),
            "detected_at": timezone.now(),
        },
    )
    return alert if created else None


def attendance_session_students(session):
    """Étudiants concernés par une séance (groupe si défini, sinon classe)."""
    qs = StudentProfile.objects.filter(groups__school_class=session.school_class)
    if session.student_group_id:
        qs = qs.filter(groups=session.student_group)
    qs = qs.distinct().select_related("membership__user")
    if qs.exists():
        return qs.order_by(
            "membership__user__last_name", "membership__user__first_name",
        )
    return StudentProfile.objects.filter(
        tutor_assignments__school_class=session.school_class,
        tutor_assignments__status=TutorAssignment.STATUS_ACTIVE,
    ).distinct().select_related("membership__user").order_by(
        "membership__user__last_name", "membership__user__first_name",
    )


def attendance_occurrence_start(slot, session_date):
    """Début réel d'une occurrence hebdomadaire de l'emploi du temps."""
    return timezone.make_aware(datetime.combine(session_date, slot.start_time))


def attendance_occurrence_end(slot, session_date):
    """Fin réelle d'une occurrence hebdomadaire de l'emploi du temps."""
    return timezone.make_aware(datetime.combine(session_date, slot.end_time))


def _attendance_occurrence_row(slot, session_date, session=None):
    records = list(session.records.all()) if session is not None else []
    has_record = bool(records)
    starts_at = attendance_occurrence_start(slot, session_date)
    is_upcoming = starts_at > timezone.now()
    if session is not None and session.status == AttendanceSession.STATUS_CANCELLED:
        status = AttendanceSession.STATUS_CANCELLED
        status_label = session.get_status_display()
    elif has_record:
        status = AttendanceSession.STATUS_COMPLETED
        status_label = "Relevé"
    elif is_upcoming:
        status = "upcoming"
        status_label = "À venir"
    else:
        status = "todo"
        status_label = "À saisir"
    return {
        "slot": slot,
        "date": session_date,
        "starts_at": starts_at,
        "ends_at": attendance_occurrence_end(slot, session_date),
        "session": session,
        "has_record": has_record,
        "attended": sum(
            1 for record in records
            if record.status in AttendanceRecord.ATTENDED_STATUSES
        ),
        "recorded": sum(
            1 for record in records
            if record.status in AttendanceRecord.COUNTED_STATUSES
        ),
        "status": status,
        "status_label": status_label,
        "is_todo": status == "todo",
        "is_upcoming": status == "upcoming",
    }


def attendance_occurrences(professor, start_date, end_date):
    """Occurrences réelles des séances d'emploi du temps d'un professeur.

    Chaque séance hebdomadaire est projetée sur les dates demandées. La
    ``AttendanceSession`` correspondante n'est créée qu'à l'ouverture du
    relevé : tant qu'elle n'existe pas, l'occurrence reste « à saisir ».
    """
    if start_date > end_date:
        return []
    slots = (
        ScheduleSlot.objects.filter(
            university=professor.university, assignment__professor=professor,
        )
        .select_related(
            "assignment__school_class", "assignment__subject",
            "assignment__professor__membership__user", "group",
        )
    )
    existing = {
        (session.slot_id, session.session_date): session
        for session in AttendanceSession.objects.filter(
            professor=professor,
            slot__isnull=False,
            session_date__gte=start_date,
            session_date__lte=end_date,
        )
        .select_related("school_class", "student_group")
        .prefetch_related("records")
    }
    rows = []
    for slot in slots:
        offset = (slot.weekday - start_date.weekday()) % 7
        day = start_date + timedelta(days=offset)
        while day <= end_date:
            session = existing.get((slot.pk, day))
            rows.append(_attendance_occurrence_row(slot, day, session))
            day += timedelta(days=7)
    rows.sort(key=lambda row: (row["starts_at"], row["slot"].pk))
    return rows


def get_or_create_slot_session(professor, slot, session_date, created_by=None):
    """Ouvre le relevé d'une occurrence précise de l'emploi du temps."""
    if slot.assignment.professor_id != professor.pk:
        raise ValidationError("Cette séance de l'emploi du temps ne vous est pas affectée.")
    if session_date.weekday() != slot.weekday:
        raise ValidationError(
            "Cette date ne correspond pas au jour de la séance dans l'emploi du temps."
        )
    session, created = AttendanceSession.objects.get_or_create(
        slot=slot,
        session_date=session_date,
        defaults={
            "university": slot.university,
            "professor": professor,
            "school_class": slot.assignment.school_class,
            "student_group": slot.group,
            "title": slot.assignment.subject.name,
            "kind": slot.session_type,
            "starts_at": attendance_occurrence_start(slot, session_date),
            "duration_minutes": slot.duration_minutes,
            "created_by": created_by,
        },
    )
    return session, created


def attendance_pending_count(professor, start_date=None, end_date=None):
    """Occurrences de la période encore sans relevé, plus les séances libres."""
    start_date = start_date or timezone.localdate()
    end_date = end_date or start_date
    count = sum(
        1 for row in attendance_occurrences(professor, start_date, end_date)
        if row["is_todo"]
    )
    count += (
        AttendanceSession.objects.filter(
            professor=professor,
            university=professor.university,
            slot__isnull=True,
            starts_at__date__gte=start_date,
            starts_at__date__lte=end_date,
        )
        .exclude(status=AttendanceSession.STATUS_CANCELLED)
        .annotate(record_count=Count("records"))
        .filter(record_count=0)
        .count()
    )
    return count


def create_assignment(student, professor, school_class, academic_year, assigned_by=None):
    metrics = {
        "average_grade": None,
        "previous_average": None,
        "attendance_rate": attendance_metrics(student)["rate"] or 0,
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
            "attendance_rate": metrics["attendance_rate"] or sheet.attendance_rate,
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


def assign_class_referent(school_class, professor, academic_year, assigned_by=None):
    """Affecte un référent unique à toute la population de la classe.

    Retourne uniquement les étudiants dont le référent a réellement changé,
    afin de ne pas renvoyer de notifications inutiles.
    """
    changed = []
    for student in class_tutoring_students(school_class, academic_year):
        current = TutorAssignment.objects.filter(
            student=student,
            academic_year=academic_year,
            status=TutorAssignment.STATUS_ACTIVE,
        ).first()
        if (
            current is not None
            and current.professor_id == professor.pk
            and current.school_class_id == school_class.pk
        ):
            continue
        create_assignment(student, professor, school_class, academic_year, assigned_by)
        changed.append(student)
    return changed


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
        .select_related("student", "professor__membership__user")
    )
    by_class = defaultdict(list)
    for assignment in assignments:
        if assignment.school_class_id:
            by_class[assignment.school_class_id].append(assignment)
    rows = []
    for school_class in classes:
        class_assignments = by_class.get(school_class.pk, [])
        roster = list(class_tutoring_students(school_class, year))
        student_ids = {student.pk for student in roster}
        class_assignments = [
            item for item in class_assignments if item.student_id in student_ids
        ]
        students = len(student_ids)
        assigned = len({item.student_id for item in class_assignments})
        group_count = enrolled_count(school_class)
        outside_group = max(students - group_count, 0)
        tutors = len({item.professor_id for item in class_assignments})
        referent_names = sorted({
            display_name(item.professor) for item in class_assignments
        })
        waiting = max(students - assigned, 0)
        rate = min(percent(assigned, students), 100) if students else 0
        if not students:
            status, status_class, tags = (
                "Sans étudiants", "bg-surface-container text-on-surface-variant", "",
            )
        elif tutors > 1:
            status, status_class, tags = (
                "Référents multiples",
                "bg-error-container text-on-error-container",
                "a_completer",
            )
        elif waiting > 0:
            status, status_class, tags = (
                "À compléter",
                "bg-error-container text-on-error-container",
                "a_completer",
            )
        else:
            status, status_class, tags = (
                "Complet", "bg-primary-fixed text-primary", "a_jour",
            )
        rows.append({
            "school_class": school_class,
            "students": students,
            "outside_group": outside_group,
            "tutors": tutors,
            "referent_names": referent_names,
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
        .select_related("professor__membership__user", "slot")
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
    ordered_alerts = list(alerts.order_by("status", "-detected_at"))
    active_alerts = sum(
        1 for alert in ordered_alerts if alert.status == PerseveranceAlert.STATUS_OPEN
    )
    taken_alerts = sum(
        1 for alert in ordered_alerts if alert.status == PerseveranceAlert.STATUS_TAKEN
    )
    high_alerts = sum(
        1 for alert in ordered_alerts
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
        attendance = []
        for item in class_assignments_all:
            rate = attendance_metrics(item.student)["rate"]
            if rate is not None:
                attendance.append(rate)
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
        "taken_alerts": taken_alerts,
        "high_alerts": high_alerts,
        "open_sheets": open_sheets,
        "closed_recent": closed_recent,
        "perseverance_rate": perseverance_rate,
        "cohorts": cohorts[:3],
        "alerts": ordered_alerts[:6],
        "all_alerts": ordered_alerts,
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
