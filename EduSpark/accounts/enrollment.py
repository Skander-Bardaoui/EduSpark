"""Affectation automatique d'un étudiant à une classe selon son niveau et sa section.

La classe d'un étudiant est matérialisée par son appartenance à un groupe de
cette classe (``StudentGroup``). Un groupe « Groupe principal » est créé à la
demande pour recevoir les étudiants validés par l'administration.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import MAX_STUDENTS_PER_CLASS, Membership, SchoolClass, StudentGroup
from .tenancy import Role

DEFAULT_GROUP_NAME = "Groupe principal"


def class_student_count(school_class):
    return school_class.student_queryset().count()


def _available_class(profile, school_class=None):
    if school_class is not None:
        return school_class
    level = (profile.level or "").strip()
    section = (profile.section or "").strip()
    if not level:
        raise ValidationError(
            "Renseignez le niveau de l'étudiant avant de valider son inscription."
        )
    classes = (
        SchoolClass.objects.filter(
            university_id=profile.university_id,
            level__iexact=level,
            section__iexact=section,
        )
        .order_by("-academic_year", "name")
    )
    if not classes.exists() and section:
        # Les classes historiques n'ont pas toujours de section : on accepte
        # alors la classe du même niveau sans section comme solution de repli.
        classes = (
            SchoolClass.objects.filter(
                university_id=profile.university_id,
                level__iexact=level,
                section="",
            )
            .order_by("-academic_year", "name")
        )
    for candidate in classes:
        if class_student_count(candidate) < MAX_STUDENTS_PER_CLASS:
            return candidate
    raise ValidationError(
        "Aucune classe « %s — section %s » n'a de place disponible (maximum %d étudiants). "
        "Créez ou libérez une classe correspondante."
        % (level, section or "—", MAX_STUDENTS_PER_CLASS)
    )


def _group_for_enrollment(school_class):
    group = school_class.groups.filter(name=DEFAULT_GROUP_NAME).first()
    if group is None:
        group = StudentGroup.objects.create(
            university_id=school_class.university_id,
            school_class=school_class,
            name=DEFAULT_GROUP_NAME,
            capacity=MAX_STUDENTS_PER_CLASS,
        )
    return group


@transaction.atomic
def assign_student_to_class(profile, school_class=None):
    """Affecte ``profile`` à une classe et renvoie la classe retenue.

    - un étudiant déjà affecté à une classe y reste ;
    - sinon la classe est choisie par niveau + section, avec une place libre ;
    - l'effectif de la classe ne peut jamais dépasser 30 étudiants.
    """
    existing = profile.groups.select_related("school_class").first()
    if existing is not None:
        if school_class is not None and existing.school_class_id != school_class.pk:
            raise ValidationError(
                "Cet étudiant appartient déjà à la classe « %s »."
                % existing.school_class.name
            )
        return existing.school_class

    target = _available_class(profile, school_class)
    if class_student_count(target) >= MAX_STUDENTS_PER_CLASS:
        raise ValidationError(
            "La classe « %s » est complète (%d étudiants maximum)."
            % (target.name, MAX_STUDENTS_PER_CLASS)
        )
    group = _group_for_enrollment(target)
    group.students.add(profile)
    if not profile.program and target.program:
        profile.program = target.program
        profile.save(update_fields=["program"])
    return target


def pending_students_by_level(university):
    """Inscriptions étudiantes en attente, regroupées par niveau choisi."""
    memberships = (
        Membership.objects.filter(
            university=university,
            role=Role.STUDENT,
            is_active=False,
        )
        .select_related("user", "student_profile")
        .order_by("student_profile__level", "student_profile__section", "created_at")
    )
    groups = {}
    for membership in memberships:
        profile = getattr(membership, "student_profile", None)
        level = (profile.level or "").strip() if profile else ""
        section = (profile.section or "").strip() if profile else ""
        row = {
            "membership": membership,
            "profile": profile,
            "level": level or "Niveau non renseigné",
            "section": section,
        }
        groups.setdefault(row["level"], []).append(row)
    return [
        {"level": level, "students": rows}
        for level, rows in sorted(groups.items(), key=lambda item: item[0])
    ]
