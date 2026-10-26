"""Supports de cours : validation des fichiers, accès contrôlé, flux avec Range."""

import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse

from accounts.models import Membership
from courses import files
from courses.file_views import UNSATISFIABLE, _RangeIterator, parse_range
from courses.models import CourseMaterial, TeachingAssignment

from .base import PDF_BYTES, CoursesTestCase, pdf_upload


def body(response):
    return b"".join(response.streaming_content) if response.streaming else response.content


class FileRulesTests(SimpleTestCase):
    def test_type_detection(self):
        expected = {
            "a.pdf": files.PDF, "A.PDF": files.PDF, "a.pptx": files.PRESENTATION, "a.odp": files.PRESENTATION,
            "a.mp4": files.VIDEO, "a.webm": files.VIDEO, "a.mp3": files.AUDIO, "a.wav": files.AUDIO,
            "a.exe": None, "a.html": None, "a.svg": None, "noextension": None, "": None,
        }
        for name, material_type in expected.items():
            with self.subTest(name=name):
                self.assertEqual(files.detect_type(name), material_type)

    def test_mime_types_come_from_the_whitelist(self):
        self.assertEqual(files.mime_for("x.pdf"), "application/pdf")
        self.assertEqual(files.mime_for("x.mp4"), "video/mp4")
        self.assertEqual(files.mime_for("x.html"), "application/octet-stream")

    def test_every_accepted_extension_has_a_mime_type(self):
        for rule in files.TYPE_RULES.values():
            for extension in rule["extensions"]:
                self.assertIn(extension, files.MIME_TYPES)

    def test_format_size_is_french(self):
        self.assertEqual(files.format_size(0), "0 o")
        self.assertEqual(files.format_size(900), "900 o")
        self.assertEqual(files.format_size(2048), "2 Ko")
        self.assertEqual(files.format_size(int(4.8 * 1024 * 1024)), "4,8 Mo")
        self.assertEqual(files.format_size(3 * 1024 ** 3), "3 Go")

    def test_original_name_is_sanitised(self):
        self.assertEqual(files.safe_original_name("../../etc/passwd.pdf"), "passwd.pdf")
        self.assertEqual(files.safe_original_name("C:\\Users\\moi\\cours.pdf"), "cours.pdf")
        self.assertEqual(files.safe_original_name(""), "support")
        self.assertEqual(len(files.safe_original_name("a" * 400 + ".pdf")), 255)

    def test_validate_upload(self):
        self.assertEqual(files.validate_upload(pdf_upload()), files.PDF)
        self.assertEqual(files.validate_upload(SimpleUploadedFile("a.mp3", b"ID3")), files.AUDIO)
        for upload, message in (
            (SimpleUploadedFile("a.exe", b"MZ"), "Format non pris en charge"),
            (SimpleUploadedFile("a.pdf", b""), "vide"),
            (SimpleUploadedFile("a.pdf", b"<html>pas un pdf</html>"), "pas un PDF valide"),
        ):
            with self.subTest(name=upload.name), self.assertRaisesMessage(ValidationError, message):
                files.validate_upload(upload)

    def test_pdf_signature_is_searched_in_the_first_kilobyte(self):
        files.validate_upload(SimpleUploadedFile("a.pdf", b"\x00" * 200 + PDF_BYTES))


class RangeParsingTests(SimpleTestCase):
    def test_ranges(self):
        cases = {
            ("bytes=0-9", 100): (0, 9),
            ("bytes=10-", 100): (10, 99),
            ("bytes=-5", 100): (95, 99),
            ("bytes=90-500", 100): (90, 99),
            ("bytes=-500", 100): (0, 99),
            ("bytes=0-0", 100): (0, 0),
            ("bytes=100-", 100): UNSATISFIABLE,
            ("bytes=250-300", 100): UNSATISFIABLE,
            ("bytes=-0", 100): UNSATISFIABLE,
            ("bytes=9-3", 100): None,          # plage inversée : ignorée
            ("bytes=0-1,5-6", 100): None,      # plages multiples : on sert tout le fichier
            ("items=0-5", 100): None,
            ("bytes=abc", 100): None,
            ("bytes=-", 100): None,
            ("", 100): None,
            (None, 100): None,
        }
        for (header, size), expected in cases.items():
            with self.subTest(header=header):
                self.assertEqual(parse_range(header, size), expected)


