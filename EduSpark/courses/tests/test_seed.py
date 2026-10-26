"""Jeu de données de démonstration : cohérence, idempotence et flux complet."""

from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import SchoolClass, University
from accounts.tenancy import SESSION_KEY
from courses.models import (
    Chapter, Course, CourseMaterial, CoursePublication, Department, Program, ScheduleSlot,
    Subject, TeachingAssignment,
)

from .base import ProtectedMediaMixin


def seed():
    call_command("seed_courses", stdout=StringIO())


def snapshot():
    return tuple(
        model.objects.count() for model in (
            User, Department, Program, Subject, TeachingAssignment, ScheduleSlot, Course, Chapter,
            CourseMaterial, CoursePublication,
        )
    )


@override_settings(DEBUG=True)
class SeedCoursesTests(ProtectedMediaMixin, TestCase):
    def login(self, email, university=None):
        client = Client()
        client.force_login(User.objects.get(email=email))
        if university is not None:  # un professeur de plusieurs universités choisit celle où il travaille
            session = client.session
            session[SESSION_KEY] = University.objects.get(name=university).pk
            session.save()
        return client

    def test_seed_is_idempotent(self):
        seed()
        first = snapshot()
        self.assertTrue(all(count > 0 for count in first))
        seed()
        self.assertEqual(snapshot(), first)

    def test_seed_refuses_to_run_without_debug_unless_forced(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command("seed_courses", stdout=StringIO())
            call_command("seed_courses", force=True, stdout=StringIO())
        self.assertTrue(Course.objects.exists())

    def test_demo_timetable_has_no_conflict(self):
        seed()
        for slot in ScheduleSlot.objects.select_related("assignment__school_class"):
            with self.subTest(slot=str(slot)):
                self.assertEqual(slot.find_conflicts(), [])
                slot.full_clean(exclude=["university"])

    def test_demo_data_respects_the_business_rules(self):
        seed()
        for course in Course.objects.all():
            with self.subTest(course=course.title):
                course.full_clean(exclude=["university"])
        for publication in CoursePublication.objects.filter(is_published=True):
            with self.subTest(publication=str(publication)):
                publication.clean()
        for assignment in TeachingAssignment.objects.all():
            with self.subTest(assignment=str(assignment)):
                assignment.full_clean(exclude=["university"])
                self.assertIn(assignment.professor, assignment.school_class.professors.all())
        for school_class in SchoolClass.objects.exclude(study_program=None):
            self.assertEqual(school_class.program, school_class.study_program.name)

    def test_seed_survives_a_second_run_of_seed_demo(self):
        seed()
        call_command("seed_demo", force=True, stdout=StringIO(), verbosity=0)  # réinitialise l'encadrement des classes
        seed()
        for assignment in TeachingAssignment.objects.all():
            self.assertIn(assignment.professor, assignment.school_class.professors.all())

    def test_student_sees_published_courses_and_his_own_timetable(self):
        seed()
        client = self.login("test.ui@example.com")  # Camille, groupe TD A de la L3
        catalogue = client.get(reverse("courses:student_catalogue"))
        self.assertContains(catalogue, "Algorithmique avancée — Graphes et complexité")
        self.assertContains(catalogue, "Bases de données relationnelles")
        self.assertContains(catalogue, "Travaux pratiques d&#x27;algorithmique")
        self.assertNotContains(catalogue, "(brouillon)")
        self.assertNotContains(catalogue, "Architecture applicative")  # autre classe

        timetable = client.get(reverse("courses:student_timetable"))
        self.assertContains(timetable, "Amphi A")      # séance de toute la classe
        self.assertContains(timetable, "Salle 105")    # TD du groupe TD A
        self.assertNotContains(timetable, "Salle machine B204")  # TP du groupe TP B

        library = client.get(reverse("courses:student_course_materials"))
        self.assertContains(library, "Polycopié — Parcours de graphes")
        self.assertContains(library, "Plan du cours et bibliographie")

    def test_other_group_sees_the_practical_session_instead(self):
        seed()
        client = self.login("yanis.leroy@u-paris.fr")  # groupe TP B
        timetable = client.get(reverse("courses:student_timetable"))
        self.assertContains(timetable, "Salle machine B204")
        self.assertNotContains(timetable, "Salle 105")

    def test_each_role_reaches_its_pages(self):
        seed()
        expectations = {
            "admin.paris@u-paris.fr": (
                "courses:admin_program_offer", "courses:admin_subjects", "courses:admin_assignments",
                "courses:admin_timetable", "courses:admin_courses",
            ),
            "prof.test@eduspark.local": (
                "courses:prof_course", "courses:prof_subjects", "courses:prof_timetable",
                "courses:prof_course_materials",
            ),
            "m.traore@u-paris.fr": ("courses:prof_course", "courses:prof_timetable"),
            "test.ui@example.com": (
                "courses:student_catalogue", "courses:student_timetable", "courses:student_course_materials",
            ),
        }
        for email, names in expectations.items():
            client = self.login(email)
            for name in names:
                with self.subTest(email=email, page=name):
                    self.assertEqual(client.get(reverse(name)).status_code, 200)

    def test_professor_publishes_per_class_and_the_student_follows(self):
        seed()
        draft = Course.objects.get(title__contains="brouillon")
        self.assertFalse(draft.publications.filter(is_published=True).exists())
        professor = self.login("prof.test@eduspark.local", university="Université Paris Cité")
        school_class = SchoolClass.objects.get(name="Licence 3 Informatique")
        response = professor.post(
            reverse("courses:prof_course_publication", args=[draft.pk, school_class.pk]), {"action": "publier"},
        )
        self.assertEqual(response.status_code, 302)
        student = self.login("test.ui@example.com")
        self.assertContains(student.get(reverse("courses:student_catalogue")), "(brouillon)")
        self.assertEqual(student.get(reverse("courses:student_course_detail", args=[draft.pk])).status_code, 200)
