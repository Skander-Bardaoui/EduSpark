"""Fichiers joints directement à la création / modification d'un cours
(bouton ou glisser-déposer) : PDF, PowerPoint, Word…"""

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from courses import files
from courses.models import Course, CourseMaterial

from .base import PDF_BYTES, CoursesTestCase


def uploads():
    return [
        SimpleUploadedFile("Cours 1 - Graphes.pdf", PDF_BYTES, content_type="application/pdf"),
        SimpleUploadedFile("Slides chapitre 1.pptx", b"PK\x03\x04slides"),
        SimpleUploadedFile("Fiche de TD.docx", b"PK\x03\x04word"),
    ]


class CourseUploadTests(CoursesTestCase):
    def setUp(self):
        self.login(self.prof_user)
        self.url = reverse("courses:prof_course_create")

    def test_form_offers_a_button_and_a_drop_zone(self):
        response = self.client.get(self.url)
        self.assertContains(response, "data-dropzone")
        self.assertContains(response, "Glissez-déposez vos fichiers ici")
        self.assertContains(response, "Choisir des fichiers")
        self.assertContains(response, 'multiple')
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, ".docx")  # attribut accept du champ

    def test_files_dropped_at_creation_become_course_materials(self):
        response = self.client.post(self.url, {
            "subject": self.subject.pk, "title": "Graphes", "description": "", "files": uploads(),
        })
        course = Course.objects.get(title="Graphes")
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[course.pk]))
        materials = {m.original_name: m for m in CourseMaterial.objects.filter(course=course)}
        self.assertEqual(
            {name: m.material_type for name, m in materials.items()},
            {"Cours 1 - Graphes.pdf": files.PDF, "Slides chapitre 1.pptx": files.PRESENTATION,
             "Fiche de TD.docx": files.DOCUMENT},
        )
        for material in materials.values():
            self.assertIsNone(material.chapter)
            self.assertEqual(material.uploaded_by, self.prof_user)
        self.assertEqual(materials["Fiche de TD.docx"].title, "Fiche de TD")
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn("3 fichiers ajoutés aux supports du cours.", texts)

    def test_course_can_still_be_created_without_files(self):
        self.client.post(self.url, {"subject": self.subject.pk, "title": "Sans fichier", "description": "Texte"})
        course = Course.objects.get(title="Sans fichier")
        self.assertFalse(course.materials.exists())

    def test_one_invalid_file_rejects_the_whole_form(self):
        bad = SimpleUploadedFile("virus.exe", b"MZ")
        response = self.client.post(self.url, {
            "subject": self.subject.pk, "title": "Refusé", "description": "", "files": uploads() + [bad],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "virus.exe : Format non pris en charge")
        self.assertFalse(Course.objects.filter(title="Refusé").exists())
        self.assertFalse(CourseMaterial.objects.exists())

    def test_files_can_be_added_when_editing_the_course(self):
        course = self.make_course()
        response = self.client.post(reverse("courses:prof_course_update", args=[course.pk]), {
            "subject": self.subject.pk, "title": course.title, "description": "",
            "files": [SimpleUploadedFile("Annexe.odt", b"PK\x03\x04odt")],
        })
        self.assertRedirects(response, reverse("courses:prof_course_detail", args=[course.pk]))
        self.assertEqual(list(course.materials.values_list("material_type", flat=True)), [files.DOCUMENT])

    def test_word_documents_are_downloaded_not_previewed(self):
        self.client.post(self.url, {
            "subject": self.subject.pk, "title": "Word", "description": "",
            "files": [SimpleUploadedFile("Plan.docx", b"PK\x03\x04word")],
        })
        material = CourseMaterial.objects.get(original_name="Plan.docx")
        response = self.client.get(reverse("courses:material_file", args=[material.pk]))
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        page = self.client.get(reverse("courses:material_view", args=[material.pk]))
        self.assertContains(page, "Aperçu indisponible")

    def test_single_material_form_also_has_a_drop_zone(self):
        response = self.client.get(reverse("courses:prof_material_create") + "?cours=%d" % self.make_course().pk)
        self.assertContains(response, "data-dropzone")
        self.assertContains(response, "Choisir un fichier")