class MaterialAccessTests(CoursesTestCase):
    def setUp(self):
        self.course = self.make_course()
        self.material = CourseMaterial.objects.create(
            course=self.course, title="Polycopié", description="Version 1", file=pdf_upload("poly.pdf"),
        )
        self.file_url = reverse("courses:material_file", args=[self.material.pk])
        self.view_url = reverse("courses:material_view", args=[self.material.pk])

    def statuses(self, users, url=None):
        url = url or self.file_url
        result = {}
        for user in users:
            self.login(user)
            result[user.email] = self.client.get(url).status_code
        return result

    def test_anonymous_users_are_sent_to_the_login_page(self):
        for url in (self.file_url, self.view_url):
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url), "%s?next=%s" % (settings.LOGIN_URL, url), fetch_redirect_response=False,
                )

    def test_unpublished_course_is_reserved_to_its_author_and_the_university_admin(self):
        for url in (self.file_url, self.view_url):
            with self.subTest(url=url):
                result = self.statuses(
                    [self.prof_user, self.admin, self.platform, self.student_user, self.student2_user,
                     self.student3_user, self.prof2_user, self.other_admin, self.other_prof_user,
                     self.other_student_user],
                    url,
                )
                self.assertEqual(result, {
                    "prof@ut.test": 200, "admin@ut.test": 200, "platform@ut.test": 200,
                    "camille@ut.test": 404, "ines@ut.test": 404, "yanis@ut.test": 404,
                    "prof2@ut.test": 404, "admin@uv.test": 404, "prof@uv.test": 404, "lucas@uv.test": 404,
                })

    def test_published_course_opens_to_the_students_of_that_class_only(self):
        self.publish(self.course)
        result = self.statuses([
            self.student_user, self.student2_user, self.student3_user, self.other_student_user,
            self.prof2_user, self.prof_user,
        ])
        self.assertEqual(result, {
            "camille@ut.test": 200, "ines@ut.test": 200, "yanis@ut.test": 404,
            "lucas@uv.test": 404, "prof2@ut.test": 404, "prof@ut.test": 200,
        })

    def test_publication_for_another_class_does_not_open_the_course(self):
        from accounts.models import StudentGroup

        group = StudentGroup.objects.create(school_class=self.class_gl, name="Groupe GL")
        group.students.add(self.student3)
        self.publish(self.course)  # publié pour la L3 seulement
        self.assertEqual(self.statuses([self.student3_user]), {"yanis@ut.test": 404})

    def test_withdrawing_the_course_revokes_access(self):
        publication = self.publish(self.course)
        self.assertEqual(self.statuses([self.student_user]), {"camille@ut.test": 200})
        publication.is_published = False
        publication.save()
        self.assertEqual(self.statuses([self.student_user]), {"camille@ut.test": 404})

    def test_removing_the_assignment_revokes_access(self):
        self.publish(self.course)
        TeachingAssignment.objects.get(pk=self.assign.pk).delete()
        self.assertEqual(self.statuses([self.student_user]), {"camille@ut.test": 404})

    def test_suspended_membership_loses_access(self):
        Membership.objects.filter(user=self.prof_user).update(is_active=False)
        self.assertEqual(self.statuses([self.prof_user]), {"prof@ut.test": 404})

    def test_unknown_material_is_404(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("courses:material_file", args=[99999])).status_code, 404)

    def test_files_have_no_public_media_url(self):
        self.publish(self.course)
        self.login(self.student_user)
        page = self.client.get(self.view_url)
        self.assertNotContains(page, settings.MEDIA_URL + "courses")
        self.assertNotContains(page, self.material.file.name)
        self.assertEqual(self.client.get(settings.MEDIA_URL + self.material.file.name).status_code, 404)


class MaterialStreamingTests(CoursesTestCase):
    def setUp(self):
        self.course = self.make_course()
        self.payload = bytes(range(256)) * 4  # 1024 octets reconnaissables
        self.video = CourseMaterial.objects.create(
            course=self.course, title="Capsule", file=SimpleUploadedFile("capsule.mp4", self.payload),
        )
        self.login(self.prof_user)
        self.url = reverse("courses:material_file", args=[self.video.pk])

    def test_full_response_headers(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp4")
        self.assertEqual(response["Content-Length"], "1024")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("private", response["Cache-Control"])
        self.assertTrue(response["Content-Disposition"].startswith("inline"))
        self.assertIn("capsule.mp4", response["Content-Disposition"])
        self.assertEqual(body(response), self.payload)

    def test_partial_content(self):
        response = self.client.get(self.url, HTTP_RANGE="bytes=10-19")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 10-19/1024")
        self.assertEqual(response["Content-Length"], "10")
        self.assertEqual(response["Content-Type"], "video/mp4")
        self.assertEqual(body(response), self.payload[10:20])

    def test_open_ended_and_suffix_ranges(self):
        response = self.client.get(self.url, HTTP_RANGE="bytes=1000-")
        self.assertEqual((response.status_code, response["Content-Range"]), (206, "bytes 1000-1023/1024"))
        self.assertEqual(body(response), self.payload[1000:])
        response = self.client.get(self.url, HTTP_RANGE="bytes=-4")
        self.assertEqual((response.status_code, response["Content-Range"]), (206, "bytes 1020-1023/1024"))
        self.assertEqual(body(response), self.payload[-4:])

    def test_range_is_clamped_to_the_file_size(self):
        response = self.client.get(self.url, HTTP_RANGE="bytes=1020-99999")
        self.assertEqual(response["Content-Range"], "bytes 1020-1023/1024")

    def test_unsatisfiable_range(self):
        response = self.client.get(self.url, HTTP_RANGE="bytes=5000-")
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], "bytes */1024")

    def test_ignored_ranges_serve_the_whole_file(self):
        for header in ("bytes=0-1,5-6", "bytes=9-3", "junk"):
            with self.subTest(header=header):
                response = self.client.get(self.url, HTTP_RANGE=header)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(body(response), self.payload)

    def test_download_flag_forces_an_attachment(self):
        response = self.client.get(self.url + "?telecharger=1")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))

    def test_range_iterator_reads_only_its_slice_and_closes_the_file(self):
        handle = self.video.file.open("rb")
        iterator = _RangeIterator(handle, 100, 150)
        self.assertEqual(b"".join(iterator), self.payload[100:250])
        iterator.close()
        self.assertTrue(handle.closed)

    def test_range_iterator_stops_at_the_end_of_the_file(self):
        handle = self.video.file.open("rb")
        iterator = _RangeIterator(handle, 1000, 5000)
        self.assertEqual(b"".join(iterator), self.payload[1000:])
        iterator.close()

    def test_missing_file_on_disk_is_a_404(self):
        os.remove(self.video.file.path)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_only_get_is_allowed(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)


