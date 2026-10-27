"""Tests unitaires des modèles du module cours : validations, conflits d'emploi
du temps, droits d'accès aux supports, filtres de gabarits et signaux."""

from datetime import time
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import SchoolClass, StudentGroup
from accounts.tenancy import Role
from courses import files
from courses.forms import SubjectForm, TeachingAssignmentForm
from courses.models import (
    CONFLICT_CLASS, CONFLICT_PROFESSOR, CONFLICT_ROOM, Chapter, Course, CourseMaterial, CoursePublication,
    Department, Program, ScheduleSlot, Subject, TeachingAssignment,
)
from courses.services import can_access_material, format_minutes
from courses.templatetags.courses_extras import minutes_fr, size_fr

from .base import PDF_BYTES, CoursesTestCase, join, make_slot, make_user


class CatalogueValidationTests(CoursesTestCase):
    def test_department_head_must_belong_to_the_university(self):
        department = Department(university=self.univ, name="Physique", head=self.other_prof)
        with self.assertRaises(ValidationError) as error:
            department.clean()
        self.assertIn("head", error.exception.message_dict)
        Department(university=self.univ, name="Physique", head=self.prof).clean()

    def test_department_name_is_stripped_on_save(self):
        department = Department.objects.create(university=self.univ, name="  Chimie  ")
        self.assertEqual(department.name, "Chimie")
        self.assertIn("Chimie", str(department))

    def test_program_coordinator_must_belong_to_the_university(self):
        program = Program(department=self.dept, name="Licence Pro", coordinator=self.other_prof)
        with self.assertRaises(ValidationError) as error:
            program.clean()
        self.assertIn("coordinator", error.exception.message_dict)

    def test_program_takes_the_university_of_its_department_and_normalizes(self):
        program = Program.objects.create(department=self.dept, name="  Licence Pro ", code=" lp-dev ")
        self.assertEqual(program.university_id, self.univ.pk)
        self.assertEqual((program.name, program.code), ("Licence Pro", "LP-DEV"))
        self.assertEqual(program.semester_count, program.duration_years * 2)

    def test_subject_program_of_another_university_is_refused(self):
        subject = Subject(program=self.other_program, university=self.univ, name="X", code="X1", semester=1)
        with self.assertRaises(ValidationError) as error:
            subject.clean()
        self.assertIn("program", error.exception.message_dict)

    def test_subject_semester_must_exist_in_the_program(self):
        subject = Subject(program=self.program, university=self.univ, name="X", code="X1", semester=9)
        with self.assertRaisesMessage(ValidationError, "compte 6 semestres"):
            subject.clean()
        self.assertEqual(Subject(semester=3).semester_label, "S3")

    def test_subject_cannot_move_to_a_program_whose_classes_differ(self):
        self.subject.program = self.program_gl
        self.subject.semester = 1
        with self.assertRaisesMessage(ValidationError, "affectée à des classes d'une autre filière"):
            self.subject.clean()

    def test_subject_code_is_uppercased_and_takes_program_university(self):
        subject = Subject.objects.create(program=self.program, name=" Réseaux ", code=" inf510 ", semester=5)
        self.assertEqual((subject.name, subject.code, subject.university_id), ("Réseaux", "INF510", self.univ.pk))


class AssignmentValidationTests(CoursesTestCase):
    def test_professor_must_belong_to_the_class_university(self):
        assignment = TeachingAssignment(school_class=self.school_class, subject=self.subject2,
                                        professor=self.other_prof)
        with self.assertRaises(ValidationError) as error:
            assignment.clean()
        self.assertIn("professor", error.exception.message_dict)

    def test_replacing_professor_busy_on_a_transferred_slot_is_refused(self):
        make_slot(self.assign, weekday=0, start="08:30", end="10:00")
        other_prof = join(make_user("remplacant@ut.test"), self.univ, Role.PROFESSOR).professor_profile
        TeachingAssignment.objects.create(school_class=self.class_gl, subject=self.subject_gl, professor=other_prof)
        make_slot(TeachingAssignment.objects.get(professor=other_prof), weekday=0, start="09:00", end="11:00")
        assignment = TeachingAssignment.objects.get(pk=self.assign.pk)
        assignment.professor = other_prof
        with self.assertRaisesMessage(ValidationError, "déjà occupé sur un créneau de cette matière"):
            assignment.clean()

    def test_replacing_professor_free_on_the_slots_is_accepted(self):
        make_slot(self.assign, weekday=0, start="08:30", end="10:00")
        free = join(make_user("libre@ut.test"), self.univ, Role.PROFESSOR).professor_profile
        assignment = TeachingAssignment.objects.get(pk=self.assign.pk)
        assignment.professor = free
        assignment.clean()
        assignment.save()
        self.assertEqual(assignment.slots.get().professor, free)


