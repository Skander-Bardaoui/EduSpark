"""Portail admin université : droits, CRUD du catalogue, affectations, emploi du temps."""

from django.conf import settings
from django.contrib.messages import get_messages
from django.urls import reverse

from courses.models import (
    Chapter, CourseMaterial, CoursePublication, Department, Program, ScheduleSlot, Subject,
    TeachingAssignment,
)

from .base import CoursesTestCase, make_slot, pdf_upload


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


class AdminAccessTests(CoursesTestCase):
    def urls(self):
        listing = [
            reverse(name) for name in (
                "courses:admin_program_offer", "courses:admin_subjects", "courses:admin_assignments",
                "courses:admin_timetable", "courses:admin_courses",
                "courses:admin_department_create", "courses:admin_program_create",
                "courses:admin_subject_create", "courses:admin_assignment_create",
                "courses:admin_slot_create",
            )
        ]
        slot = make_slot(self.assign)
        course = self.make_course()
        objects = [
            reverse("courses:admin_department_update", args=[self.dept.pk]),
            reverse("courses:admin_department_delete", args=[self.dept.pk]),
            reverse("courses:admin_program_update", args=[self.program.pk]),
            reverse("courses:admin_program_delete", args=[self.program.pk]),
            reverse("courses:admin_subject_update", args=[self.subject.pk]),
            reverse("courses:admin_subject_delete", args=[self.subject.pk]),
            reverse("courses:admin_assignment_update", args=[self.assign.pk]),
            reverse("courses:admin_assignment_delete", args=[self.assign.pk]),
            reverse("courses:admin_slot_update", args=[slot.pk]),
            reverse("courses:admin_slot_delete", args=[slot.pk]),
            reverse("courses:admin_course_detail", args=[course.pk]),
        ]
        return listing + objects

    def test_anonymous_users_are_sent_to_the_login_page(self):
        urls = self.urls()
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(
                    response, "%s?next=%s" % (settings.LOGIN_URL, url), fetch_redirect_response=False,
                )

    def test_professors_and_students_are_refused(self):
        urls = self.urls()
        for user in (self.prof_user, self.student_user):
            self.login(user)
            for url in urls:
                with self.subTest(user=user.email, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_platform_admin_is_redirected_to_universities(self):
        self.login(self.platform)
        response = self.client.get(reverse("courses:admin_program_offer"))
        self.assertRedirects(response, reverse("portal:admin_universities"))

    def test_university_admin_reaches_every_page(self):
        urls = self.urls()
        self.login(self.admin)
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_of_another_university_cannot_touch_foreign_objects(self):
        slot = make_slot(self.assign)
        course = self.make_course()
        foreign = [
            reverse("courses:admin_department_update", args=[self.dept.pk]),
            reverse("courses:admin_department_delete", args=[self.dept.pk]),
            reverse("courses:admin_program_update", args=[self.program.pk]),
            reverse("courses:admin_subject_update", args=[self.subject.pk]),
            reverse("courses:admin_assignment_update", args=[self.assign.pk]),
            reverse("courses:admin_assignment_delete", args=[self.assign.pk]),
            reverse("courses:admin_slot_update", args=[slot.pk]),
            reverse("courses:admin_slot_delete", args=[slot.pk]),
        ]
        detail = reverse("courses:admin_course_detail", args=[course.pk])
        self.login(self.other_admin)
        for url in foreign:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertTrue(Department.objects.filter(pk=self.dept.pk).exists())

    def test_lists_are_scoped_to_the_current_university(self):
        self.login(self.other_admin)
        response = self.client.get(reverse("courses:admin_subjects"))
        self.assertContains(response, "MAT101")
        self.assertNotContains(response, "INF501")
        response = self.client.get(reverse("courses:admin_assignments"))
        self.assertContains(response, "L1 Maths")
        self.assertNotContains(response, "Licence 3 Informatique")


class DepartmentAndProgramTests(CoursesTestCase):
    def setUp(self):
        self.login(self.admin)

    def test_offer_page_lists_departments_and_programs(self):
        response = self.client.get(reverse("courses:admin_program_offer"))
        self.assertContains(response, "Informatique")
        self.assertContains(response, "Licence Informatique")
        self.assertContains(response, "Master Génie Logiciel")
        self.assertEqual(response.context["stats"]["programs"], 2)
        self.assertEqual(response.context["stats"]["classes"], 2)

    def test_offer_page_can_filter_programs_by_department(self):
        other = Department.objects.create(university=self.univ, name="Sciences")
        Program.objects.create(department=other, name="Licence Physique")
        response = self.client.get(reverse("courses:admin_program_offer"), {"departement": other.pk})
        self.assertEqual([p.name for p in response.context["programs"]], ["Licence Physique"])

    def test_create_department(self):
        response = self.client.post(reverse("courses:admin_department_create"), {
            "name": "Mathématiques", "code": "math", "head": self.prof.pk, "description": "Algèbre",
        })
        self.assertRedirects(response, reverse("courses:admin_program_offer"))
        department = Department.objects.get(university=self.univ, name="Mathématiques")
        self.assertEqual((department.code, department.university, department.head), ("MATH", self.univ, self.prof))

    def test_duplicate_department_name_is_refused_with_a_message(self):
        response = self.client.post(reverse("courses:admin_department_create"), {"name": "INFORMATIQUE"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Un département porte déjà ce nom.")
        self.assertEqual(Department.objects.filter(university=self.univ).count(), 1)

    def test_head_must_come_from_the_same_university(self):
        response = self.client.post(reverse("courses:admin_department_create"), {
            "name": "Physique", "head": self.other_prof.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Department.objects.filter(name="Physique").exists())

    def test_update_department(self):
        response = self.client.post(
            reverse("courses:admin_department_update", args=[self.dept.pk]),
            {"name": "Informatique & IA", "code": "INFO", "description": ""},
        )
        self.assertRedirects(response, reverse("courses:admin_program_offer"))
        self.dept.refresh_from_db()
        self.assertEqual(self.dept.name, "Informatique & IA")

    def test_delete_department_in_use_is_blocked_with_an_explanation(self):
        url = reverse("courses:admin_department_delete", args=[self.dept.pk])
        page = self.client.get(url)
        self.assertContains(page, "2")  # nombre de filières rattachées
        response = self.client.post(url, follow=True)
        self.assertTrue(Department.objects.filter(pk=self.dept.pk).exists())
        self.assertTrue(any("Suppression impossible" in m for m in messages_of(response)))

    def test_delete_empty_department(self):
        empty = Department.objects.create(university=self.univ, name="Vide")
        response = self.client.post(reverse("courses:admin_department_delete", args=[empty.pk]))
        self.assertRedirects(response, reverse("courses:admin_program_offer"))
        self.assertFalse(Department.objects.filter(pk=empty.pk).exists())

    def test_create_program(self):
        response = self.client.post(reverse("courses:admin_program_create"), {
            "name": "Licence Réseaux", "code": "lic-res", "department": self.dept.pk,
            "degree": "licence", "duration_years": 3, "coordinator": self.prof2.pk, "description": "",
        })
        self.assertRedirects(response, reverse("courses:admin_program_offer"))
        program = Program.objects.get(name="Licence Réseaux")
        self.assertEqual((program.code, program.university, program.coordinator), ("LIC-RES", self.univ, self.prof2))

    def test_program_cannot_use_a_foreign_department(self):
        response = self.client.post(reverse("courses:admin_program_create"), {
            "name": "Intrus", "department": self.other_dept.pk, "degree": "licence", "duration_years": 3,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Program.objects.filter(name="Intrus").exists())

    def test_duplicate_program_name_is_refused(self):
        response = self.client.post(reverse("courses:admin_program_create"), {
            "name": "licence informatique", "department": self.dept.pk, "degree": "licence", "duration_years": 3,
        })
        self.assertContains(response, "Une filière porte déjà ce nom.")

    def test_delete_program_with_subjects_is_blocked(self):
        response = self.client.post(
            reverse("courses:admin_program_delete", args=[self.program.pk]), follow=True,
        )
        self.assertTrue(Program.objects.filter(pk=self.program.pk).exists())
        self.assertTrue(any("matières" in m for m in messages_of(response)))

    def test_delete_program_detaches_its_classes(self):
        empty = Program.objects.create(department=self.dept, name="Licence Vide")
        self.school_class.study_program = empty
        self.school_class.save()
        self.client.post(reverse("courses:admin_program_delete", args=[empty.pk]))
        self.school_class.refresh_from_db()
        self.assertIsNone(self.school_class.study_program)


class SubjectTests(CoursesTestCase):
    def setUp(self):
        self.login(self.admin)

    def payload(self, **overrides):
        data = {
            "program": self.program.pk, "name": "Réseaux", "code": "inf510", "semester": 6,
            "coefficient": "2.5", "credits": 5, "hours_cm": 14, "hours_td": 7, "hours_tp": 7,
            "description": "", "is_active": "on",
        }
        data.update(overrides)
        return data

    def test_list_search_and_filters(self):
        url = reverse("courses:admin_subjects")
        response = self.client.get(url)
        self.assertContains(response, "INF501")
        self.assertContains(response, "GEN401")
        self.assertEqual(len(response.context["subjects"]), 3)
        response = self.client.get(url, {"q": "bases"})
        self.assertEqual([s.code for s in response.context["subjects"]], ["INF504"])
        response = self.client.get(url, {"filiere": self.program_gl.pk})
        self.assertEqual([s.code for s in response.context["subjects"]], ["GEN401"])
        response = self.client.get(url, {"semestre": 1})
        self.assertEqual([s.code for s in response.context["subjects"]], ["GEN401"])

    def test_create_subject(self):
        response = self.client.post(reverse("courses:admin_subject_create"), self.payload())
        self.assertRedirects(response, reverse("courses:admin_subjects"))
        subject = Subject.objects.get(code="INF510")
        self.assertEqual((subject.university, subject.semester, subject.total_hours), (self.univ, 6, 28))

    def test_semester_must_fit_the_program(self):
        response = self.client.post(
            reverse("courses:admin_subject_create"), self.payload(program=self.program_gl.pk, semester=6),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "compte 4 semestres")
        self.assertFalse(Subject.objects.filter(code="INF510").exists())

    def test_duplicate_code_and_name_are_refused(self):
        response = self.client.post(reverse("courses:admin_subject_create"), self.payload(code="inf501"))
        self.assertContains(response, "Une matière utilise déjà ce code.")
        response = self.client.post(
            reverse("courses:admin_subject_create"), self.payload(name="BASES de données"),
        )
        self.assertContains(response, "Cette filière a déjà une matière portant cet intitulé.")

    def test_update_and_archive_subject(self):
        url = reverse("courses:admin_subject_update", args=[self.subject2.pk])
        data = self.payload(name="Bases de données", code="INF504", semester=5)
        data.pop("is_active")  # case décochée : archivée
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse("courses:admin_subjects"))
        self.subject2.refresh_from_db()
        self.assertFalse(self.subject2.is_active)

    def test_archived_subjects_are_not_offered_for_new_assignments(self):
        self.subject2.is_active = False
        self.subject2.save()
        response = self.client.get(reverse("courses:admin_assignment_create"))
        offered = [subject.pk for subject in response.context["form"].fields["subject"].queryset]
        self.assertNotIn(self.subject2.pk, offered)
        self.assertIn(self.subject.pk, offered)

    def test_delete_subject_in_use_is_blocked(self):
        response = self.client.post(
            reverse("courses:admin_subject_delete", args=[self.subject.pk]), follow=True,
        )
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())
        self.assertTrue(any("Suppression impossible" in m for m in messages_of(response)))

    def test_delete_unused_subject(self):
        unused = Subject.objects.create(program=self.program, name="Libre", code="LIB1", semester=1)
        response = self.client.post(reverse("courses:admin_subject_delete", args=[unused.pk]))
        self.assertRedirects(response, reverse("courses:admin_subjects"))
        self.assertFalse(Subject.objects.filter(pk=unused.pk).exists())


class AssignmentTests(CoursesTestCase):
    def setUp(self):
        self.login(self.admin)

    def test_list_and_filters(self):
        url = reverse("courses:admin_assignments")
        response = self.client.get(url)
        self.assertEqual(len(response.context["assignments"]), 3)
        response = self.client.get(url, {"classe": self.class_gl.pk})
        self.assertEqual([a.pk for a in response.context["assignments"]], [self.assign_gl.pk])
        response = self.client.get(url, {"professeur": self.prof2.pk})
        self.assertEqual([a.pk for a in response.context["assignments"]], [self.assign2.pk])

    def test_create_assignment_for_a_preselected_class(self):
        url = reverse("courses:admin_assignment_create") + "?classe=%d" % self.class_gl.pk
        page = self.client.get(url)
        form = page.context["form"]
        self.assertEqual(form.fields["school_class"].initial, self.class_gl.pk)
        # La classe suit un master : seules les matières de ce master sont proposées.
        self.assertEqual([s.code for s in form.fields["subject"].queryset], ["GEN401"])
        second = Subject.objects.create(program=self.program_gl, name="Tests", code="GEN402", semester=2)
        response = self.client.post(url, {
            "school_class": self.class_gl.pk, "subject": second.pk, "professor": self.prof2.pk,
        })
        self.assertRedirects(
            response, reverse("courses:admin_assignments") + "?classe=%d" % self.class_gl.pk,
        )
        assignment = TeachingAssignment.objects.get(subject=second)
        self.assertEqual((assignment.university, assignment.professor), (self.univ, self.prof2))
        self.assertIn(self.prof2, self.class_gl.professors.all())

    def test_subject_of_another_program_is_refused(self):
        response = self.client.post(reverse("courses:admin_assignment_create"), {
            "school_class": self.school_class.pk, "subject": self.subject_gl.pk, "professor": self.prof.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "appartient à la filière")

    def test_duplicate_assignment_is_refused(self):
        response = self.client.post(reverse("courses:admin_assignment_create"), {
            "school_class": self.school_class.pk, "subject": self.subject.pk, "professor": self.prof.pk,
        })
        self.assertContains(response, "Cette matière a déjà un professeur dans cette classe")

    def test_foreign_objects_are_not_selectable(self):
        response = self.client.post(reverse("courses:admin_assignment_create"), {
            "school_class": self.other_class.pk, "subject": self.other_subject.pk, "professor": self.other_prof.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TeachingAssignment.objects.filter(university=self.other_univ).count(), 1)

    def test_inactive_professor_cannot_be_assigned(self):
        membership = self.prof2.membership
        membership.is_active = False
        membership.save()
        response = self.client.get(reverse("courses:admin_assignment_create"))
        self.assertNotIn(self.prof2, response.context["form"].fields["professor"].queryset)

    def test_replace_the_professor(self):
        course = self.make_course()
        self.publish(course)
        url = reverse("courses:admin_assignment_update", args=[self.assign.pk])
        page = self.client.get(url)
        self.assertTrue(page.context["form"].fields["school_class"].disabled)
        self.assertTrue(page.context["form"].fields["subject"].disabled)
        response = self.client.post(url, {"professor": self.prof2.pk})
        self.assertRedirects(response, reverse("courses:admin_assignments"))
        self.assign.refresh_from_db()
        self.assertEqual(self.assign.professor, self.prof2)
        # Les cours de l'ancien professeur ne sont plus publiés pour cette classe.
        self.assertFalse(CoursePublication.objects.filter(course=course).exists())

    def test_replacing_with_a_busy_professor_is_refused(self):
        make_slot(self.assign, weekday=2, start="14:00", end="15:30")
        make_slot(self.assign2, weekday=2, start="14:30", end="16:00")  # prof2 est déjà pris
        response = self.client.post(
            reverse("courses:admin_assignment_update", args=[self.assign.pk]), {"professor": self.prof2.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "déjà occupé")
        self.assign.refresh_from_db()
        self.assertEqual(self.assign.professor, self.prof)

    def test_delete_assignment_removes_its_slots_and_publications(self):
        make_slot(self.assign)
        course = self.make_course()
        self.publish(course)
        url = reverse("courses:admin_assignment_delete", args=[self.assign.pk])
        self.assertContains(self.client.get(url), "séances de l&#x27;emploi du temps")
        response = self.client.post(url)
        self.assertRedirects(response, reverse("courses:admin_assignments"))
        self.assertFalse(TeachingAssignment.objects.filter(pk=self.assign.pk).exists())
        self.assertFalse(ScheduleSlot.objects.exists())
        self.assertFalse(CoursePublication.objects.exists())


class TimetableTests(CoursesTestCase):
    def setUp(self):
        self.login(self.admin)

    def slot_payload(self, assignment=None, **overrides):
        data = {
            "assignment": (assignment or self.assign).pk, "session_type": "cm", "group": "",
            "weekday": 0, "start_time": "08:30", "end_time": "10:00", "room": "Amphi A",
        }
        data.update(overrides)
        return data

    def test_page_shows_each_class_with_its_sessions(self):
        make_slot(self.assign, weekday=1, start="10:15", end="11:45", room="B204")
        response = self.client.get(reverse("courses:admin_timetable"))
        self.assertContains(response, "Licence 3 Informatique")
        self.assertContains(response, "Master 1 Génie Logiciel")
        self.assertContains(response, "INF501")
        self.assertContains(response, "10:15 – 11:45")
        entries = {entry["school_class"].pk: entry for entry in response.context["timetables"]}
        self.assertEqual(entries[self.school_class.pk]["grid"]["slot_count"], 1)
        self.assertEqual(entries[self.class_gl.pk]["grid"]["slot_count"], 0)
        # Les affectations sans séance sont signalées.
        self.assertEqual(response.context["pending_count"], 2)
        self.assertEqual(response.context["slot_count"], 1)

    def test_page_filters_by_level_and_class(self):
        url = reverse("courses:admin_timetable")
        response = self.client.get(url, {"niveau": "Master 1"})
        self.assertEqual([e["school_class"].pk for e in response.context["timetables"]], [self.class_gl.pk])
        response = self.client.get(url, {"classe": self.school_class.pk})
        self.assertEqual([e["school_class"].pk for e in response.context["timetables"]], [self.school_class.pk])
        response = self.client.get(url, {"filiere": "Programme inconnu"})
        self.assertEqual(response.context["timetables"], [])

    def test_saturday_column_only_appears_when_needed(self):
        url = reverse("courses:admin_timetable")
        self.assertFalse(self.client.get(url).context["timetables"][0]["grid"]["show_saturday"])
        make_slot(self.assign, weekday=5, start="09:00", end="11:00")
        entry = next(
            e for e in self.client.get(url).context["timetables"] if e["school_class"].pk == self.school_class.pk
        )
        self.assertTrue(entry["grid"]["show_saturday"])

    def test_create_slot(self):
        url = reverse("courses:admin_slot_create") + "?classe=%d" % self.school_class.pk
        response = self.client.post(url, self.slot_payload())
        self.assertRedirects(response, reverse("courses:admin_timetable") + "?classe=%d" % self.school_class.pk)
        slot = ScheduleSlot.objects.get()
        self.assertEqual((slot.university, slot.weekday, slot.room), (self.univ, 0, "Amphi A"))

    def test_form_limits_assignments_to_the_selected_class(self):
        url = reverse("courses:admin_slot_create") + "?classe=%d" % self.class_gl.pk
        form = self.client.get(url).context["form"]
        self.assertEqual([a.pk for a in form.fields["assignment"].queryset], [self.assign_gl.pk])

    def test_conflicts_are_reported_to_the_admin(self):
        make_slot(self.assign, start="08:30", end="10:00", room="Amphi A")
        response = self.client.post(
            reverse("courses:admin_slot_create"),
            self.slot_payload(self.assign2, start_time="09:00", end_time="10:30"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La classe a déjà une séance sur ce créneau")
        self.assertContains(response, "La salle est déjà occupée")
        self.assertEqual(ScheduleSlot.objects.count(), 1)

    def test_inverted_times_are_refused(self):
        response = self.client.post(
            reverse("courses:admin_slot_create"), self.slot_payload(start_time="11:00", end_time="10:00"),
        )
        self.assertContains(response, "L&#x27;heure de fin doit être postérieure")
        self.assertFalse(ScheduleSlot.objects.exists())

    def test_group_session_for_one_group(self):
        response = self.client.post(
            reverse("courses:admin_slot_create"),
            self.slot_payload(session_type="tp", group=self.group_tp.pk, room="Labo 1"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ScheduleSlot.objects.get().group, self.group_tp)

    def test_group_of_another_class_is_refused(self):
        other_group = self.class_gl.groups.create(name="Autre classe")
        response = self.client.post(
            reverse("courses:admin_slot_create"), self.slot_payload(group=other_group.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ScheduleSlot.objects.exists())

    def test_update_slot_may_keep_its_own_time(self):
        slot = make_slot(self.assign, start="08:30", end="10:00", room="Amphi A")
        response = self.client.post(
            reverse("courses:admin_slot_update", args=[slot.pk]),
            self.slot_payload(end_time="10:30", room="Amphi B"),
        )
        self.assertEqual(response.status_code, 302)
        slot.refresh_from_db()
        self.assertEqual((slot.end_time.strftime("%H:%M"), slot.room), ("10:30", "Amphi B"))

    def test_delete_slot(self):
        slot = make_slot(self.assign)
        response = self.client.post(reverse("courses:admin_slot_delete", args=[slot.pk]))
        self.assertRedirects(response, reverse("courses:admin_timetable"))
        self.assertFalse(ScheduleSlot.objects.exists())


class CourseSupervisionTests(CoursesTestCase):
    def setUp(self):
        self.login(self.admin)
        self.course = self.make_course()
        chapter = Chapter.objects.create(course=self.course, title="Graphes", summary="Parcours")
        CourseMaterial.objects.create(course=self.course, chapter=chapter, title="Poly", file=pdf_upload())
        self.publish(self.course)

    def test_list_shows_status_and_content_counts(self):
        draft = self.make_course(professor=self.prof2, subject=self.subject2, title="Brouillon SQL")
        response = self.client.get(reverse("courses:admin_courses"))
        self.assertContains(response, "Cours d&#x27;algorithmique")
        self.assertEqual(response.context["stats"], {"courses": 2, "published": 1, "drafts": 1, "professors": 2})
        rows = {c.pk: c for c in response.context["courses"]}
        self.assertEqual((rows[self.course.pk].chapter_count, rows[self.course.pk].material_count), (1, 1))
        self.assertEqual(rows[draft.pk].published_count, 0)

    def test_list_filters(self):
        self.make_course(professor=self.prof2, subject=self.subject2, title="Brouillon SQL")
        url = reverse("courses:admin_courses")
        titles = lambda response: [c.title for c in response.context["courses"]]  # noqa: E731
        self.assertEqual(titles(self.client.get(url, {"statut": "publie"})), ["Cours d'algorithmique"])
        self.assertEqual(titles(self.client.get(url, {"statut": "brouillon"})), ["Brouillon SQL"])
        self.assertEqual(titles(self.client.get(url, {"professeur": self.prof2.pk})), ["Brouillon SQL"])
        self.assertEqual(titles(self.client.get(url, {"q": "algorithmique"})), ["Cours d'algorithmique"])

    def test_detail_is_read_only_supervision(self):
        response = self.client.get(reverse("courses:admin_course_detail", args=[self.course.pk]))
        self.assertContains(response, "Graphes")
        self.assertContains(response, "Poly")
        self.assertContains(response, "Licence 3 Informatique")
        self.assertNotContains(response, "Supprimer le cours")
