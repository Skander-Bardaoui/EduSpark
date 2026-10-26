from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import Membership, SchoolClass, StudentGroup, University
from accounts.tenancy import Role

from .models import (
    ExamCopy, ExamCopyPage, ExamSession, ExamSubject, GradeRecord, JuryMember,
    StudentGrade,
)


def _png_bytes(size=(400, 300), color=(255, 255, 255)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf_bytes():
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _pdf_upload(name="sujet.pdf"):
    return SimpleUploadedFile(name, _pdf_bytes(), content_type="application/pdf")


class AdminExamModuleTests(TestCase):
    def setUp(self):
        self.university = University.objects.create(name="Université Test", code="UT")
        self.other_university = University.objects.create(name="Université Voisine", code="UV")
        self.admin = User.objects.create_user(
            username="admin@test.local", email="admin@test.local", password="Pass12345!",
        )
        Membership.objects.create(
            user=self.admin, university=self.university, role=Role.UNIVERSITY_ADMIN,
        )
        self.other_admin = User.objects.create_user(
            username="other@test.local", email="other@test.local", password="Pass12345!",
        )
        Membership.objects.create(
            user=self.other_admin, university=self.other_university, role=Role.UNIVERSITY_ADMIN,
        )
        self.school_class = SchoolClass.objects.create(
            university=self.university, name="Licence 3 Informatique",
            level="3e année", program="Informatique", academic_year="2025-2026",
        )
        self.prof_user = User.objects.create_user(
            username="prof@test.local", email="prof@test.local",
            password="Pass12345!", first_name="Hélène", last_name="Vasseur",
        )
        self.prof_membership = Membership.objects.create(
            user=self.prof_user, university=self.university, role=Role.PROFESSOR,
        )
        self.school_class.professors.add(self.prof_membership.ensure_profile())
        self.student_user = User.objects.create_user(
            username="etu@test.local", email="etu@test.local",
            password="Pass12345!", first_name="Camille", last_name="Martin",
        )
        self.student_membership = Membership.objects.create(
            user=self.student_user, university=self.university, role=Role.STUDENT,
        )
        self.group = StudentGroup.objects.create(
            university=self.university, school_class=self.school_class, name="TD 1",
        )
        self.group.students.add(self.student_membership.ensure_profile())
        self.record = GradeRecord.objects.get(school_class=self.school_class)
        self.session = ExamSession.objects.create(
            university=self.university, school_class=self.school_class,
            title="INF501 · Algorithmique", date=date(2025, 11, 3),
            start_time=time(8, 30), end_time=time(10, 30), room="Amphi A",
            status=ExamSession.STATUS_PLANNED,
        )
        self.foreign_class = SchoolClass.objects.create(
            university=self.other_university, name="Master 1 Maths",
            level="Master 1", program="Mathématiques", academic_year="2025-2026",
        )
        self.foreign_session = ExamSession.objects.create(
            university=self.other_university, school_class=self.foreign_class,
            title="MAT401 · Analyse", date=date(2025, 11, 3),
            start_time=time(10, 15), end_time=time(12, 15), room="Amphi C",
        )
        self.client.force_login(self.admin)

    def test_sessions_page_is_tenant_scoped(self):
        response = self.client.get(reverse("exams:admin_exam_sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INF501 · Algorithmique")
        self.assertNotContains(response, "MAT401 · Analyse")

    def test_create_session(self):
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk],
            "create-title": "MAT301 · Probabilités",
            "create-exam_type": ExamSession.TYPE_ECRIT,
            "create-date": "2025-11-06",
            "create-start_time": "13:30",
            "create-end_time": "15:30",
            "create-room": "Salle 204",
        })
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        self.assertTrue(ExamSession.objects.filter(title="MAT301 · Probabilités").exists())

    def test_create_session_for_multiple_classes(self):
        second_class = SchoolClass.objects.create(
            university=self.university, name="Licence 3 Génie Logiciel",
            level="3e année", program="Génie logiciel", academic_year="2025-2026",
        )
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk, second_class.pk],
            "create-title": "INF502 · Bases de données",
            "create-exam_type": ExamSession.TYPE_ECRIT,
            "create-date": "2025-11-07",
            "create-start_time": "08:30",
            "create-end_time": "10:30",
            "create-room": "Amphi B",
        })
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        sessions = ExamSession.objects.filter(title="INF502 · Bases de données")
        self.assertEqual(sessions.count(), 2)
        self.assertEqual(
            len({session.plan_group for session in sessions}), 1,
        )
        self.assertEqual(
            set(sessions.values_list("school_class_id", flat=True)),
            {self.school_class.pk, second_class.pk},
        )

    def test_multiclass_plan_sharing_room_is_not_a_conflict(self):
        second_class = SchoolClass.objects.create(
            university=self.university, name="Licence 3 Génie Logiciel",
            level="3e année", program="Génie logiciel", academic_year="2025-2026",
        )
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk, second_class.pk],
            "create-title": "INF503 · Réseaux",
            "create-exam_type": ExamSession.TYPE_ECRIT,
            "create-date": "2025-11-07",
            "create-start_time": "08:30",
            "create-end_time": "10:30",
            "create-room": "Amphi B",
        })
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        page = self.client.get(reverse("exams:admin_exam_sessions"))
        self.assertContains(page, "Aucun chevauchement détecté")

    def test_create_session_rejects_room_conflict(self):
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk],
            "create-title": "Épreuve en conflit",
            "create-exam_type": ExamSession.TYPE_ECRIT,
            "create-date": "2025-11-03",
            "create-start_time": "09:00",
            "create-end_time": "11:00",
            "create-room": "Amphi A",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "déjà occupée")
        self.assertFalse(ExamSession.objects.filter(title="Épreuve en conflit").exists())

    def test_create_session_rejects_inverted_time(self):
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk],
            "create-title": "Épreuve à horaire invalide",
            "create-exam_type": ExamSession.TYPE_ECRIT,
            "create-date": "2025-11-06",
            "create-start_time": "15:30",
            "create-end_time": "13:30",
            "create-room": "Salle 204",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "L&#x27;heure de fin doit être postérieure")
        self.assertFalse(ExamSession.objects.filter(title="Épreuve à horaire invalide").exists())

    def test_create_session_notifies_professors_and_students(self):
        mail.outbox = []
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk],
            "create-title": "MAT301 · Probabilités",
            "create-exam_type": ExamSession.TYPE_ECRIT,
            "create-date": "2025-11-06",
            "create-start_time": "13:30",
            "create-end_time": "15:30",
            "create-room": "Salle 204",
        })
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            sorted(email.to[0] for email in mail.outbox),
            ["etu@test.local", "prof@test.local"],
        )
        self.assertTrue(all("MAT301 · Probabilités" in email.body for email in mail.outbox))
        self.assertTrue(all("Salle 204" in email.body for email in mail.outbox))

    def test_toggle_convocation_notifies_students_and_professors(self):
        mail.outbox = []
        url = reverse("exams:admin_exam_session_toggle_convocation", args=[self.session.pk])
        self.client.post(url)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ExamSession.STATUS_CONVOKED)
        self.assertIsNotNone(self.session.convoked_at)
        recipients = sorted(email.to[0] for email in mail.outbox)
        self.assertEqual(recipients, ["etu@test.local", "prof@test.local"])
        self.assertTrue(any("convocation" in email.body.lower() for email in mail.outbox))
        self.client.post(url)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ExamSession.STATUS_PLANNED)

    def test_revoke_convocation_keeps_copies(self):
        self.session.status = ExamSession.STATUS_CONVOKED
        self.session.convoked_at = timezone.now()
        self.session.save(update_fields=["status", "convoked_at"])
        copy = ExamCopy.objects.create(
            university=self.university, session=self.session,
            student=self.student_membership.ensure_profile(),
        )
        page = ExamCopyPage.objects.create(
            copy=copy, file=SimpleUploadedFile(
                "page1.png", _png_bytes(), content_type="image/png",
            ),
        )
        url = reverse("exams:admin_exam_session_toggle_convocation", args=[self.session.pk])
        self.client.post(url)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ExamSession.STATUS_PLANNED)
        self.assertTrue(ExamCopy.objects.filter(session=self.session).exists())
        self.assertTrue(page.file.storage.exists(page.file.name))

    def test_sessions_page_shows_subject_status(self):
        subject = ExamSubject.objects.create(
            session=self.session, file=_pdf_upload(), created_by=self.admin,
        )
        response = self.client.get(reverse("exams:admin_exam_sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sujet en brouillon")

        subject.published_at = timezone.now()
        subject.save(update_fields=["published_at"])
        response = self.client.get(reverse("exams:admin_exam_sessions"))
        self.assertContains(response, "Sujet publié")

    def test_delete_session(self):
        url = reverse("exams:admin_exam_session_delete", args=[self.session.pk])
        response = self.client.post(url)
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        self.assertFalse(ExamSession.objects.filter(pk=self.session.pk).exists())

    def test_foreign_session_is_not_editable(self):
        url = reverse("exams:admin_exam_session_delete", args=[self.foreign_session.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ExamSession.objects.filter(pk=self.foreign_session.pk).exists())

    def test_csv_exports(self):
        for name in (
            "exams:admin_exam_sessions_export",
            "exams:admin_statistics_export",
            "exams:admin_official_records_export",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("text/csv"))
            self.assertIn("attachment;", response["Content-Disposition"])

    def test_sign_publish_and_detail(self):
        self.record.students_count = 74
        self.record.admitted_count = 66
        self.record.average = Decimal("12.4")
        self.record.save()

        sign_url = reverse("exams:admin_grade_record_sign", args=[self.record.pk])
        self.client.post(sign_url)
        self.record.refresh_from_db()
        self.assertTrue(self.record.pv_signed)
        self.assertEqual(self.record.pv_signed_by, self.admin)

        publish_url = reverse("exams:admin_grade_record_publish", args=[self.record.pk])
        self.client.post(publish_url)
        self.record.refresh_from_db()
        self.assertTrue(self.record.transcript_published)

        response = self.client.get(
            reverse("exams:admin_grade_record_detail", args=[self.record.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Licence 3 Informatique")
        self.assertContains(response, "66")

    def test_publish_requires_signed_pv(self):
        url = reverse("exams:admin_grade_record_publish", args=[self.record.pk])
        self.client.post(url)
        self.record.refresh_from_db()
        self.assertFalse(self.record.transcript_published)

    def test_detail_updates_results(self):
        url = reverse("exams:admin_grade_record_detail", args=[self.record.pk])
        response = self.client.post(url, {
            "students_count": 74,
            "admitted_count": 66,
            "average": "12.4",
        })
        self.assertEqual(response.status_code, 302)
        self.record.refresh_from_db()
        self.assertEqual(self.record.students_count, 74)
        self.assertEqual(self.record.admitted_count, 66)
        self.assertEqual(self.record.rate, 89)

    def test_statistics_uses_record_values(self):
        self.record.students_count = 74
        self.record.admitted_count = 66
        self.record.average = Decimal("12.4")
        self.record.save()
        response = self.client.get(reverse("exams:admin_statistics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "89 %")
        self.assertContains(response, "12,4")
        self.assertNotContains(response, "Master 1 Maths")


class _ExamFlowMixin:
    def _create_university_actors(self):
        self.university = University.objects.create(name="Université Test", code="UT")
        self.prof_user = User.objects.create_user(
            username="prof@test.local", email="prof@test.local",
            password="Pass12345!", first_name="Hélène", last_name="Vasseur",
        )
        self.prof_membership = Membership.objects.create(
            user=self.prof_user, university=self.university, role=Role.PROFESSOR,
        )
        self.prof_profile = self.prof_membership.ensure_profile()
        self.student_user = User.objects.create_user(
            username="etu@test.local", email="etu@test.local",
            password="Pass12345!", first_name="Camille", last_name="Martin",
        )
        self.student_membership = Membership.objects.create(
            user=self.student_user, university=self.university, role=Role.STUDENT,
        )
        self.student_profile = self.student_membership.ensure_profile()
        self.school_class = SchoolClass.objects.create(
            university=self.university, name="Licence 3 Informatique",
            level="3e année", program="Informatique", academic_year="2025-2026",
        )
        self.school_class.professors.add(self.prof_profile)
        self.group = StudentGroup.objects.create(
            university=self.university, school_class=self.school_class, name="TD 1",
        )
        self.group.students.add(self.student_profile)
        self.record = GradeRecord.objects.get(school_class=self.school_class)
        self.future_date = date.today() + timedelta(days=10)
        self.session = ExamSession.objects.create(
            university=self.university, school_class=self.school_class,
            title="INF501 · Algorithmique avancée", date=self.future_date,
            start_time=time(8, 30), end_time=time(10, 30), room="Amphi A",
            status=ExamSession.STATUS_CONVOKED, convoked_at=timezone.now(),
        )

    def _criteria_post(self, points=(4, 5, 3, 2), action="save"):
        data = {
            "session": self.session.pk,
            "student": self.student_profile.pk,
            "action": action,
            "comment": "Bon travail dans l'ensemble.",
        }
        for index, (label, pts) in enumerate(zip(
            ("Architecture & Rétropropagation", "Calcul du Gradient",
             "Régularisation", "Rigueur scientifique"),
            points,
        )):
            data["crit_label_%d" % index] = label
            data["crit_weight_%d" % index] = "5"
            data["crit_points_%d" % index] = str(pts)
            data["crit_comment_%d" % index] = ""
        return data


class ProfExamModuleTests(_ExamFlowMixin, TestCase):
    def setUp(self):
        self._create_university_actors()
        self.client.force_login(self.prof_user)

    def test_prof_sessions_page_lists_own_sessions(self):
        response = self.client.get(reverse("exams:prof_exam_sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INF501 · Algorithmique avancée")

    def test_prof_sessions_page_rejects_creation(self):
        response = self.client.post(reverse("exams:prof_exam_sessions"), {
            "create-school_class": self.school_class.pk,
            "create-title": "MAT301 · Probabilités",
            "create-exam_type": ExamSession.TYPE_ECRIT,
            "create-date": (date.today() + timedelta(days=12)).isoformat(),
            "create-start_time": "13:30",
            "create-end_time": "15:30",
            "create-room": "Salle 204",
        })
        self.assertEqual(response.status_code, 405)
        self.assertFalse(ExamSession.objects.filter(title="MAT301 · Probabilités").exists())

    def test_prof_subject_upload_publish_unpublish(self):
        response = self.client.post(
            reverse("exams:prof_subject_upload", args=[self.session.pk]),
            {"file": _pdf_upload()},
        )
        self.assertRedirects(response, reverse("exams:prof_exam_sessions"))
        subject = ExamSubject.objects.get(session=self.session)
        self.assertEqual(subject.created_by, self.prof_user)
        self.assertIsNone(subject.published_at)

        response = self.client.post(
            reverse("exams:prof_subject_publish", args=[self.session.pk]),
        )
        self.assertRedirects(response, reverse("exams:prof_exam_sessions"))
        subject.refresh_from_db()
        self.assertIsNotNone(subject.published_at)

        self.client.post(
            reverse("exams:prof_subject_publish", args=[self.session.pk]),
        )
        subject.refresh_from_db()
        self.assertIsNone(subject.published_at)

    def test_prof_subject_upload_rejects_non_pdf(self):
        response = self.client.post(
            reverse("exams:prof_subject_upload", args=[self.session.pk]),
            {"file": SimpleUploadedFile("sujet.txt", b"texte", content_type="text/plain")},
            follow=True,
        )
        self.assertContains(response, "Envoyez le sujet au format PDF.")
        self.assertFalse(ExamSubject.objects.filter(session=self.session).exists())

    def test_prof_subject_upload_replaces_and_resets_publication(self):
        self.client.post(
            reverse("exams:prof_subject_upload", args=[self.session.pk]),
            {"file": _pdf_upload("v1.pdf")},
        )
        self.client.post(
            reverse("exams:prof_subject_publish", args=[self.session.pk]),
        )
        self.client.post(
            reverse("exams:prof_subject_upload", args=[self.session.pk]),
            {"file": _pdf_upload("v2.pdf")},
        )
        subject = ExamSubject.objects.get(session=self.session)
        self.assertIsNone(subject.published_at)
        self.assertTrue(subject.file.name.endswith(".pdf"))
        self.assertEqual(ExamSubject.objects.filter(session=self.session).count(), 1)

    def test_prof_subject_publish_requires_upload(self):
        response = self.client.post(
            reverse("exams:prof_subject_publish", args=[self.session.pk]),
            follow=True,
        )
        self.assertContains(response, "Déposez d&#x27;abord le sujet")

    def test_prof_corrections_save_then_validate(self):
        response = self.client.post(
            reverse("exams:prof_corrections"), self._criteria_post(),
        )
        expected = "%s?session=%s&student=%s" % (
            reverse("exams:prof_corrections"),
            self.session.pk, self.student_profile.pk,
        )
        self.assertRedirects(response, expected)
        grade = StudentGrade.objects.get(
            session=self.session, student=self.student_profile,
        )
        self.assertEqual(grade.status, StudentGrade.STATUS_DRAFT)
        self.assertIsNone(grade.score)

        self.client.post(
            reverse("exams:prof_corrections"),
            self._criteria_post(action="validate"),
        )
        grade.refresh_from_db()
        self.assertEqual(grade.status, StudentGrade.STATUS_VALIDATED)
        self.assertEqual(grade.score, Decimal("14.00"))
        self.assertEqual(grade.graded_by, self.prof_user)
        self.assertEqual(len(grade.criteria), 4)

    def test_prof_validate_requires_points(self):
        self.client.post(
            reverse("exams:prof_corrections"),
            self._criteria_post(points=(0, 0, 0, 0), action="validate"),
        )
        self.assertFalse(StudentGrade.objects.filter(
            session=self.session, student=self.student_profile,
        ).exists())

    def test_prof_publishes_validated_grades(self):
        self.client.post(
            reverse("exams:prof_corrections"),
            self._criteria_post(action="validate"),
        )
        response = self.client.post(
            reverse("exams:prof_corrections_publish"),
            {"session": self.session.pk},
        )
        expected = "%s?session=%s" % (
            reverse("exams:prof_corrections"), self.session.pk,
        )
        self.assertRedirects(response, expected)
        grade = StudentGrade.objects.get(
            session=self.session, student=self.student_profile,
        )
        self.assertEqual(grade.status, StudentGrade.STATUS_PUBLISHED)

    def test_prof_class_cards_lists_students_and_copies(self):
        copy = ExamCopy.objects.create(
            university=self.university, session=self.session,
            student=self.student_profile, original_name="copie.pdf",
            file=_pdf_upload("copie.pdf"),
            submitted_at=timezone.now(),
        )
        response = self.client.get(reverse("exams:prof_corrections"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Licence 3 Informatique")
        self.assertContains(response, "Camille Martin")
        self.assertContains(response, "copie.pdf")
        self.assertContains(response, "Soumise et verrouillée")
        self.assertContains(response, "N°")

    def test_prof_publishes_one_validated_grade(self):
        grade = StudentGrade.objects.create(
            university=self.university, session=self.session,
            student=self.student_profile, score=Decimal("14.00"),
            status=StudentGrade.STATUS_VALIDATED, graded_by=self.prof_user,
        )
        response = self.client.post(
            reverse("exams:prof_correction_publish_one"),
            {"session": self.session.pk, "student": self.student_profile.pk},
        )
        self.assertRedirects(
            response,
            "%s?session=%s&student=%s" % (
                reverse("exams:prof_corrections"),
                self.session.pk, self.student_profile.pk,
            ),
        )
        grade.refresh_from_db()
        self.assertEqual(grade.status, StudentGrade.STATUS_PUBLISHED)

    def test_prof_cannot_publish_draft_grade(self):
        grade = StudentGrade.objects.create(
            university=self.university, session=self.session,
            student=self.student_profile, score=Decimal("12.00"),
            status=StudentGrade.STATUS_DRAFT, graded_by=self.prof_user,
        )
        response = self.client.post(
            reverse("exams:prof_correction_publish_one"),
            {"session": self.session.pk, "student": self.student_profile.pk},
        )
        self.assertRedirects(
            response,
            "%s?session=%s&student=%s" % (
                reverse("exams:prof_corrections"),
                self.session.pk, self.student_profile.pk,
            ),
        )
        grade.refresh_from_db()
        self.assertEqual(grade.status, StudentGrade.STATUS_DRAFT)

    def test_prof_grade_sheets_page_and_sign(self):
        response = self.client.get(reverse("exams:prof_grade_sheets"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Licence 3 Informatique")
        self.assertFalse(self.record.pv_signed)

        response = self.client.post(reverse("exams:prof_grade_sheets_sign"))
        self.assertRedirects(response, reverse("exams:prof_grade_sheets"))
        self.record.refresh_from_db()
        self.assertTrue(self.record.pv_signed)
        self.assertEqual(self.record.pv_signed_by, self.prof_user)

    def test_prof_jury_invite(self):
        other_user = User.objects.create_user(
            username="autre@test.local", email="autre@test.local",
            password="Pass12345!", first_name="Awa", last_name="Diallo",
        )
        other_membership = Membership.objects.create(
            user=other_user, university=self.university, role=Role.PROFESSOR,
        )
        other_membership.ensure_profile()
        response = self.client.post(
            reverse("exams:prof_jury_invite", args=[self.record.pk]),
        )
        self.assertRedirects(response, reverse("exams:prof_grade_sheets"))
        jury = JuryMember.objects.get(
            grade_record=self.record, professor=other_membership.professor_profile,
        )
        self.assertEqual(jury.status, JuryMember.STATUS_INVITED)

    def test_foreign_session_not_accessible(self):
        other_university = University.objects.create(name="Université Voisine", code="UV")
        other_class = SchoolClass.objects.create(
            university=other_university, name="Master 1 Maths",
            level="Master 1", program="Mathématiques", academic_year="2025-2026",
        )
        foreign = ExamSession.objects.create(
            university=other_university, school_class=other_class,
            title="MAT401 · Analyse", date=self.future_date,
            start_time=time(8, 30), end_time=time(10, 30), room="Amphi C",
        )
        response = self.client.post(
            reverse("exams:prof_corrections_publish"),
            {"session": foreign.pk},
        )
        self.assertEqual(response.status_code, 404)


class StudentExamModuleTests(_ExamFlowMixin, TestCase):
    def setUp(self):
        self._create_university_actors()
        self.client.force_login(self.student_user)

    def _published_grade(self, score="14.00"):
        return StudentGrade.objects.create(
            university=self.university, session=self.session,
            student=self.student_profile, score=Decimal(score), max_score=20,
            criteria=[
                {"label": "Architecture & Rétropropagation", "weight": 5, "points": 4, "comment": ""},
                {"label": "Calcul du Gradient", "weight": 5, "points": 5, "comment": ""},
                {"label": "Régularisation", "weight": 5, "points": 3, "comment": ""},
                {"label": "Rigueur scientifique", "weight": 5, "points": 2, "comment": ""},
            ],
            status=StudentGrade.STATUS_PUBLISHED, graded_by=self.prof_user,
        )

    def _deposit_now(self):
        """Fige « maintenant » au milieu de l'épreuve (dépôt ouvert)."""
        start = timezone.make_aware(
            datetime.combine(self.session.date, self.session.start_time),
        )
        end = timezone.make_aware(
            datetime.combine(self.session.date, self.session.end_time),
        )
        return mock.patch(
            "django.utils.timezone.now",
            return_value=start + (end - start) / 2,
        )

    def test_student_exams_lists_upcoming_only(self):
        ExamSession.objects.create(
            university=self.university, school_class=self.school_class,
            title="PAST · Ancienne épreuve", date=date.today() - timedelta(days=5),
            start_time=time(8, 30), end_time=time(10, 30), room="Salle X",
        )
        response = self.client.get(reverse("exams:student_exams"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INF501 · Algorithmique avancée")
        self.assertNotContains(response, "PAST · Ancienne épreuve")

    def test_student_exams_shows_subject_only_during_exam_window(self):
        response = self.client.get(reverse("exams:student_exams"))
        self.assertContains(response, "Aucun sujet déposé")
        self.assertNotContains(response, "Télécharger le sujet")

        subject = ExamSubject.objects.create(
            session=self.session, file=_pdf_upload(), created_by=self.prof_user,
        )
        subject.published_at = timezone.now()
        subject.save(update_fields=["published_at"])

        response = self.client.get(reverse("exams:student_exams"))
        self.assertContains(response, "Sujet disponible au début")
        self.assertNotContains(response, "Télécharger le sujet")

        with self._deposit_now():
            response = self.client.get(reverse("exams:student_exams"))
            self.assertContains(response, "Télécharger le sujet")
            self.assertNotContains(response, "Sujet disponible au début")

        end = timezone.make_aware(
            datetime.combine(self.session.date, self.session.end_time),
        )
        with mock.patch(
            "django.utils.timezone.now",
            return_value=end + timedelta(minutes=5),
        ):
            response = self.client.get(reverse("exams:student_exams"))
            self.assertContains(response, "Sujet fermé")
            self.assertNotContains(response, "Télécharger le sujet")

    def test_student_subject_download_is_gated_by_exam_window(self):
        subject = ExamSubject.objects.create(
            session=self.session, file=_pdf_upload(), created_by=self.prof_user,
        )
        subject.published_at = timezone.now()
        subject.save(update_fields=["published_at"])
        url = reverse("exams:student_subject_download", args=[self.session.pk])

        response = self.client.get(url)
        self.assertRedirects(response, reverse("exams:student_exams"))

        with self._deposit_now():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")

    def test_student_convocation_pdf(self):
        response = self.client.get(
            reverse("exams:student_convocation_pdf", args=[self.session.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])

    def test_student_convocation_pdf_requires_convocation(self):
        self.session.status = ExamSession.STATUS_PLANNED
        self.session.convoked_at = None
        self.session.save()
        response = self.client.get(
            reverse("exams:student_convocation_pdf", args=[self.session.pk]),
        )
        self.assertRedirects(response, reverse("exams:student_exams"))

    def test_student_copy_upload_works_without_convocation_during_window(self):
        self.session.status = ExamSession.STATUS_PLANNED
        self.session.convoked_at = None
        self.session.save()
        with self._deposit_now():
            response = self.client.post(
                reverse("exams:student_copy_upload", args=[self.session.pk]),
                {"file": _pdf_upload("copie.pdf")},
            )
        self.assertRedirects(
            response, reverse("exams:student_exams"), fetch_redirect_response=False,
        )
        copy = ExamCopy.objects.get(
            session=self.session, student=self.student_profile,
        )
        self.assertTrue(copy.has_file)
        self.assertEqual(copy.original_name, "copie.pdf")

    def test_student_copy_upload_accepts_zip(self):
        with self._deposit_now():
            response = self.client.post(
                reverse("exams:student_copy_upload", args=[self.session.pk]),
                {"file": SimpleUploadedFile(
                    "copie.zip", b"PK\x03\x04archive", content_type="application/zip",
                )},
            )
        self.assertRedirects(response, reverse("exams:student_exams"))
        copy = ExamCopy.objects.get(
            session=self.session, student=self.student_profile,
        )
        self.assertTrue(copy.is_zip)
        self.assertEqual(copy.original_name, "copie.zip")

    def test_student_copy_upload_locked_before_exam_starts(self):
        response = self.client.post(
            reverse("exams:student_copy_upload", args=[self.session.pk]),
            {"file": SimpleUploadedFile(
                "page1.png", _png_bytes(), content_type="image/png",
            )},
        )
        self.assertRedirects(response, reverse("exams:student_exams"))
        self.assertFalse(ExamCopy.objects.filter(
            session=self.session, student=self.student_profile,
        ).exists())

        page = self.client.get(reverse("exams:student_exams"))
        self.assertContains(page, "Le dépôt de copie s'ouvre au début de l'épreuve")
        self.assertNotContains(page, "Soumettre la copie")

    def test_student_copy_upload_locked_after_exam_ends(self):
        end = timezone.make_aware(
            datetime.combine(self.session.date, self.session.end_time),
        )
        with mock.patch(
            "django.utils.timezone.now",
            return_value=end + timedelta(minutes=5),
        ):
            response = self.client.post(
                reverse("exams:student_copy_upload", args=[self.session.pk]),
                {"file": SimpleUploadedFile(
                    "page1.png", _png_bytes(), content_type="image/png",
                )},
            )
            self.assertRedirects(response, reverse("exams:student_exams"))
            self.assertFalse(ExamCopy.objects.filter(
                session=self.session, student=self.student_profile,
            ).exists())

            page = self.client.get(reverse("exams:student_exams"))
            self.assertContains(page, "Le dépôt de copie est fermé")
            self.assertNotContains(page, "Soumettre la copie")

    def test_student_copy_upload_submit_and_receipt(self):
        with self._deposit_now():
            response = self.client.post(
                reverse("exams:student_copy_upload", args=[self.session.pk]),
                {"file": SimpleUploadedFile(
                    "page1.png", _png_bytes(), content_type="image/png",
                )},
            )
            self.assertRedirects(response, reverse("exams:student_exams"))
            copy = ExamCopy.objects.get(
                session=self.session, student=self.student_profile,
            )
            self.assertEqual(copy.page_count, 1)

            response = self.client.post(
                reverse("exams:student_copy_submit", args=[self.session.pk]),
            )
            self.assertRedirects(response, reverse("exams:student_exams"))
            copy.refresh_from_db()
            self.assertTrue(copy.is_submitted)

            response = self.client.get(reverse("exams:student_exams"))
            self.assertContains(response, "Copie soumise")

    def test_student_exams_keeps_copy_visible_without_convocation(self):
        with self._deposit_now():
            self.client.post(
                reverse("exams:student_copy_upload", args=[self.session.pk]),
                {"file": _pdf_upload("copie.pdf")},
                follow=True,
            )
            self.client.post(
                reverse("exams:student_copy_submit", args=[self.session.pk]),
                follow=True,
            )
        self.session.status = ExamSession.STATUS_PLANNED
        self.session.convoked_at = None
        self.session.save(update_fields=["status", "convoked_at"])
        response = self.client.get(reverse("exams:student_exams"))
        self.assertContains(response, "Convocation en attente d'envoi")
        self.assertContains(response, "copie.pdf")
        self.assertContains(response, "Copie soumise et verrouillée")

    def test_student_copy_submit_requires_pages(self):
        with self._deposit_now():
            response = self.client.post(
                reverse("exams:student_copy_submit", args=[self.session.pk]),
            )
        self.assertRedirects(response, reverse("exams:student_exams"))
        self.assertFalse(ExamCopy.objects.filter(
            session=self.session, student=self.student_profile,
        ).exists())

    def test_student_copy_page_rotate_replace(self):
        with self._deposit_now():
            self.client.post(
                reverse("exams:student_copy_upload", args=[self.session.pk]),
                {"file": SimpleUploadedFile(
                    "page1.png", _png_bytes(), content_type="image/png",
                )},
            )
            page = ExamCopy.objects.get(
                session=self.session, student=self.student_profile,
            ).pages.first()
            original_name = page.file.name

            response = self.client.post(
                reverse("exams:student_copy_page_rotate", args=[page.pk]),
            )
            self.assertRedirects(response, reverse("exams:student_exams"))

            response = self.client.post(
                reverse("exams:student_copy_page_autocrop", args=[page.pk]),
            )
            self.assertRedirects(response, reverse("exams:student_exams"))

            response = self.client.post(
                reverse("exams:student_copy_page_replace", args=[page.pk]),
                {"file": SimpleUploadedFile(
                    "page2.png", _png_bytes(color=(200, 200, 200)),
                    content_type="image/png",
                )},
            )
            self.assertRedirects(response, reverse("exams:student_exams"))
            page.refresh_from_db()
            self.assertNotEqual(page.file.name, original_name)

    def test_student_transcript_page_and_pdfs(self):
        self._published_grade()
        response = self.client.get(reverse("exams:student_transcript"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "14")
        self.assertContains(response, "INF501 · Algorithmique avancée")

        for name in ("exams:student_transcript_pdf", "exams:student_attestation_pdf"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("application/pdf"))

    def test_student_attestation_requires_average_10(self):
        self._published_grade(score="8.00")
        response = self.client.get(reverse("exams:student_attestation_pdf"))
        self.assertRedirects(response, reverse("exams:student_transcript"))

    def test_student_exams_shows_published_grade_details(self):
        self._published_grade()
        response = self.client.get(reverse("exams:student_exams"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Architecture &amp; Rétropropagation")
        self.assertContains(response, "Publié")