class ScheduleSlotTests(CoursesTestCase):
    def test_shortcuts_and_labels(self):
        slot = make_slot(self.assign, weekday=1, start="10:15", end="11:45", room=" Salle 204 ")
        self.assertEqual(slot.room, "Salle 204")
        self.assertEqual(slot.school_class, self.school_class)
        self.assertEqual(slot.professor, self.prof)
        self.assertEqual(slot.time_label, "10:15 – 11:45")
        self.assertEqual(slot.duration_minutes, 90)
        self.assertIn("INF501", slot.describe())
        self.assertIn(self.school_class.name, str(slot))

    def test_groups_sharing_a_student_are_in_conflict(self):
        make_slot(self.assign, weekday=2, start="08:30", end="10:00", group=self.group_td)
        self.group_tp.students.add(self.student)
        slot = ScheduleSlot(assignment=self.assign2, weekday=2, start_time=time(9), end_time=time(10),
                            group=self.group_tp)
        reasons = [reasons for reasons, _other in slot.find_conflicts()]
        self.assertIn(CONFLICT_CLASS, reasons[0])

    def test_disjoint_groups_are_not_in_conflict(self):
        other_prof = join(make_user("tp@ut.test"), self.univ, Role.PROFESSOR).professor_profile
        assignment = TeachingAssignment.objects.get(pk=self.assign2.pk)
        assignment.professor = other_prof
        assignment.save()
        make_slot(self.assign, weekday=2, start="08:30", end="10:00", group=self.group_td)
        slot = ScheduleSlot(assignment=assignment, weekday=2, start_time=time(9), end_time=time(10),
                            group=self.group_tp)
        self.assertEqual(slot.find_conflicts(), [])

    def test_room_and_professor_conflicts_are_reported(self):
        make_slot(self.assign, weekday=3, start="14:00", end="16:00", room="Amphi A")
        # Même professeur, autre classe, même salle (casse et espaces ignorés).
        slot = ScheduleSlot(assignment=self.assign_gl, weekday=3, start_time=time(15), end_time=time(17),
                            room="amphi a ")
        reasons = slot.find_conflicts()[0][0]
        self.assertEqual(sorted(reasons), sorted([CONFLICT_PROFESSOR, CONFLICT_ROOM]))
        with self.assertRaisesMessage(ValidationError, "Amphi A"):
            slot.clean()

    def test_back_to_back_slots_and_incomplete_slots_have_no_conflict(self):
        make_slot(self.assign, weekday=4, start="08:30", end="10:00")
        self.assertEqual(ScheduleSlot(assignment=self.assign, weekday=4, start_time=time(10),
                                      end_time=time(11)).find_conflicts(), [])
        self.assertEqual(ScheduleSlot(weekday=4).find_conflicts(), [])
        self.assertEqual(ScheduleSlot(assignment=self.assign, weekday=4, start_time=time(11),
                                      end_time=time(10)).find_conflicts(), [])

    def test_clean_without_assignment_does_nothing_and_group_must_match_class(self):
        ScheduleSlot(weekday=0).clean()
        other_group = StudentGroup.objects.create(school_class=self.class_gl, name="TD Z")
        slot = ScheduleSlot(assignment=self.assign, weekday=0, start_time=time(8), end_time=time(9), group=other_group)
        with self.assertRaisesMessage(ValidationError, "Ce groupe n'appartient pas"):
            slot.clean()


class CourseAndPublicationTests(CoursesTestCase):
    def test_publication_course_and_class_of_different_universities(self):
        publication = CoursePublication(course=self.make_course(), school_class=self.other_class)
        with self.assertRaisesMessage(ValidationError, "même université"):
            publication.clean()

    def test_publication_requires_the_professor_to_teach_the_class(self):
        publication = CoursePublication(course=self.make_course(), school_class=self.class_gl)
        with self.assertRaisesMessage(ValidationError, "n'enseigne pas cette matière"):
            publication.clean()

    def test_publication_label_and_university(self):
        publication = self.publish(self.make_course())
        self.assertEqual(publication.university_id, self.univ.pk)
        self.assertIn("publié", str(publication))
        publication.is_published = False
        self.assertIn("non publié", str(publication))

    def test_changing_subject_unpublishes_classes_where_it_is_not_taught(self):
        course = self.make_course()
        self.publish(course)
        course.title = "Nouveau titre"  # même matière : la publication reste
        course.save()
        self.assertTrue(course.publications.exists())
        # Le professeur n'enseigne pas « Architecture applicative » en Licence 3 : publication retirée.
        course.subject = self.subject_gl
        course.save()
        self.assertFalse(course.publications.exists())

    def test_course_title_is_stripped(self):
        self.assertEqual(self.make_course(title="  Graphes  ").title, "Graphes")


