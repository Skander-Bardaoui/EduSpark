"""Règles d'accès du module examens, alignées sur les affectations d'enseignement."""

from accounts.models import SchoolClass
from courses.models import Course, TeachingAssignment


def professor_classes(professor, university):
    """Classes où le professeur a au moins une affectation d'enseignement."""
    if professor is None:
        return SchoolClass.objects.none()
    return (
        SchoolClass.objects.filter(
            university=university,
            teaching_assignments__professor=professor,
        )
        .distinct()
        .order_by("-academic_year", "name")
    )


def professor_teaches(professor, session):
    """Le professeur est-il affecté à la matière et à la classe de la session ?"""
    return bool(
        professor is not None
        and session.course_subject_id
        and TeachingAssignment.objects.filter(
            professor=professor,
            subject_id=session.course_subject_id,
            school_class_id=session.school_class_id,
        ).exists()
    )


def professor_courses(professor, session):
    """Cours du professeur publiés pour la classe de la session."""
    if not professor_teaches(professor, session):
        return Course.objects.none()
    return (
        Course.objects.filter(
            university=session.university_id,
            professor=professor,
            subject_id=session.course_subject_id,
            publications__school_class_id=session.school_class_id,
        )
        .distinct()
        .order_by("title")
    )


def student_classes(student, university):
    """Classes de l'étudiant, via ses groupes."""
    if student is None:
        return SchoolClass.objects.none()
    return (
        SchoolClass.objects.filter(
            university=university,
            groups__students=student,
        )
        .distinct()
        .order_by("-academic_year", "name")
    )
