"""Règles métier portées par les modèles : unicités, validations, conflits
d'horaires, cohérence des publications et nettoyage des fichiers."""

import os
from datetime import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError

from accounts.models import SchoolClass, StudentGroup
from courses import files
from courses.models import (
    Chapter, Course, CourseMaterial, CoursePublication, Department, Program, ScheduleSlot,
    Subject, TeachingAssignment,
)

from .base import CoursesTestCase, make_slot, pdf_upload


class CatalogTests(CoursesTestCase):
    def test_department_name_is_unique_per_university_ignoring_case(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Department.objects.create(university=self.univ, name="informatique")
        # Le même nom reste possible dans une autre université.
        Department.objects.create(university=self.other_univ, name="Informatique")

    def test_codes_are_uppercased_and_unique_per_university(self):
        department = Department.objects.create(university=self.univ, name="Physique", code=" phy ")
        self.assertEqual(department.code, "PHY")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Department.objects.create(university=self.univ, name="Chimie", code="phy")
        Department.objects.create(university=self.univ, name="Biologie", code="")
        Department.objects.create(university=self.univ, name="Géologie", code="")  # codes vides tolérés

    def test_program_university_follows_department(self):
        program = Program.objects.create(department=self.dept, name="Licence Réseaux")
        self.assertEqual(program.university, self.univ)

    def test_program_rename_updates_class_label(self):
        self.assertEqual(self.school_class.program, "Licence Informatique")
        self.program.name = "Licence Informatique Générale"
        self.program.save()
        self.school_class.refresh_from_db()
        self.assertEqual(self.school_class.program, "Licence Informatique Générale")

    def test_class_label_follows_selected_program(self):
        school_class = SchoolClass.objects.create(
            university=self.univ, name="Classe test", study_program=self.program_gl,
        )
        self.assertEqual(school_class.program, "Master Génie Logiciel")

    def test_subject_semester_must_fit_the_program_duration(self):
        subject = Subject(
            university=self.univ, program=self.program_gl, name="Hors durée", code="XXX1", semester=5,
        )
        with self.assertRaises(ValidationError) as caught:
            subject.full_clean(exclude=["university"])
        self.assertIn("semester", caught.exception.message_dict)
        subject.semester = 4
        subject.full_clean(exclude=["university"])

    def test_subject_code_is_unique_per_university(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subject.objects.create(program=self.program, name="Autre", code="inf501")

    def test_subject_derived_values(self):
        self.assertEqual(self.subject.total_hours, 54)
        self.assertEqual(self.subject.semester_label, "S5")

    def test_subject_cannot_move_to_another_program_while_assigned_to_classes_of_the_current_one(self):
        other_program = Program.objects.create(department=self.dept, name="Licence Réseaux", duration_years=3)
        self.subject.program = other_program
        with self.assertRaises(ValidationError) as caught:
            self.subject.full_clean(exclude=["university"])
        self.assertIn("program", caught.exception.message_dict)
        # Sans classe liée à la filière d'origine, le changement est possible.
        TeachingAssignment.objects.filter(subject=self.subject).delete()
        self.subject.full_clean(exclude=["university"])

    def test_deleting_catalog_objects_in_use_is_refused(self):
        with self.assertRaises(RestrictedError):
            self.dept.delete()
        with self.assertRaises(RestrictedError):
            self.program.delete()
        with self.assertRaises(RestrictedError):
            self.subject.delete()


class AssignmentTests(CoursesTestCase):
    def test_assignment_attaches_professor_to_the_class(self):
        self.assertIn(self.prof, self.school_class.professors.all())
        self.assertIn(self.prof2, self.school_class.professors.all())
        self.assertEqual(self.assign.university, self.univ)

    def test_assignment_is_unique_per_class_subject_professor(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeachingAssignment.objects.create(
                school_class=self.school_class, subject=self.subject, professor=self.prof,
            )

    def test_two_professors_can_share_a_subject_in_a_class(self):
        TeachingAssignment.objects.create(
            school_class=self.school_class, subject=self.subject, professor=self.prof2,
        )

    def test_assignment_rejects_subject_of_another_program(self):
        assignment = TeachingAssignment(
            school_class=self.school_class, subject=self.subject_gl, professor=self.prof,
        )
        with self.assertRaises(ValidationError) as caught:
            assignment.full_clean(exclude=["university"])
        self.assertIn("subject", caught.exception.message_dict)

    def test_assignment_rejects_other_university(self):
        assignment = TeachingAssignment(
            school_class=self.school_class, subject=self.other_subject, professor=self.other_prof,
        )
        with self.assertRaises(ValidationError) as caught:
            assignment.full_clean(exclude=["university"])
        self.assertIn("subject", caught.exception.message_dict)
        self.assertIn("professor", caught.exception.message_dict)

    def test_class_without_program_accepts_any_subject(self):
        free_class = SchoolClass.objects.create(university=self.univ, name="Classe libre")
        assignment = TeachingAssignment(
            school_class=free_class, subject=self.subject_gl, professor=self.prof,
        )
        assignment.full_clean(exclude=["university"])

    def test_deleting_an_assignment_unpublishes_the_professor_courses(self):
        course = self.make_course()
        self.publish(course)
        self.assign.delete()
        self.assertFalse(CoursePublication.objects.filter(course=course).exists())

    def test_replacing_the_professor_unpublishes_the_previous_courses(self):
        course = self.make_course()
        self.publish(course)
        assignment = TeachingAssignment.objects.get(pk=self.assign.pk)
        assignment.professor = self.prof2
        assignment.save()
        self.assertFalse(CoursePublication.objects.filter(course=course).exists())
        self.assertIn(self.prof2, self.school_class.professors.all())

    def test_replacing_the_professor_checks_existing_slots(self):
        make_slot(self.assign, weekday=0, start="08:30", end="10:00")
        make_slot(self.assign2, weekday=0, start="08:30", end="10:00")
        assignment = TeachingAssignment.objects.get(pk=self.assign.pk)
        assignment.professor = self.prof2  # prof2 enseigne déjà à ce créneau
        with self.assertRaises(ValidationError) as caught:
            assignment.full_clean(exclude=["university"])
        self.assertIn("professor", caught.exception.message_dict)


class SlotTests(CoursesTestCase):
    def build(self, assignment=None, weekday=0, start="08:30", end="10:00", room="", group=None):
        return ScheduleSlot(
            assignment=assignment or self.assign, weekday=weekday, session_type="cm",
            start_time=time.fromisoformat(start), end_time=time.fromisoformat(end),
            room=room, group=group,
        )

    def conflicts(self, slot):
        return [reasons for reasons, _other in slot.find_conflicts()]

    def test_end_must_follow_start(self):
        with self.assertRaises(ValidationError) as caught:
            self.build(start="10:00", end="09:00").full_clean(exclude=["university"])
        self.assertEqual(
            caught.exception.messages, ["L'heure de fin doit être postérieure à l'heure de début."],
        )

    def test_database_rejects_inverted_times(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_slot(self.assign, start="11:00", end="10:00")

    def test_class_conflict(self):
        make_slot(self.assign, start="08:30", end="10:00")
        # Autre matière, autre professeur, même classe, créneau qui se chevauche.
        self.assertEqual(self.conflicts(self.build(self.assign2, start="09:00", end="10:30")), [["classe"]])

    def test_professor_conflict_across_classes(self):
        make_slot(self.assign, start="08:30", end="10:00")
        # prof enseigne aussi au master : il ne peut pas être aux deux endroits.
        self.assertEqual(self.conflicts(self.build(self.assign_gl, start="09:00", end="11:00")), [["professeur"]])

    def test_room_conflict_across_classes_ignores_case_and_spaces(self):
        make_slot(self.assign, start="08:30", end="10:00", room="Amphi A")
        slot = self.build(self.assign_gl, start="09:00", end="10:30", room=" amphi a ")
        # Le professeur est le même (prof) : classe différente, mais professeur et salle en conflit.
        self.assertEqual(self.conflicts(slot), [["professeur", "salle"]])

    def test_back_to_back_and_other_days_are_fine(self):
        make_slot(self.assign, start="08:30", end="10:00")
        self.assertEqual(self.conflicts(self.build(self.assign2, start="10:00", end="11:30")), [])
        self.assertEqual(self.conflicts(self.build(self.assign2, weekday=1, start="08:30", end="10:00")), [])

    def test_editing_a_slot_does_not_conflict_with_itself(self):
        slot = make_slot(self.assign, start="08:30", end="10:00")
        slot.end_time = time(10, 30)
        self.assertEqual(self.conflicts(slot), [])

    def test_groups_of_different_students_can_run_in_parallel(self):
        make_slot(self.assign, start="08:30", end="10:00", group=self.group_td)
        slot = self.build(self.assign2, start="08:30", end="10:00", group=self.group_tp)
        self.assertEqual(self.conflicts(slot), [])

    def test_groups_sharing_a_student_conflict(self):
        make_slot(self.assign, start="08:30", end="10:00", group=self.group_td)
        self.group_tp.students.add(self.student)  # Camille est maintenant dans les deux groupes
        slot = self.build(self.assign2, start="08:30", end="10:00", group=self.group_tp)
        self.assertEqual(self.conflicts(slot), [["classe"]])

    def test_whole_class_session_conflicts_with_a_group_session(self):
        make_slot(self.assign, start="08:30", end="10:00", group=self.group_td)
        self.assertEqual(self.conflicts(self.build(self.assign2, start="09:00", end="10:00")), [["classe"]])

    def test_clean_reports_every_conflict(self):
        make_slot(self.assign, start="08:30", end="10:00", room="B204")
        slot = self.build(self.assign, start="09:00", end="10:00", room="B204")
        with self.assertRaises(ValidationError) as caught:
            slot.full_clean(exclude=["university"])
        text = " ".join(caught.exception.messages)
        for expected in ("classe", "professeur", "salle"):
            self.assertIn(expected, text)

    def test_group_must_belong_to_the_assignment_class(self):
        foreign = StudentGroup.objects.create(school_class=self.class_gl, name="Groupe GL")
        with self.assertRaises(ValidationError) as caught:
            self.build(group=foreign).full_clean(exclude=["university"])
        self.assertIn("group", caught.exception.message_dict)

    def test_slot_shortcuts(self):
        slot = make_slot(self.assign, start="08:30", end="10:00")
        self.assertEqual(slot.university, self.univ)
        self.assertEqual(slot.subject, self.subject)
        self.assertEqual(slot.professor, self.prof)
        self.assertEqual(slot.time_label, "08:30 – 10:00")
        self.assertEqual(slot.duration_minutes, 90)
        self.assertEqual(slot.type_label, "CM")


class CourseTests(CoursesTestCase):
    def test_course_requires_a_taught_subject(self):
        course = Course(professor=self.prof2, subject=self.subject_gl, title="Hors périmètre")
        with self.assertRaises(ValidationError) as caught:
            course.full_clean(exclude=["university"])
        self.assertIn("subject", caught.exception.message_dict)

    def test_course_university_follows_subject(self):
        self.assertEqual(self.make_course().university, self.univ)

    def test_course_title_is_unique_per_professor_and_subject(self):
        self.make_course(title="Introduction")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_course(title="introduction")
        self.make_course(subject=self.subject_gl, title="Introduction")  # autre matière : permis

    def test_publication_requires_an_assignment(self):
        course = self.make_course()  # INF501 : le professeur l'enseigne à la L3, pas au master
        with self.assertRaises(ValidationError):
            CoursePublication(course=course, school_class=self.class_gl).clean()
        CoursePublication(course=course, school_class=self.school_class).clean()

    def test_changing_the_subject_keeps_only_the_classes_where_the_new_subject_is_taught(self):
        course = self.make_course()  # INF501, publié pour la L3 où le professeur enseigne aussi INF504 ci-dessous
        self.publish(course)
        TeachingAssignment.objects.create(
            school_class=self.school_class, subject=self.subject2, professor=self.prof,
        )
        course = Course.objects.get(pk=course.pk)
        course.subject = self.subject2
        course.save()
        self.assertTrue(CoursePublication.objects.filter(course=course, school_class=self.school_class).exists())

        # GEN401 n'est enseigné par ce professeur qu'au master : la publication L3 disparaît.
        course = Course.objects.get(pk=course.pk)
        course.subject = self.subject_gl
        course.save()
        self.assertFalse(CoursePublication.objects.filter(course=course).exists())

    def test_chapter_gets_the_next_order_automatically(self):
        course = self.make_course()
        first = Chapter.objects.create(course=course, title="Un")
        second = Chapter.objects.create(course=course, title="Deux")
        self.assertEqual((first.order, second.order), (1, 2))

    def test_deleting_a_course_cascades_to_its_content(self):
        course = self.make_course()
        chapter = Chapter.objects.create(course=course, title="Un")
        CourseMaterial.objects.create(course=course, chapter=chapter, file=pdf_upload())
        self.publish(course)
        course.delete()
        self.assertFalse(Chapter.objects.exists())
        self.assertFalse(CourseMaterial.objects.exists())
        self.assertFalse(CoursePublication.objects.exists())


class MaterialTests(CoursesTestCase):
    def test_metadata_is_derived_from_the_uploaded_file(self):
        course = self.make_course()
        material = CourseMaterial.objects.create(course=course, file=pdf_upload("Polycopié de cours.pdf"))
        self.assertEqual(material.material_type, files.PDF)
        self.assertEqual(material.original_name, "Polycopié de cours.pdf")
        self.assertEqual(material.size, len(pdf_upload().read()))
        self.assertEqual(material.title, "Polycopié de cours")  # titre par défaut : nom du fichier
        self.assertTrue(material.file.name.startswith("courses/%d/%d/" % (self.univ.pk, course.pk)))
        self.assertTrue(material.file.name.endswith(".pdf"))

    def test_stored_name_does_not_leak_the_original_name(self):
        material = CourseMaterial.objects.create(course=self.make_course(), file=pdf_upload("secret.pdf"))
        self.assertNotIn("secret", material.file.name)

    def test_file_has_no_public_url_and_lives_outside_media_root(self):
        material = CourseMaterial.objects.create(course=self.make_course(), file=pdf_upload())
        self.assertEqual(material.file.url, "")
        self.assertTrue(os.path.isfile(material.file.path))
        self.assertFalse(os.path.abspath(material.file.path).startswith(os.path.abspath(settings.MEDIA_ROOT)))

    def test_unsupported_extension_is_refused(self):
        with self.assertRaises(ValidationError):
            CourseMaterial.objects.create(
                course=self.make_course(), file=SimpleUploadedFile("virus.exe", b"MZ"),
            )

    def test_chapter_must_belong_to_the_course(self):
        course = self.make_course()
        foreign_chapter = Chapter.objects.create(course=self.make_course(title="Autre"), title="Ailleurs")
        material = CourseMaterial(course=course, chapter=foreign_chapter, title="x", file=pdf_upload())
        with self.assertRaises(ValidationError) as caught:
            material.clean()
        self.assertIn("chapter", caught.exception.message_dict)

    def test_file_is_removed_from_disk_when_the_record_is_deleted(self):
        material = CourseMaterial.objects.create(course=self.make_course(), file=pdf_upload())
        path = material.file.path
        self.assertTrue(os.path.isfile(path))
        with self.captureOnCommitCallbacks(execute=True):
            material.delete()
        self.assertFalse(os.path.exists(path))

    def test_deleting_a_chapter_removes_its_materials_and_files(self):
        course = self.make_course()
        chapter = Chapter.objects.create(course=course, title="Un")
        material = CourseMaterial.objects.create(course=course, chapter=chapter, file=pdf_upload())
        path = material.file.path
        with self.captureOnCommitCallbacks(execute=True):
            chapter.delete()
        self.assertFalse(CourseMaterial.objects.filter(pk=material.pk).exists())
        self.assertFalse(os.path.exists(path))

    def test_presentation_helpers(self):
        material = CourseMaterial.objects.create(
            course=self.make_course(), file=SimpleUploadedFile("cours.pptx", b"PK\x03\x04data"),
        )
        self.assertEqual(material.material_type, files.PRESENTATION)
        self.assertFalse(material.can_preview)
        self.assertEqual(material.extension_label, "PPTX")
        self.assertEqual(material.icon, "slideshow")