class MaterialAccessTests(CoursesTestCase):
    def setUp(self):
        self.course = self.make_course()
        self.material = CourseMaterial.objects.create(
            course=self.course, file=SimpleUploadedFile("cours.pdf", PDF_BYTES), uploaded_by=self.prof_user,
        )

    def test_anonymous_and_outsiders_cannot_read(self):
        self.assertFalse(can_access_material(AnonymousUser(), self.material))
        self.assertFalse(can_access_material(self.other_student_user, self.material))
        self.assertFalse(can_access_material(self.other_prof_user, self.material))

    def test_superuser_admin_and_author_can_read(self):
        self.assertTrue(can_access_material(self.platform, self.material))
        self.assertTrue(can_access_material(self.admin, self.material))
        self.assertTrue(can_access_material(self.prof_user, self.material))

    def test_another_professor_of_the_same_university_cannot_read(self):
        colleague = make_user("collegue@ut.test")
        join(colleague, self.univ, Role.PROFESSOR)
        self.assertFalse(can_access_material(colleague, self.material))

    def test_student_reads_only_once_published_for_their_class(self):
        self.assertFalse(can_access_material(self.student_user, self.material))
        self.publish(self.course, published=False)
        self.assertFalse(can_access_material(self.student_user, self.material))
        self.publish(self.course, published=True)
        self.assertTrue(can_access_material(self.student_user, self.material))

    def test_inactive_membership_loses_access(self):
        self.publish(self.course)
        self.student_user.memberships.update(is_active=False)
        self.assertFalse(can_access_material(self.student_user, self.material))


class HelpersAndSignalsTests(CoursesTestCase):
    def test_minutes_and_size_filters(self):
        self.assertEqual(minutes_fr(210), "3 h 30")
        self.assertEqual(minutes_fr(120), "2 h")
        self.assertEqual(minutes_fr(45), "45 min")
        self.assertEqual(minutes_fr(None), "0 min")
        self.assertEqual(format_minutes("90"), "1 h 30")
        self.assertEqual(size_fr(500), "500 o")
        self.assertEqual(size_fr(5 * 1024 * 1024), "5 Mo")
        self.assertTrue(files.format_size(3 * 1024 ** 4).endswith("Go"))  # au-delà : reste en Go
        self.assertEqual(size_fr(None), "0 o")

    def test_deleting_a_material_removes_its_file_after_commit(self):
        material = CourseMaterial.objects.create(
            course=self.make_course(), file=SimpleUploadedFile("cours.pdf", PDF_BYTES), uploaded_by=self.prof_user,
        )
        storage, name = material.file.storage, material.file.name
        self.assertTrue(storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            material.delete()
        self.assertFalse(storage.exists(name))

    def test_material_without_file_name_deletes_nothing(self):
        material = mock.Mock()
        material.file.name = ""
        from courses.signals import delete_material_file

        with mock.patch("courses.signals.transaction.on_commit") as on_commit:
            delete_material_file(CourseMaterial, material)
        on_commit.assert_not_called()

    def test_deleting_an_assignment_purges_its_publications(self):
        course = self.make_course()
        self.publish(course)
        with self.captureOnCommitCallbacks(execute=True):
            TeachingAssignment.objects.get(pk=self.assign.pk).delete()
        self.assertFalse(course.publications.exists())

    def test_chapter_order_and_label(self):
        course = self.make_course()
        first = Chapter.objects.create(course=course, title="Intro", order=1)
        second = Chapter.objects.create(course=course, title="Suite", order=2)
        self.assertEqual(list(course.chapters.all()), [first, second])
        self.assertIn("Intro", str(first))


class FormsUnitTests(CoursesTestCase):
    def test_subject_name_must_be_unique_in_its_program_but_can_be_kept(self):
        data = {"program": self.program.pk, "name": "algorithmique AVANCÉE", "code": "NEW1", "semester": 5,
                "coefficient": 1, "credits": 1, "hours_cm": 0, "hours_td": 0, "hours_tp": 0, "is_active": True}
        form = SubjectForm(data, university=self.univ)
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)
        edit = SubjectForm(dict(data, name="Algorithmique avancée", code="INF501"),
                           instance=self.subject, university=self.univ)
        self.assertTrue(edit.is_valid(), edit.errors)

    def test_assignment_form_filters_subjects_by_the_class_program(self):
        form = TeachingAssignmentForm(university=self.univ, school_class=self.school_class)
        self.assertEqual(form.fields["school_class"].initial, self.school_class.pk)
        self.assertNotIn(self.subject_gl, form.fields["subject"].queryset)
        free_class = SchoolClass.objects.create(university=self.univ, name="Classe libre", academic_year="2025-2026")
        form = TeachingAssignmentForm(university=self.univ, school_class=free_class)
        self.assertIn(self.subject_gl, form.fields["subject"].queryset)

    def test_assignment_form_in_edit_mode_locks_class_and_subject(self):
        form = TeachingAssignmentForm(instance=self.assign, university=self.univ)
        self.assertTrue(form.fields["school_class"].disabled)
        self.assertTrue(form.fields["subject"].disabled)
