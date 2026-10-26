"""Portail étudiant : classe, matières et enseignants, cours publiés, supports
et emploi du temps. Un cours n'est visible que s'il est publié pour la classe."""

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Membership, SchoolClass, StudentGroup
from accounts.tenancy import Role
from courses.models import Chapter, CourseMaterial

from .base import CoursesTestCase, join, make_slot, make_user, pdf_upload


class StudentAccessTests(CoursesTestCase):
    def build(self):
        course = self.make_course()
        self.publish(course)
        return [
            reverse("courses:student_catalogue"), reverse("courses:student_timetable"),
            reverse("courses:student_course_materials"),
            reverse("courses:student_course_detail", args=[course.pk]),
        ]

    def test_anonymous_users_are_sent_to_the_login_page(self):
        for url in self.build():
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url), "%s?next=%s" % (settings.LOGIN_URL, url),
                    fetch_redirect_response=False,
                )

    def test_professors_and_admins_are_refused(self):
        urls = self.build()
        for user in (self.prof_user, self.admin):
            self.login(user)
            for url in urls:
                with self.subTest(user=user.email, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_student_reaches_every_page(self):
        urls = self.build()
        self.login(self.student_user)
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_pending_student_is_sent_back_to_the_university_chooser(self):
        pending = make_user("attente@ut.test")
        Membership.objects.create(user=pending, university=self.univ, role=Role.STUDENT, is_active=False)
        self.login(pending)
        for url in self.build()[:3]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse("portal:university_switch"))


class CatalogueTests(CoursesTestCase):
    def setUp(self):
        self.login(self.student_user)
        self.url = reverse("courses:student_catalogue")

    def rows(self, response):
        return {row["subject"].code: row for row in response.context["rows"]}

    def test_subjects_and_teachers_of_the_class_are_listed_even_without_a_course(self):
        response = self.client.get(self.url)
        rows = self.rows(response)
        self.assertEqual(sorted(rows), ["INF501", "INF504"])  # GEN401 appartient à une autre classe
        self.assertEqual([p.pk for p in rows["INF501"]["professors"]], [self.prof.pk])
        self.assertEqual([p.pk for p in rows["INF504"]["professors"]], [self.prof2.pk])
        self.assertEqual(rows["INF501"]["courses"], [])
        self.assertContains(response, "Aucun cours publié pour le moment")
        self.assertContains(response, "Hélène Vasseur")
        self.assertContains(response, "Mariam Traoré")
        self.assertEqual(response.context["school_class"], self.school_class)
        stats = response.context["stats"]
        self.assertEqual((stats["subjects"], stats["courses"], stats["professors"], stats["credits"]), (2, 0, 2, 10))

    def test_only_published_courses_are_visible(self):
        course = self.make_course(title="Graphes et complexité")
        self.assertNotContains(self.client.get(self.url), "Graphes et complexité")
        self.publish(course)
        response = self.client.get(self.url)
        self.assertContains(response, "Graphes et complexité")
        self.assertContains(response, reverse("courses:student_course_detail", args=[course.pk]))
        self.assertEqual([c.pk for c in self.rows(response)["INF501"]["courses"]], [course.pk])
        self.publish(course, published=False)
        self.assertNotContains(self.client.get(self.url), "Graphes et complexité")

    def test_each_course_appears_under_its_subject_with_its_professor(self):
        first = self.make_course(title="Cours Vasseur")
        second = self.make_course(professor=self.prof2, subject=self.subject2, title="Cours Traoré")
        self.publish(first)
        self.publish(second)
        rows = self.rows(self.client.get(self.url))
        self.assertEqual([c.title for c in rows["INF501"]["courses"]], ["Cours Vasseur"])
        self.assertEqual([c.title for c in rows["INF504"]["courses"]], ["Cours Traoré"])
        self.assertEqual(rows["INF504"]["courses"][0].professor, self.prof2)

    def test_course_published_for_another_class_stays_hidden(self):
        course = self.make_course(subject=self.subject_gl, title="Architecture du master")
        self.publish(course, school_class=self.class_gl)
        self.assertNotContains(self.client.get(self.url), "Architecture du master")

    def test_content_counts_are_shown(self):
        course = self.make_course()
        chapter = Chapter.objects.create(course=course, title="Un")
        CourseMaterial.objects.create(course=course, chapter=chapter, file=pdf_upload())
        self.publish(course)
        listed = self.rows(self.client.get(self.url))["INF501"]["courses"][0]
        self.assertEqual((listed.chapter_count, listed.material_count), (1, 1))
        self.assertIsNotNone(listed.published_on)

    def test_student_without_a_class_gets_an_explanation(self):
        self.login(self.student3_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["school_class"])
        self.assertContains(response, "Vous n'êtes rattaché à aucune classe")

    def test_student_of_another_university_sees_nothing_of_this_one(self):
        self.publish(self.make_course(title="Cours confidentiel"))
        self.login(self.other_student_user)
        response = self.client.get(self.url)
        self.assertNotContains(response, "Cours confidentiel")
        self.assertIsNone(response.context["school_class"])

    def test_student_in_two_classes_can_switch(self):
        group = StudentGroup.objects.create(school_class=self.class_gl, name="Groupe GL")
        group.students.add(self.student)
        old_class = SchoolClass.objects.create(
            university=self.univ, name="Ancienne promo", academic_year="2023-2024", study_program=self.program,
        )
        old_group = StudentGroup.objects.create(school_class=old_class, name="Ancien groupe")
        old_group.students.add(self.student)
        response = self.client.get(self.url)
        self.assertEqual(
            [c.pk for c in response.context["student_classes"]],
            [self.school_class.pk, self.class_gl.pk, old_class.pk],  # année la plus récente d'abord, puis nom
        )
        self.assertContains(response, "Choix de la classe")
        self.assertEqual(response.context["school_class"], self.school_class)
        self.assertEqual(self.client.get(self.url, {"classe": self.class_gl.pk}).context["school_class"], self.class_gl)
        # Une classe qui n'est pas la sienne est ignorée.
        fallback = self.client.get(self.url, {"classe": self.other_class.pk}).context["school_class"]
        self.assertEqual(fallback, self.school_class)

    def test_no_class_switcher_for_a_single_class(self):
        self.assertNotContains(self.client.get(self.url), "Choix de la classe")


