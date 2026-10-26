"""Intégration avec le reste du projet : formulaire de classe, navigation,
suppressions en cascade depuis le module accounts et site d'administration Django."""

import os

from django.contrib import admin as django_admin
from django.urls import reverse

from accounts.models import Membership, SchoolClass, University
from accounts.tenancy import Role
from courses.models import (
    Chapter, Course, CourseMaterial, CoursePublication, Department, Program, ScheduleSlot,
    Subject, TeachingAssignment,
)

from .base import CoursesTestCase, join, make_slot, make_user, pdf_upload


def nav_labels(response):
    return {
        item["label"]
        for section in response.context["portal_nav_sections"]
        for item in section["items"]
    }


class ClassFormTests(CoursesTestCase):
    def setUp(self):
        self.login(self.admin)

    def payload(self, **overrides):
        data = {
            "name": "Licence 2 Informatique", "level": "2e année", "study_program": self.program.pk,
            "academic_year": "2025-2026", "description": "", "professors": [],
        }
        data.update(overrides)
        return data

    def test_form_offers_the_catalogue_programs_instead_of_free_text(self):
        form = self.client.get(reverse("portal:admin_class_create")).context["form"]
        self.assertIn("study_program", form.fields)
        self.assertNotIn("program", form.fields)
        self.assertEqual(
            sorted(p.name for p in form.fields["study_program"].queryset),
            ["Licence Informatique", "Master Génie Logiciel"],
        )

    def test_choosing_a_program_sets_the_class_label(self):
        response = self.client.post(reverse("portal:admin_class_create"), self.payload())
        self.assertEqual(response.status_code, 302)
        school_class = SchoolClass.objects.get(name="Licence 2 Informatique")
        self.assertEqual((school_class.study_program, school_class.program), (self.program, "Licence Informatique"))
        self.assertEqual(school_class.university, self.univ)

    def test_program_of_another_university_is_refused(self):
        response = self.client.post(
            reverse("portal:admin_class_create"), self.payload(study_program=self.other_program.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SchoolClass.objects.filter(name="Licence 2 Informatique").exists())

    def test_legacy_class_keeps_its_label_when_edited(self):
        legacy = SchoolClass.objects.create(
            university=self.univ, name="Classe historique", program="Ancien libellé", academic_year="2024-2025",
        )
        response = self.client.post(
            reverse("portal:admin_class_update", args=[legacy.pk]),
            {"name": "Classe historique", "level": "", "study_program": "", "academic_year": "2024-2025",
             "description": "Mise à jour", "professors": []},
        )
        self.assertEqual(response.status_code, 302)
        legacy.refresh_from_db()
        self.assertEqual((legacy.program, legacy.study_program, legacy.description), ("Ancien libellé", None, "Mise à jour"))

    def test_free_text_remains_when_the_university_has_no_program(self):
        bare = University.objects.create(name="Université sans catalogue")
        admin = make_user("admin@bare.test")
        join(admin, bare, Role.UNIVERSITY_ADMIN)
        self.login(admin)
        form = self.client.get(reverse("portal:admin_class_create")).context["form"]
        self.assertIn("program", form.fields)
        self.assertNotIn("study_program", form.fields)
        response = self.client.post(reverse("portal:admin_class_create"), {
            "name": "Classe libre", "level": "", "program": "Informatique", "academic_year": "", "description": "",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SchoolClass.objects.get(name="Classe libre").program, "Informatique")

    def test_program_cannot_contradict_the_subjects_already_assigned(self):
        response = self.client.post(
            reverse("portal:admin_class_update", args=[self.school_class.pk]),
            self.payload(name=self.school_class.name, study_program=self.program_gl.pk,
                         professors=[self.prof.pk, self.prof2.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INF501, INF504")
        self.school_class.refresh_from_db()
        self.assertEqual(self.school_class.study_program, self.program)

    def test_clearing_the_program_is_always_allowed(self):
        response = self.client.post(
            reverse("portal:admin_class_update", args=[self.school_class.pk]),
            self.payload(name=self.school_class.name, study_program="", professors=[self.prof.pk, self.prof2.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.school_class.refresh_from_db()
        self.assertIsNone(self.school_class.study_program)

    def test_a_teaching_professor_cannot_be_unticked_from_the_class(self):
        response = self.client.post(
            reverse("portal:admin_class_update", args=[self.school_class.pk]),
            self.payload(name=self.school_class.name, study_program=self.program.pk, professors=[self.prof.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mariam Traoré")
        self.assertIn(self.prof2, self.school_class.professors.all())

    def test_a_professor_without_assignment_can_be_removed_from_the_class(self):
        spare_user = make_user("spare@ut.test", "Paul", "Libre")
        spare = join(spare_user, self.univ, Role.PROFESSOR).professor_profile
        self.school_class.professors.add(spare)
        response = self.client.post(
            reverse("portal:admin_class_update", args=[self.school_class.pk]),
            self.payload(name=self.school_class.name, study_program=self.program.pk,
                         professors=[self.prof.pk, self.prof2.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(spare, self.school_class.professors.all())

    def test_class_detail_lists_subjects_and_teachers(self):
        response = self.client.get(reverse("portal:admin_class_detail", args=[self.school_class.pk]))
        self.assertContains(response, "Matières et enseignants")
        self.assertContains(response, "INF501")
        self.assertContains(response, "INF504")
        self.assertContains(response, "Mariam Traoré")
        self.assertContains(response, reverse("courses:admin_timetable") + "?classe=%d" % self.school_class.pk)
        self.assertContains(response, "Informatique")  # département de la filière
        self.assertNotContains(response, "GEN401")


class CascadeTests(CoursesTestCase):
    def test_deleting_a_class_removes_its_assignments_sessions_and_publications(self):
        make_slot(self.assign)
        course = self.make_course()
        self.publish(course)
        self.school_class.delete()
        self.assertFalse(TeachingAssignment.objects.filter(school_class=self.school_class.pk).exists())
        self.assertEqual(ScheduleSlot.objects.count(), 0)
        self.assertFalse(CoursePublication.objects.exists())
        self.assertTrue(Course.objects.filter(pk=course.pk).exists())  # le cours lui-même reste
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())

    def test_deleting_a_professor_from_the_admin_portal_removes_everything_they_own(self):
        course = self.make_course()
        chapter = Chapter.objects.create(course=course, title="Un")
        material = CourseMaterial.objects.create(course=course, chapter=chapter, file=pdf_upload())
        path = material.file.path
        self.publish(course)
        make_slot(self.assign)
        self.login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("portal:admin_teacher_delete", args=[self.prof.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Membership.objects.filter(user=self.prof_user, university=self.univ).exists())
        self.assertFalse(Course.objects.filter(pk=course.pk).exists())
        self.assertFalse(TeachingAssignment.objects.filter(subject=self.subject).exists())
        self.assertFalse(ScheduleSlot.objects.exists())
        self.assertFalse(CoursePublication.objects.exists())
        self.assertFalse(os.path.exists(path))
        # Les matières, filières et classes subsistent.
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())
        self.assertTrue(SchoolClass.objects.filter(pk=self.school_class.pk).exists())

    def test_deleting_the_head_of_a_department_only_clears_the_link(self):
        self.dept.head = self.prof
        self.dept.save()
        self.login(self.admin)
        self.client.post(reverse("portal:admin_teacher_delete", args=[self.prof.pk]))
        self.dept.refresh_from_db()
        self.assertIsNone(self.dept.head)

    def test_deleting_a_university_removes_its_catalogue(self):
        make_slot(self.assign)
        self.univ.delete()
        for model in (Department, Program, Subject, TeachingAssignment, ScheduleSlot, Course):
            with self.subTest(model=model.__name__):
                self.assertEqual(model.objects.filter(university=self.univ.pk).count(), 0)


class NavigationTests(CoursesTestCase):
    def test_admin_navigation_exposes_the_catalogue_pages(self):
        self.login(self.admin)
        response = self.client.get(reverse("courses:admin_program_offer"))
        labels = nav_labels(response)
        for expected in ("Départements & Filières", "Matières", "Affectations enseignants",
                         "Emploi du temps global", "Tous les cours"):
            self.assertIn(expected, labels)
        self.assertEqual(response.context["portal_current_label"], "Départements & Filières")

    def test_professor_navigation(self):
        self.login(self.prof_user)
        response = self.client.get(reverse("courses:prof_course"))
        labels = nav_labels(response)
        for expected in ("Mes Cours", "Supports de cours", "Emploi du temps", "Mes matières"):
            self.assertIn(expected, labels)
        self.assertNotIn("Gestion des matières", labels)
        self.assertNotIn("Affectations enseignants", labels)

    def test_student_navigation(self):
        self.login(self.student_user)
        labels = nav_labels(self.client.get(reverse("courses:student_catalogue")))
        for expected in ("Catalogue des cours", "Supports de cours", "Mon Emploi du temps"):
            self.assertIn(expected, labels)
        self.assertNotIn("Départements & Filières", labels)

    def test_sub_pages_keep_their_menu_entry_highlighted(self):
        course = self.make_course()
        self.publish(course)
        material = CourseMaterial.objects.create(course=course, title="Poly", file=pdf_upload())
        cases = (
            (self.prof_user, reverse("courses:prof_course_detail", args=[course.pk]), "Mes Cours"),
            (self.prof_user, reverse("courses:prof_course_create"), "Mes Cours"),
            (self.prof_user, reverse("courses:prof_material_create"), "Supports de cours"),
            (self.prof_user, reverse("courses:material_view", args=[material.pk]), "Supports de cours"),
            (self.student_user, reverse("courses:student_course_detail", args=[course.pk]), "Catalogue des cours"),
            (self.student_user, reverse("courses:material_view", args=[material.pk]), "Supports de cours"),
            (self.admin, reverse("courses:admin_department_create"), "Départements & Filières"),
            (self.admin, reverse("courses:admin_subject_create"), "Matières"),
            (self.admin, reverse("courses:admin_assignment_create"), "Affectations enseignants"),
            (self.admin, reverse("courses:admin_slot_create"), "Emploi du temps global"),
            (self.admin, reverse("courses:admin_course_detail", args=[course.pk]), "Tous les cours"),
        )
        for user, url, label in cases:
            with self.subTest(url=url):
                self.login(user)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["portal_current_label"], label)

    def test_pages_use_the_theme_of_the_role(self):
        for user, url, base in (
            (self.admin, reverse("courses:admin_subject_create"), "portal/base_admin.html"),
            (self.prof_user, reverse("courses:prof_course_create"), "portal/base_prof.html"),
        ):
            with self.subTest(user=user.email):
                self.login(user)
                response = self.client.get(url)
                self.assertEqual(response.context["portal_base_template"], base)
                self.assertTemplateUsed(response, base)


class DjangoAdminSiteTests(CoursesTestCase):
    """Le back-office Django reste utilisable pour les nouveaux modèles."""

    def test_every_model_is_registered_and_its_pages_load(self):
        course = self.make_course()
        Chapter.objects.create(course=course, title="Un")
        CourseMaterial.objects.create(course=course, title="Poly", file=pdf_upload())
        self.publish(course)
        make_slot(self.assign)
        self.login(self.platform)
        models = (Department, Program, Subject, TeachingAssignment, ScheduleSlot, Course,
                  CoursePublication, Chapter, CourseMaterial)
        for model in models:
            self.assertIn(model, django_admin.site._registry)
            meta = model._meta
            with self.subTest(model=meta.model_name):
                changelist = reverse("admin:%s_%s_changelist" % (meta.app_label, meta.model_name))
                self.assertEqual(self.client.get(changelist).status_code, 200)
                add = reverse("admin:%s_%s_add" % (meta.app_label, meta.model_name))
                self.assertEqual(self.client.get(add).status_code, 200)
                instance = model.objects.first()
                change = reverse("admin:%s_%s_change" % (meta.app_label, meta.model_name), args=[instance.pk])
                self.assertEqual(self.client.get(change).status_code, 200)