class MaterialSecurityTests(CoursesTestCase):
    def setUp(self):
        self.course = self.make_course()
        self.login(self.prof_user)

    def serve(self, name, content):
        material = CourseMaterial.objects.create(
            course=self.course, title=name, file=SimpleUploadedFile(name, content),
        )
        return self.client.get(reverse("courses:material_file", args=[material.pk]))

    def test_presentations_are_always_downloaded(self):
        response = self.serve("cours.pptx", b"PK\x03\x04")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

    def test_html_hidden_in_an_allowed_extension_is_never_served_as_html(self):
        response = self.serve("piege.pptx", b"<html><script>alert(document.cookie)</script></html>")
        self.assertNotIn("text/html", response["Content-Type"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))

    def test_preview_frame_is_allowed_for_the_same_origin_only(self):
        response = self.serve("cours.pdf", PDF_BYTES)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")

    def test_non_ascii_names_are_encoded_in_the_header(self):
        material = CourseMaterial.objects.create(
            course=self.course, title="Accents", file=SimpleUploadedFile("Résumé élèves.pdf", PDF_BYTES),
        )
        response = self.client.get(reverse("courses:material_file", args=[material.pk]) + "?telecharger=1")
        self.assertIn("filename*=utf-8''R%C3%A9sum%C3%A9%20%C3%A9l%C3%A8ves.pdf", response["Content-Disposition"])


class MaterialViewerTests(CoursesTestCase):
    def setUp(self):
        self.course = self.make_course()
        self.publish(self.course)

    def viewer(self, name, content=b"data", user=None):
        material = CourseMaterial.objects.create(
            course=self.course, title="Support %s" % name, file=SimpleUploadedFile(name, content),
        )
        self.login(user or self.student_user)
        return self.client.get(reverse("courses:material_view", args=[material.pk])), material

    def test_each_type_gets_the_right_player(self):
        response, material = self.viewer("cours.pdf", PDF_BYTES)
        self.assertContains(response, "<iframe")
        self.assertContains(response, reverse("courses:material_file", args=[material.pk]))
        response, _ = self.viewer("film.mp4")
        self.assertContains(response, "<video")
        response, _ = self.viewer("podcast.mp3")
        self.assertContains(response, "<audio")
        response, _ = self.viewer("slides.pptx")
        self.assertContains(response, "Aperçu indisponible")
        self.assertNotContains(response, "<iframe")

    def test_back_link_depends_on_the_role(self):
        expected = {
            self.student_user: reverse("courses:student_course_detail", args=[self.course.pk]),
            self.prof_user: reverse("courses:prof_course_detail", args=[self.course.pk]),
            self.admin: reverse("courses:admin_course_detail", args=[self.course.pk]),
        }
        for user, url in expected.items():
            with self.subTest(user=user.email):
                response, _ = self.viewer("cours.pdf", PDF_BYTES, user=user)
                self.assertEqual(response.context["back_url"], url)

    def test_viewer_shows_description_and_metadata(self):
        material = CourseMaterial.objects.create(
            course=self.course, title="Poly", description="Chapitres 1 à 3", file=pdf_upload("poly.pdf"),
        )
        self.login(self.student_user)
        response = self.client.get(reverse("courses:material_view", args=[material.pk]))
        self.assertContains(response, "Chapitres 1 à 3")
        self.assertContains(response, "Hélène Vasseur")
        self.assertContains(response, "PDF")
