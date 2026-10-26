"""Portail professeur : ses cours, chapitres, supports, la publication par classe,
ses matières et son emploi du temps."""

import os
from unittest import mock

from django.conf import settings
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import SchoolClass
from accounts.tenancy import Role
from courses import files
from courses.models import Chapter, Course, CourseMaterial, CoursePublication, TeachingAssignment

from .base import CoursesTestCase, join, make_slot, make_user, pdf_upload


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


class ProfAccessTests(CoursesTestCase):
    def build(self):
        """Pages sans objet (``pages``) et pages portant sur un cours précis (``content``)."""
        course = self.make_course()
        chapter = Chapter.objects.create(course=course, title="Un")
        material = CourseMaterial.objects.create(course=course, chapter=chapter, file=pdf_upload())
        pages = [
            reverse("courses:prof_course"), reverse("courses:prof_course_create"),
            reverse("courses:prof_subjects"), reverse("courses:prof_timetable"),
            reverse("courses:prof_course_materials"), reverse("courses:prof_material_create"),
        ]
        content = [
            reverse("courses:prof_course_detail", args=[course.pk]),
            reverse("courses:prof_course_update", args=[course.pk]),
            reverse("courses:prof_course_delete", args=[course.pk]),
            reverse("courses:prof_chapter_create", args=[course.pk]),
            reverse("courses:prof_chapter_update", args=[course.pk, chapter.pk]),
            reverse("courses:prof_chapter_delete", args=[course.pk, chapter.pk]),
            reverse("courses:prof_material_update", args=[material.pk]),
            reverse("courses:prof_material_delete", args=[material.pk]),
        ]
        return pages, content

    def test_anonymous_users_are_sent_to_the_login_page(self):
        pages, content = self.build()
        for url in pages + content:
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url), "%s?next=%s" % (settings.LOGIN_URL, url),
                    fetch_redirect_response=False,
                )

    def test_admins_and_students_are_refused(self):
        pages, content = self.build()
        for user in (self.admin, self.student_user):
            self.login(user)
            for url in pages + content:
                with self.subTest(user=user.email, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_professor_reaches_every_page(self):
        pages, content = self.build()
        self.login(self.prof_user)
        for url in pages + content:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_colleagues_and_foreign_professors_only_get_their_own_pages(self):
        pages, content = self.build()
        for user in (self.prof2_user, self.other_prof_user):
            self.login(user)
            for url in pages:
                with self.subTest(user=user.email, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)
            for url in content:
                with self.subTest(user=user.email, url=url):
                    self.assertEqual(self.client.get(url).status_code, 404)


class ProfCourseTests(CoursesTestCase):
    def setUp(self):
        self.login(self.prof_user)

    def test_list_shows_only_my_courses(self):
        mine = self.make_course(title="Mon cours")
        self.make_course(professor=self.prof2, subject=self.subject2, title="Cours d'un collègue")
        response = self.client.get(reverse("courses:prof_course"))
        self.assertEqual([c.pk for c in response.context["courses"]], [mine.pk])
        self.assertContains(response, "Mon cours")
        self.assertNotContains(response, "Cours d&#x27;un collègue")
        self.assertEqual(response.context["stats"]["courses"], 1)
        self.assertTrue(response.context["can_create"])

    def test_list_flags_classes_still_to_publish(self):
        course = self.make_course()
        response = self.client.get(reverse("courses:prof_course"))
        row = response.context["courses"][0]
        self.assertEqual((row.assigned_class_count, row.published_count, row.to_publish), (1, 0, 1))
        self.publish(course)
        row = self.client.get(reverse("courses:prof_course")).context["courses"][0]
        self.assertEqual((row.published_count, row.to_publish), (1, 0))

    def test_list_search_and_filter(self):
        self.make_course(title="Graphes")
        self.make_course(subject=self.subject_gl, title="Patrons de conception")
        url = reverse("courses:prof_course")
        titles = lambda response: [c.title for c in response.context["courses"]]  # noqa: E731
        self.assertEqual(titles(self.client.get(url, {"q": "graph"})), ["Graphes"])
        self.assertEqual(titles(self.client.get(url, {"matiere": self.subject_gl.pk})), ["Patrons de conception"])

    def test_create_course_for_a_taught_subject(self):
        response = self.client.post(reverse("courses:prof_course_create"), {
            "subject": self.subject.pk, "title": "Théorie des graphes", "description": "Parcours, plus courts chemins.",
        })
        course = Course.objects.get(title="Théorie des graphes")
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[course.pk]))
        self.assertEqual((course.professor, course.university, course.subject), (self.prof, self.univ, self.subject))

    def test_only_taught_subjects_are_offered(self):
        form = self.client.get(reverse("courses:prof_course_create")).context["form"]
        self.assertEqual(
            sorted(subject.code for subject in form.fields["subject"].queryset), ["GEN401", "INF501"],
        )

    def test_course_for_a_subject_taught_by_someone_else_is_refused(self):
        response = self.client.post(reverse("courses:prof_course_create"), {
            "subject": self.subject2.pk, "title": "Intrus", "description": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Course.objects.filter(title="Intrus").exists())

    def test_preselected_subject_from_my_subjects_page(self):
        response = self.client.get(reverse("courses:prof_course_create") + "?matiere=%d" % self.subject_gl.pk)
        self.assertEqual(response.context["form"].initial["subject"], self.subject_gl.pk)

    def test_professor_without_assignment_is_redirected_with_an_explanation(self):
        newcomer = make_user("nouveau@ut.test", "Nina", "Nouvelle")
        join(newcomer, self.univ, Role.PROFESSOR)
        self.login(newcomer)
        response = self.client.get(reverse("courses:prof_course_create"))
        self.assertRedirects(response, reverse("courses:prof_course"))
        self.assertTrue(any("Aucune matière ne vous est encore affectée" in m for m in messages_of(response)))
        page = self.client.get(reverse("courses:prof_course"))
        self.assertFalse(page.context["can_create"])
        self.assertContains(page, "Aucune matière ne vous est encore affectée")

    def test_duplicate_title_is_refused(self):
        self.make_course(title="Introduction")
        response = self.client.post(reverse("courses:prof_course_create"), {
            "subject": self.subject.pk, "title": "introduction", "description": "",
        })
        self.assertContains(response, "Vous avez déjà un cours portant ce titre")

    def test_detail_lists_classes_and_scheduled_sessions(self):
        course = self.make_course()
        make_slot(self.assign, weekday=2, start="14:00", end="15:30", room="B204")
        make_slot(self.assign2, weekday=3, start="08:30", end="10:00")  # séance d'une autre matière
        response = self.client.get(reverse("courses:prof_course_detail", args=[course.pk]))
        self.assertEqual([row["school_class"].pk for row in response.context["class_rows"]], [self.school_class.pk])
        self.assertEqual(response.context["published_total"], 0)
        self.assertEqual(len(response.context["slots"]), 1)
        self.assertContains(response, "Mercredi · 14:00 – 15:30")
        self.assertContains(response, "Publier")

    def test_update_course(self):
        course = self.make_course()
        response = self.client.post(reverse("courses:prof_course_update", args=[course.pk]), {
            "subject": self.subject.pk, "title": "Titre corrigé", "description": "Nouvelle présentation",
        })
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[course.pk]))
        course.refresh_from_db()
        self.assertEqual((course.title, course.description), ("Titre corrigé", "Nouvelle présentation"))

    def test_delete_course_removes_content_and_files(self):
        course = self.make_course()
        chapter = Chapter.objects.create(course=course, title="Un")
        material = CourseMaterial.objects.create(course=course, chapter=chapter, file=pdf_upload())
        path = material.file.path
        self.publish(course)
        url = reverse("courses:prof_course_delete", args=[course.pk])
        self.assertContains(self.client.get(url), "chapitres")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)
        self.assertRedirects(response, reverse("courses:prof_course"))
        self.assertFalse(Course.objects.exists())
        self.assertFalse(CoursePublication.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_other_professors_courses_cannot_be_edited_or_deleted(self):
        course = self.make_course(professor=self.prof2, subject=self.subject2, title="Cours du collègue")
        for name in ("prof_course_update", "prof_course_delete", "prof_course_detail"):
            with self.subTest(name=name):
                url = reverse("courses:%s" % name, args=[course.pk])
                self.assertEqual(self.client.get(url).status_code, 404)
                if name != "prof_course_detail":
                    self.assertEqual(self.client.post(url, {"title": "x"}).status_code, 404)
        course.refresh_from_db()
        self.assertEqual(course.title, "Cours du collègue")


class PublicationTests(CoursesTestCase):
    def setUp(self):
        self.login(self.prof_user)
        self.course = self.make_course()

    def url(self, school_class=None):
        return reverse("courses:prof_course_publication", args=[self.course.pk, (school_class or self.school_class).pk])

    def test_publish_then_withdraw_for_a_class(self):
        response = self.client.post(self.url(), {"action": "publier"})
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[self.course.pk]))
        publication = CoursePublication.objects.get(course=self.course, school_class=self.school_class)
        self.assertTrue(publication.is_published)
        self.assertIsNotNone(publication.published_at)
        self.assertEqual(publication.university, self.univ)

        response = self.client.post(self.url(), {"action": "retirer"})
        publication.refresh_from_db()
        self.assertFalse(publication.is_published)
        self.assertIsNone(publication.published_at)
        self.assertEqual(CoursePublication.objects.count(), 1)  # la ligne est conservée

    def test_publishing_twice_keeps_a_single_publication(self):
        self.client.post(self.url(), {"action": "publier"})
        self.client.post(self.url(), {"action": "publier"})
        self.assertEqual(CoursePublication.objects.count(), 1)

    def test_cannot_publish_for_a_class_where_the_subject_is_not_taught(self):
        response = self.client.post(self.url(self.class_gl), {"action": "publier"}, follow=True)
        self.assertFalse(CoursePublication.objects.exists())
        self.assertTrue(any("n'enseignez pas cette matière" in m for m in messages_of(response)))

    def test_cannot_publish_for_a_foreign_class(self):
        response = self.client.post(self.url(self.other_class), {"action": "publier"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CoursePublication.objects.exists())

    def test_publication_requires_post(self):
        self.assertEqual(self.client.get(self.url()).status_code, 405)

    def test_only_the_author_can_publish(self):
        self.login(self.prof2_user)
        self.assertEqual(self.client.post(self.url(), {"action": "publier"}).status_code, 404)
        self.login(self.admin)
        self.assertEqual(self.client.post(self.url(), {"action": "publier"}).status_code, 403)
        self.assertFalse(CoursePublication.objects.exists())

    def test_detail_reflects_the_publication_state(self):
        detail = reverse("courses:prof_course_detail", args=[self.course.pk])
        self.assertEqual(self.client.get(detail).context["published_total"], 0)
        self.client.post(self.url(), {"action": "publier"})
        response = self.client.get(detail)
        self.assertEqual(response.context["published_total"], 1)
        self.assertContains(response, "Retirer")

    def test_classes_listed_are_exactly_those_the_professor_teaches(self):
        second_class = SchoolClass.objects.create(
            university=self.univ, name="L3 Informatique (groupe B)", academic_year="2025-2026",
            study_program=self.program,
        )
        TeachingAssignment.objects.create(school_class=second_class, subject=self.subject, professor=self.prof)
        response = self.client.get(reverse("courses:prof_course_detail", args=[self.course.pk]))
        listed = {row["school_class"].pk for row in response.context["class_rows"]}
        self.assertEqual(listed, {self.school_class.pk, second_class.pk})


class ChapterTests(CoursesTestCase):
    def setUp(self):
        self.login(self.prof_user)
        self.course = self.make_course()

    def titles(self):
        return [chapter.title for chapter in Chapter.objects.filter(course=self.course)]

    def test_create_chapters_in_order(self):
        url = reverse("courses:prof_chapter_create", args=[self.course.pk])
        for title in ("Graphes", "Complexité"):
            response = self.client.post(url, {"title": title, "summary": ""})
            self.assertRedirects(response, reverse("courses:prof_course_detail", args=[self.course.pk]))
        self.assertEqual(self.titles(), ["Graphes", "Complexité"])
        self.assertEqual([c.order for c in Chapter.objects.filter(course=self.course)], [1, 2])

    def test_update_chapter(self):
        chapter = Chapter.objects.create(course=self.course, title="Brouillon")
        response = self.client.post(
            reverse("courses:prof_chapter_update", args=[self.course.pk, chapter.pk]),
            {"title": "Graphes et arbres", "summary": "Parcours"},
        )
        self.assertEqual(response.status_code, 302)
        chapter.refresh_from_db()
        self.assertEqual((chapter.title, chapter.summary), ("Graphes et arbres", "Parcours"))

    def test_move_chapters(self):
        first = Chapter.objects.create(course=self.course, title="A")
        second = Chapter.objects.create(course=self.course, title="B")
        third = Chapter.objects.create(course=self.course, title="C")
        self.client.post(reverse("courses:prof_chapter_up", args=[self.course.pk, third.pk]))
        self.assertEqual(self.titles(), ["A", "C", "B"])
        self.client.post(reverse("courses:prof_chapter_down", args=[self.course.pk, first.pk]))
        self.assertEqual(self.titles(), ["C", "A", "B"])
        # Aux extrémités, rien ne bouge mais l'ordre reste continu.
        self.client.post(reverse("courses:prof_chapter_up", args=[self.course.pk, third.pk]))
        self.client.post(reverse("courses:prof_chapter_down", args=[self.course.pk, second.pk]))
        self.assertEqual(self.titles(), ["C", "A", "B"])
        self.assertEqual([c.order for c in Chapter.objects.filter(course=self.course)], [1, 2, 3])

    def test_move_requires_post(self):
        chapter = Chapter.objects.create(course=self.course, title="A")
        self.assertEqual(
            self.client.get(reverse("courses:prof_chapter_up", args=[self.course.pk, chapter.pk])).status_code, 405,
        )

    def test_delete_chapter_warns_about_and_removes_its_materials(self):
        chapter = Chapter.objects.create(course=self.course, title="A")
        material = CourseMaterial.objects.create(course=self.course, chapter=chapter, file=pdf_upload())
        path = material.file.path
        url = reverse("courses:prof_chapter_delete", args=[self.course.pk, chapter.pk])
        self.assertContains(self.client.get(url), "supports de cours rattachés")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[self.course.pk]))
        self.assertFalse(Chapter.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_chapter_of_another_course_is_not_reachable_through_my_course(self):
        other = self.make_course(subject=self.subject_gl, title="Autre cours")
        foreign = Chapter.objects.create(course=other, title="Ailleurs")
        url = reverse("courses:prof_chapter_update", args=[self.course.pk, foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_other_professor_cannot_add_chapters(self):
        self.login(self.prof2_user)
        url = reverse("courses:prof_chapter_create", args=[self.course.pk])
        self.assertEqual(self.client.post(url, {"title": "Intrus"}).status_code, 404)
        self.assertFalse(Chapter.objects.exists())


class MaterialTests(CoursesTestCase):
    def setUp(self):
        self.login(self.prof_user)
        self.course = self.make_course()
        self.chapter = Chapter.objects.create(course=self.course, title="Graphes")

    def create_url(self):
        return reverse("courses:prof_material_create")

    def post_material(self, upload, **extra):
        data = {"course": self.course.pk, "chapter": self.chapter.pk, "title": "Poly", "description": "", "file": upload}
        data.update(extra)
        return self.client.post(self.create_url(), data)

    def test_upload_a_pdf_into_a_chapter(self):
        response = self.post_material(pdf_upload("poly graphes.pdf"))
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[self.course.pk]))
        material = CourseMaterial.objects.get()
        self.assertEqual(
            (material.course, material.chapter, material.title, material.material_type, material.uploaded_by),
            (self.course, self.chapter, "Poly", files.PDF, self.prof_user),
        )
        self.assertEqual(material.original_name, "poly graphes.pdf")
        self.assertTrue(os.path.isfile(material.file.path))

    def test_upload_form_is_preselected_from_the_course_page(self):
        url = self.create_url() + "?cours=%d&chapitre=%d" % (self.course.pk, self.chapter.pk)
        form = self.client.get(url).context["form"]
        self.assertEqual(form.fields["course"].initial, self.course.pk)
        self.assertEqual(form.initial["chapter"], self.chapter.pk)
        self.assertEqual([c.pk for c in form.fields["chapter"].queryset], [self.chapter.pk])

    def test_each_supported_type_is_detected(self):
        samples = {
            "cours.pptx": files.PRESENTATION, "demo.mp4": files.VIDEO,
            "podcast.mp3": files.AUDIO, "fiche.pdf": files.PDF,
        }
        for name, expected in samples.items():
            with self.subTest(name=name):
                content = pdf_upload(name).read() if name.endswith(".pdf") else b"data"
                self.post_material(SimpleUploadedFile(name, content), title=name)
        detected = dict(CourseMaterial.objects.values_list("original_name", "material_type"))
        self.assertEqual(detected, samples)

    def test_unsupported_formats_are_refused(self):
        for name in ("script.exe", "page.html", "image.svg", "archive.zip"):
            with self.subTest(name=name):
                response = self.post_material(SimpleUploadedFile(name, b"contenu"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Format non pris en charge")
        self.assertFalse(CourseMaterial.objects.exists())

    def test_fake_pdf_and_empty_files_are_refused(self):
        response = self.post_material(SimpleUploadedFile("faux.pdf", b"<html><script>alert(1)</script></html>"))
        self.assertContains(response, "n&#x27;est pas un PDF valide")
        response = self.post_material(SimpleUploadedFile("vide.pdf", b""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CourseMaterial.objects.exists())

    def test_size_limit_depends_on_the_type(self):
        rules = {key: dict(rule) for key, rule in files.TYPE_RULES.items()}
        rules[files.PDF]["max_size"] = 10
        with mock.patch.dict(files.TYPE_RULES, rules):
            response = self.post_material(pdf_upload("gros.pdf"))
        self.assertContains(response, "Fichier trop volumineux")
        self.assertFalse(CourseMaterial.objects.exists())

    def test_cannot_upload_into_someone_elses_course_or_chapter(self):
        foreign_course = self.make_course(professor=self.prof2, subject=self.subject2, title="Collègue")
        foreign_chapter = Chapter.objects.create(course=foreign_course, title="Chez le collègue")
        response = self.post_material(pdf_upload(), course=foreign_course.pk, chapter="")
        self.assertEqual(response.status_code, 200)
        response = self.post_material(pdf_upload(), chapter=foreign_chapter.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CourseMaterial.objects.exists())

    def test_chapter_must_belong_to_the_selected_course(self):
        other = self.make_course(subject=self.subject_gl, title="Autre cours")
        response = self.post_material(pdf_upload(), course=other.pk)  # chapitre du premier cours
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CourseMaterial.objects.exists())

    def test_update_without_new_file_keeps_the_file(self):
        self.post_material(pdf_upload("a.pdf"))
        material = CourseMaterial.objects.get()
        path = material.file.path
        response = self.client.post(reverse("courses:prof_material_update", args=[material.pk]), {
            "chapter": "", "title": "Poly corrigé", "description": "Version 2",
        })
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[self.course.pk]))
        material.refresh_from_db()
        self.assertEqual((material.title, material.chapter, material.file.path), ("Poly corrigé", None, path))
        self.assertTrue(os.path.isfile(path))

    def test_update_with_new_file_replaces_and_removes_the_old_one(self):
        self.post_material(pdf_upload("a.pdf"))
        material = CourseMaterial.objects.get()
        old_path = material.file.path
        new_pdf = SimpleUploadedFile("b.pdf", pdf_upload().read() + b"plus de contenu")
        response = self.client.post(reverse("courses:prof_material_update", args=[material.pk]), {
            "chapter": self.chapter.pk, "title": "Poly", "description": "", "file": new_pdf,
        })
        self.assertEqual(response.status_code, 302)
        material.refresh_from_db()
        self.assertEqual(material.original_name, "b.pdf")
        self.assertNotEqual(material.file.path, old_path)
        self.assertTrue(os.path.isfile(material.file.path))
        self.assertFalse(os.path.exists(old_path))

    def test_delete_material_removes_the_file(self):
        self.post_material(pdf_upload())
        material = CourseMaterial.objects.get()
        path = material.file.path
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("courses:prof_material_delete", args=[material.pk]))
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[self.course.pk]))
        self.assertFalse(CourseMaterial.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_other_professor_cannot_touch_my_material(self):
        self.post_material(pdf_upload())
        material = CourseMaterial.objects.get()
        self.login(self.prof2_user)
        for name in ("prof_material_update", "prof_material_delete"):
            url = reverse("courses:%s" % name, args=[material.pk])
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(CourseMaterial.objects.exists())

    def test_library_lists_only_my_materials_and_filters(self):
        self.post_material(pdf_upload("a.pdf"), title="Poly graphes")
        self.post_material(SimpleUploadedFile("film.mp4", b"video"), title="Capsule vidéo")
        foreign = self.make_course(professor=self.prof2, subject=self.subject2, title="Collègue")
        CourseMaterial.objects.create(course=foreign, title="Confidentiel", file=pdf_upload("c.pdf"))
        url = reverse("courses:prof_course_materials")
        titles = lambda response: sorted(m.title for m in response.context["materials"])  # noqa: E731
        self.assertEqual(titles(self.client.get(url)), ["Capsule vidéo", "Poly graphes"])
        self.assertEqual(titles(self.client.get(url, {"type": "video"})), ["Capsule vidéo"])
        self.assertEqual(titles(self.client.get(url, {"q": "graphes"})), ["Poly graphes"])
        self.assertEqual(titles(self.client.get(url, {"cours": self.course.pk})), ["Capsule vidéo", "Poly graphes"])
        stats = self.client.get(url).context["stats"]
        self.assertEqual((stats["materials"], stats["pdf"], stats["media"]), (2, 1, 1))
        self.assertNotContains(self.client.get(url), "Confidentiel")


class SubjectsAndTimetableTests(CoursesTestCase):
    def setUp(self):
        self.login(self.prof_user)

    def test_subjects_page_lists_my_assignments_only(self):
        response = self.client.get(reverse("courses:prof_subjects"))
        codes = [row["subject"].code for row in response.context["rows"]]
        self.assertEqual(sorted(codes), ["GEN401", "INF501"])
        self.assertEqual(response.context["stats"]["subjects"], 2)
        self.assertEqual(response.context["stats"]["classes"], 2)
        self.assertEqual(response.context["stats"]["hours"], 54)  # INF501 : 21 + 21 + 12
        self.assertNotContains(response, "INF504")

    def test_subjects_page_shows_students_and_courses(self):
        course = self.make_course()
        self.publish(course)
        response = self.client.get(reverse("courses:prof_subjects"))
        row = next(r for r in response.context["rows"] if r["subject"].code == "INF501")
        self.assertEqual(row["students"], 2)  # TD A et TP B
        self.assertEqual([c.pk for c in row["courses"]], [course.pk])
        self.assertEqual(row["courses"][0].published_total, 1)

    def test_timetable_shows_only_my_sessions(self):
        make_slot(self.assign, weekday=0, start="08:30", end="10:00", room="Amphi A")
        make_slot(self.assign_gl, weekday=2, start="14:00", end="16:00", session_type="tp")
        make_slot(self.assign2, weekday=1, start="08:30", end="10:00")  # séance de la collègue
        response = self.client.get(reverse("courses:prof_timetable"))
        grid = response.context["grid"]
        self.assertEqual(grid["slot_count"], 2)
        self.assertEqual(grid["total_label"], "3 h 30")
        self.assertEqual(response.context["class_count"], 2)
        self.assertIsNotNone(response.context["next_session"])
        self.assertContains(response, "Amphi A")
        self.assertContains(response, "Licence 3 Informatique")  # côté professeur : la classe
        self.assertNotContains(response, "INF504")

    def test_empty_timetable(self):
        response = self.client.get(reverse("courses:prof_timetable"))
        self.assertEqual(response.context["grid"]["slot_count"], 0)
        self.assertIsNone(response.context["next_session"])
        self.assertContains(response, "Votre emploi du temps est vide")
