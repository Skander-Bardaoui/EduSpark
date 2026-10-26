"""Fixtures communes aux tests du module cours.

Deux universités ; dans « Université Test » : un admin, deux professeurs, trois
étudiants (deux dans des groupes de la classe L3, un sans groupe), un
département, deux filières, des matières, deux classes et leurs affectations.
"""

import shutil
import tempfile
from datetime import time

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, SchoolClass, StudentGroup, University
from accounts.tenancy import Role
from courses.models import (
    Course, CoursePublication, Department, Program, ScheduleSlot, Subject, TeachingAssignment,
)

PASSWORD = "Pass12345!"
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def make_user(email, first_name="", last_name=""):
    return User.objects.create_user(
        username=email, email=email, password=PASSWORD,
        first_name=first_name, last_name=last_name,
    )


def join(user, university, role, **profile):
    """Rattache un compte à une université et retourne l'appartenance."""
    membership = Membership.objects.create(
        user=user, university=university, role=role, is_active=True,
    )
    obj = membership.ensure_profile()
    if obj is not None and profile:
        for name, value in profile.items():
            setattr(obj, name, value)
        obj.save()
    return membership


def pdf_upload(name="support.pdf", content=PDF_BYTES):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def make_slot(assignment, weekday=0, start="08:30", end="10:00", **extra):
    """Séance créée directement (sans passer par la validation des conflits)."""
    return ScheduleSlot.objects.create(
        assignment=assignment, weekday=weekday,
        start_time=time.fromisoformat(start), end_time=time.fromisoformat(end), **extra,
    )


class ProtectedMediaMixin:
    """Les supports sont écrits dans un dossier jetable, jamais dans protected_media/."""

    @classmethod
    def setUpClass(cls):
        cls._protected_dir = tempfile.mkdtemp(prefix="eduspark-protected-")
        cls._protected_override = override_settings(PROTECTED_MEDIA_ROOT=cls._protected_dir)
        cls._protected_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._protected_override.disable()
        shutil.rmtree(cls._protected_dir, ignore_errors=True)


class CoursesTestCase(ProtectedMediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.univ = University.objects.create(name="Université Test", code="UT")
        cls.other_univ = University.objects.create(name="Université Voisine", code="UV")

        cls.admin = make_user("admin@ut.test", "Sophie", "Bernard")
        join(cls.admin, cls.univ, Role.UNIVERSITY_ADMIN)
        cls.other_admin = make_user("admin@uv.test", "Julien", "Morel")
        join(cls.other_admin, cls.other_univ, Role.UNIVERSITY_ADMIN)
        cls.platform = User.objects.create_superuser(
            username="platform@ut.test", email="platform@ut.test", password=PASSWORD,
        )

        cls.prof_user = make_user("prof@ut.test", "Hélène", "Vasseur")
        cls.prof = join(cls.prof_user, cls.univ, Role.PROFESSOR, department="Informatique").professor_profile
        cls.prof2_user = make_user("prof2@ut.test", "Mariam", "Traoré")
        cls.prof2 = join(cls.prof2_user, cls.univ, Role.PROFESSOR, department="Informatique").professor_profile
        cls.other_prof_user = make_user("prof@uv.test", "Marc", "Lyon")
        cls.other_prof = join(cls.other_prof_user, cls.other_univ, Role.PROFESSOR).professor_profile

        cls.student_user = make_user("camille@ut.test", "Camille", "Martin")
        cls.student = join(cls.student_user, cls.univ, Role.STUDENT, student_number="UT-001").student_profile
        cls.student2_user = make_user("ines@ut.test", "Inès", "Bernard")
        cls.student2 = join(cls.student2_user, cls.univ, Role.STUDENT, student_number="UT-002").student_profile
        cls.student3_user = make_user("yanis@ut.test", "Yanis", "Leroy")
        cls.student3 = join(cls.student3_user, cls.univ, Role.STUDENT, student_number="UT-003").student_profile
        cls.other_student_user = make_user("lucas@uv.test", "Lucas", "Moreau")
        cls.other_student = join(cls.other_student_user, cls.other_univ, Role.STUDENT).student_profile

        cls.dept = Department.objects.create(university=cls.univ, name="Informatique", code="INFO")
        cls.program = Program.objects.create(
            department=cls.dept, name="Licence Informatique", code="LIC-INFO", duration_years=3,
        )
        cls.program_gl = Program.objects.create(
            department=cls.dept, name="Master Génie Logiciel", code="MST-GL",
            degree="master", duration_years=2,
        )
        cls.subject = Subject.objects.create(
            program=cls.program, name="Algorithmique avancée", code="INF501", semester=5,
            coefficient=3, credits=6, hours_cm=21, hours_td=21, hours_tp=12,
        )
        cls.subject2 = Subject.objects.create(
            program=cls.program, name="Bases de données", code="INF504", semester=5,
            coefficient=2, credits=4, hours_cm=14, hours_td=7, hours_tp=14,
        )
        cls.subject_gl = Subject.objects.create(
            program=cls.program_gl, name="Architecture applicative", code="GEN401", semester=1,
        )

        cls.school_class = SchoolClass.objects.create(
            university=cls.univ, name="Licence 3 Informatique", level="3e année",
            academic_year="2025-2026", study_program=cls.program,
        )
        cls.class_gl = SchoolClass.objects.create(
            university=cls.univ, name="Master 1 Génie Logiciel", level="Master 1",
            academic_year="2025-2026", study_program=cls.program_gl,
        )
        cls.group_td = StudentGroup.objects.create(school_class=cls.school_class, name="TD A")
        cls.group_td.students.add(cls.student)
        cls.group_tp = StudentGroup.objects.create(school_class=cls.school_class, name="TP B")
        cls.group_tp.students.add(cls.student2)

        cls.assign = TeachingAssignment.objects.create(
            school_class=cls.school_class, subject=cls.subject, professor=cls.prof,
        )
        cls.assign2 = TeachingAssignment.objects.create(
            school_class=cls.school_class, subject=cls.subject2, professor=cls.prof2,
        )
        cls.assign_gl = TeachingAssignment.objects.create(
            school_class=cls.class_gl, subject=cls.subject_gl, professor=cls.prof,
        )

        # Une université voisine complète, pour vérifier l'isolation.
        cls.other_dept = Department.objects.create(university=cls.other_univ, name="Mathématiques")
        cls.other_program = Program.objects.create(department=cls.other_dept, name="Licence Maths")
        cls.other_subject = Subject.objects.create(
            program=cls.other_program, name="Analyse", code="MAT101", semester=1,
        )
        cls.other_class = SchoolClass.objects.create(
            university=cls.other_univ, name="L1 Maths", academic_year="2025-2026",
            study_program=cls.other_program,
        )
        cls.other_assign = TeachingAssignment.objects.create(
            school_class=cls.other_class, subject=cls.other_subject, professor=cls.other_prof,
        )

    # -- aides ----------------------------------------------------------------
    def login(self, user):
        self.client.force_login(user)

    def make_course(self, professor=None, subject=None, title="Cours d'algorithmique", **extra):
        return Course.objects.create(
            professor=professor or self.prof, subject=subject or self.subject, title=title, **extra,
        )

    def publish(self, course, school_class=None, published=True):
        return CoursePublication.objects.update_or_create(
            course=course, school_class=school_class or self.school_class,
            defaults={
                "university": course.university, "is_published": published,
                "published_at": timezone.now() if published else None,
            },
        )[0]
