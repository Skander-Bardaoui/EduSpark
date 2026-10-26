"""Logique partagée entre les portails : classes d'un étudiant, grille
hebdomadaire, prochaine séance, publication des cours et droits d'accès aux
supports."""

from collections import Counter
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from accounts.models import SchoolClass
from accounts.tenancy import Role

from ..models import Course, CoursePublication, ScheduleSlot, TeachingAssignment

WEEKDAY_LABELS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
MONTH_LABELS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def format_minutes(minutes):
    """``210`` -> ``3 h 30`` ; ``45`` -> ``45 min``."""
    minutes = int(minutes or 0)
    hours, rest = divmod(minutes, 60)
    if not hours:
        return "%d min" % rest
    return "%d h %02d" % (hours, rest) if rest else "%d h" % hours


def format_date(day):
    return "%d %s" % (day.day, MONTH_LABELS[day.month - 1])


# ---------------------------------------------------------------------------
# Classes et visibilité côté étudiant
# ---------------------------------------------------------------------------

def student_classes(profile):
    """Classes d'un étudiant : celles des groupes dont il est membre, la plus récente d'abord."""
    if profile is None:
        return SchoolClass.objects.none()
    return (
        SchoolClass.objects.filter(groups__students=profile)
        .select_related("study_program__department")
        .distinct()
        .order_by("-academic_year", "name")
    )


def pick_class(classes, requested):
    """Classe affichée : celle demandée (?classe=) si elle appartient à l'étudiant, sinon la première."""
    classes = list(classes)
    if requested and str(requested).isdigit():
        for school_class in classes:
            if school_class.pk == int(requested):
                return school_class
    return classes[0] if classes else None


def visible_course_ids(school_class):
    """Cours publiés pour une classe (seule porte d'entrée de la visibilité étudiante)."""
    return CoursePublication.objects.filter(
        school_class=school_class, is_published=True,
    ).values("course_id")


def published_courses(school_class):
    return (
        Course.objects.filter(pk__in=visible_course_ids(school_class))
        .select_related("subject__program__department", "professor__membership__user")
    )


def slots_for_student(profile, school_class):
    """Séances de la classe : celles de toute la classe + celles des groupes de l'étudiant."""
    return (
        ScheduleSlot.objects.filter(assignment__school_class=school_class)
        .filter(Q(group__isnull=True) | Q(group__students=profile))
        .select_related(
            "assignment__school_class", "assignment__subject",
            "assignment__professor__membership__user", "group",
        )
        .distinct()
    )


# ---------------------------------------------------------------------------
# Emploi du temps
# ---------------------------------------------------------------------------

def build_week_grid(slots, today=None):
    """Organise des séances en colonnes de jours (lundi → vendredi, samedi si besoin)."""
    today = today or timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    slots = list(slots)
    show_saturday = any(slot.weekday == 5 for slot in slots)
    days = []
    for index in range(6 if show_saturday else 5):
        day = monday + timedelta(days=index)
        day_slots = sorted(
            (slot for slot in slots if slot.weekday == index),
            key=lambda slot: (slot.start_time, slot.end_time, slot.pk),
        )
        days.append({
            "index": index,
            "label": WEEKDAY_LABELS[index],
            "date": day,
            "date_label": format_date(day),
            "is_today": day == today,
            "slots": day_slots,
        })
    total = sum(slot.duration_minutes for slot in slots)
    last_day = monday + timedelta(days=len(days) - 1)
    return {
        "days": days,
        "slot_count": len(slots),
        "total_minutes": total,
        "total_label": format_minutes(total),
        "show_saturday": show_saturday,
        "week_label": "Semaine du %s au %s %d" % (format_date(monday), format_date(last_day), last_day.year),
    }


def next_session(slots, now=None):
    """Séance en cours ou prochaine séance (récurrence hebdomadaire)."""
    now = now or timezone.localtime()
    best = None
    for slot in slots:
        day = now.date() + timedelta(days=(slot.weekday - now.weekday()) % 7)
        start = timezone.make_aware(datetime.combine(day, slot.start_time))
        end = timezone.make_aware(datetime.combine(day, slot.end_time))
        if end <= now:
            start += timedelta(days=7)
            end += timedelta(days=7)
        if best is None or start < best["start"]:
            best = {"slot": slot, "start": start, "end": end}
    if best is None:
        return None
    best["ongoing"] = best["start"] <= now < best["end"]
    delta_days = (best["start"].date() - now.date()).days
    if best["ongoing"]:
        best["when"] = "En cours"
    elif delta_days == 0:
        best["when"] = "Aujourd'hui à %s" % best["start"].strftime("%H:%M")
    elif delta_days == 1:
        best["when"] = "Demain à %s" % best["start"].strftime("%H:%M")
    else:
        best["when"] = "%s à %s" % (WEEKDAY_LABELS[best["start"].weekday()], best["start"].strftime("%H:%M"))
    return best


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

def teaches(professor, subject, school_class):
    return TeachingAssignment.objects.filter(
        professor=professor, subject=subject, school_class=school_class,
    ).exists()


def set_publication(course, school_class, published):
    """Publie ou retire un cours pour une classe où son auteur enseigne la matière."""
    if not teaches(course.professor, course.subject, school_class):
        raise ValidationError(
            "Vous n'enseignez pas cette matière à la classe « %s » : le cours ne peut pas y être publié."
            % school_class.name
        )
    publication, _created = CoursePublication.objects.get_or_create(
        course=course, school_class=school_class, defaults={"university": course.university},
    )
    publication.is_published = published
    publication.published_at = timezone.now() if published else None
    publication.save(update_fields=["is_published", "published_at"])
    return publication


# ---------------------------------------------------------------------------
# Droits d'accès aux supports
# ---------------------------------------------------------------------------

def can_access_material(user, material):
    """Qui peut lire un support : l'auteur du cours, l'admin de l'université et
    les étudiants des classes pour lesquelles le cours est publié."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    course = material.course
    membership = user.memberships.filter(
        university_id=course.university_id, is_active=True, university__is_active=True,
    ).first()
    if membership is None:
        return False
    if membership.role == Role.UNIVERSITY_ADMIN:
        return True
    if membership.role == Role.PROFESSOR:
        return course.professor.membership_id == membership.pk
    if membership.role == Role.STUDENT:
        return CoursePublication.objects.filter(
            course=course, is_published=True,
            school_class__groups__students__membership=membership,
        ).exists()
    return False


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def describe_blockers(error):
    """Résumé lisible des objets qui empêchent une suppression.

    ``error`` est une ``ProtectedError`` ou une ``RestrictedError`` (cette dernière
    refuse la suppression directe d'un objet encore référencé mais laisse passer
    une suppression en cascade, par exemple celle d'une université entière).
    """
    blockers = getattr(error, "protected_objects", None) or getattr(error, "restricted_objects", ())
    counts = Counter(obj._meta.verbose_name_plural.lower() for obj in blockers)
    return ", ".join("%d %s" % (count, label) for label, count in counts.items())