class CourseDetailTests(CoursesTestCase):
    def setUp(self):
        self.course = self.make_course(title="Graphes", description="Parcours et plus courts chemins")
        self.chapter = Chapter.objects.create(course=self.course, title="Parcours en largeur", summary="BFS")
        self.material = CourseMaterial.objects.create(
            course=self.course, chapter=self.chapter, title="Polycopié", file=pdf_upload(),
        )
        self.general = CourseMaterial.objects.create(course=self.course, title="Bibliographie", file=pdf_upload("bib.pdf"))
        self.url = reverse("courses:student_course_detail", args=[self.course.pk])

    def test_published_course_shows_its_content(self):
        self.publish(self.course)
        make_slot(self.assign, weekday=0, start="08:30", end="10:00", room="Amphi A")
        self.login(self.student_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for expected in ("Graphes", "Parcours et plus courts chemins", "Parcours en largeur", "Polycopié",
                         "Bibliographie", "Hélène Vasseur", "Amphi A", "Licence 3 Informatique"):
            self.assertContains(response, expected)
        self.assertEqual(response.context["material_total"], 2)
        self.assertEqual([m.pk for m in response.context["general_materials"]], [self.general.pk])

    def test_visible_to_every_student_of_the_class(self):
        self.publish(self.course)
        self.login(self.student2_user)  # autre groupe de la même classe
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_unpublished_course_is_not_found(self):
        self.login(self.student_user)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.publish(self.course, published=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_course_of_another_class_is_not_found(self):
        self.publish(self.course)
        group = StudentGroup.objects.create(school_class=self.class_gl, name="Groupe GL")
        outsider = make_user("autre@ut.test")
        profile = join(outsider, self.univ, Role.STUDENT).student_profile
        group.students.add(profile)
        self.login(outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_students_without_class_or_from_another_university_get_404(self):
        self.publish(self.course)
        for user in (self.student3_user, self.other_student_user):
            self.login(user)
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_only_sessions_of_the_students_own_groups_are_listed(self):
        self.publish(self.course)
        make_slot(self.assign, weekday=1, start="10:15", end="11:45", session_type="td", group=self.group_td, room="Salle TD")
        make_slot(self.assign, weekday=2, start="10:15", end="11:45", session_type="tp", group=self.group_tp, room="Salle TP")
        self.login(self.student_user)  # groupe TD A
        response = self.client.get(self.url)
        self.assertContains(response, "Salle TD")
        self.assertNotContains(response, "Salle TP")


class MaterialLibraryTests(CoursesTestCase):
    def setUp(self):
        self.course = self.make_course(title="Graphes")
        self.hidden = self.make_course(professor=self.prof2, subject=self.subject2, title="SQL (non publié)")
        self.publish(self.course)
        CourseMaterial.objects.create(course=self.course, title="Poly graphes", file=pdf_upload())
        CourseMaterial.objects.create(course=self.course, title="Capsule vidéo", file=SimpleUploadedFile("v.mp4", b"video"))
        CourseMaterial.objects.create(course=self.hidden, title="Poly SQL", file=pdf_upload("sql.pdf"))
        self.login(self.student_user)
        self.url = reverse("courses:student_course_materials")

    def titles(self, response):
        return sorted(m.title for m in response.context["materials"])

    def test_only_materials_of_published_courses_are_listed(self):
        response = self.client.get(self.url)
        self.assertEqual(self.titles(response), ["Capsule vidéo", "Poly graphes"])
        self.assertNotContains(response, "Poly SQL")
        stats = response.context["stats"]
        self.assertEqual((stats["materials"], stats["subjects"], stats["media"], stats["recent"]), (2, 1, 1, 2))

    def test_publishing_the_other_course_adds_its_materials(self):
        self.publish(self.hidden)
        self.assertEqual(self.titles(self.client.get(self.url)), ["Capsule vidéo", "Poly SQL", "Poly graphes"])
        self.publish(self.hidden, published=False)
        self.assertNotIn("Poly SQL", self.titles(self.client.get(self.url)))

    def test_filters_and_search(self):
        self.publish(self.hidden)
        self.assertEqual(self.titles(self.client.get(self.url, {"type": "video"})), ["Capsule vidéo"])
        self.assertEqual(self.titles(self.client.get(self.url, {"matiere": self.subject2.pk})), ["Poly SQL"])
        self.assertEqual(self.titles(self.client.get(self.url, {"q": "capsule"})), ["Capsule vidéo"])

    def test_student_without_a_class_sees_an_empty_library(self):
        self.login(self.student3_user)
        response = self.client.get(self.url)
        self.assertEqual(self.titles(response), [])
        self.assertContains(response, "Vous n'êtes rattaché à aucune classe")


class StudentTimetableTests(CoursesTestCase):
    def setUp(self):
        self.login(self.student_user)  # groupe TD A de la L3
        self.url = reverse("courses:student_timetable")

    def test_class_wide_and_own_group_sessions_only(self):
        make_slot(self.assign, weekday=0, start="08:30", end="10:00", room="Amphi A")  # toute la classe
        make_slot(self.assign2, weekday=1, start="10:15", end="11:45", session_type="td", group=self.group_td, room="Salle TD")
        make_slot(self.assign2, weekday=1, start="10:15", end="11:45", session_type="tp", group=self.group_tp, room="Salle TP")
        make_slot(self.assign_gl, weekday=2, start="14:00", end="16:00", room="Salle Master")  # autre classe
        response = self.client.get(self.url)
        grid = response.context["grid"]
        self.assertEqual(grid["slot_count"], 2)
        self.assertEqual(grid["total_label"], "3 h")
        self.assertContains(response, "Amphi A")
        self.assertContains(response, "Salle TD")
        self.assertNotContains(response, "Salle TP")
        self.assertNotContains(response, "Salle Master")
        self.assertEqual(response.context["professor_count"], 2)

    def test_the_other_group_sees_its_own_sessions(self):
        make_slot(self.assign2, weekday=1, start="10:15", end="11:45", session_type="tp", group=self.group_tp, room="Salle TP")
        self.login(self.student2_user)
        self.assertContains(self.client.get(self.url), "Salle TP")

    def test_sessions_show_subject_type_room_and_teacher(self):
        make_slot(self.assign, weekday=3, start="13:30", end="15:00", room="B204", session_type="tp")
        response = self.client.get(self.url)
        for expected in ("INF501", "Algorithmique avancée", "TP", "B204", "13:30 – 15:00", "Hélène Vasseur"):
            self.assertContains(response, expected)

    def test_grid_has_one_column_per_weekday(self):
        days = self.client.get(self.url).context["grid"]["days"]
        self.assertEqual([day["label"] for day in days], ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"])
        self.assertEqual(sum(1 for day in days if day["is_today"]) <= 1, True)

    def test_student_without_a_class_gets_an_explanation(self):
        self.login(self.student3_user)
        response = self.client.get(self.url)
        self.assertEqual(response.context["grid"]["slot_count"], 0)
        self.assertContains(response, "Vous n'êtes rattaché à aucune classe")

    def test_empty_timetable_message(self):
        response = self.client.get(self.url)
        self.assertContains(response, "n'est pas encore publié")
        self.assertIsNone(response.context["next_session"])

    def test_other_university_is_isolated(self):
        make_slot(self.other_assign, weekday=0, start="08:00", end="09:00", room="Salle Voisine")
        self.assertNotContains(self.client.get(self.url), "Salle Voisine")
