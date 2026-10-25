"""Tests des pages et APIs du test de langue orale."""

import json
import uuid
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.tests import PortalTestBase, add_membership, create_user
from accounts.tenancy import Role

from coaching.language.services import ProviderError
from coaching.models import (
    LanguageTestFeedback,
    LanguageTestSession,
    TutorAssignment,
)

ACADEMIC_YEAR = "2025-2026"

FEEDBACK = {
    "overall_level": "B2",
    "overall_verdict": "Needs Work",
    "fluency_score": 6,
    "vocabulary_score": 6,
    "grammar_score": 5,
    "task_achievement_score": 6,
    "fluency_notes": ["Réponses claires."],
    "vocabulary_notes": ["Lexique adapté."],
    "grammar_notes": ["Accords à surveiller."],
    "task_achievement_notes": ["Toutes les questions traitées."],
    "pronunciation_flags": [{"word": "superficial", "timestamp": 0}],
    "recommendations": ["Développez vos exemples."],
}

USER_TRANSCRIPT = [
    {"speaker": "assistant", "text": "How do you spend your free time?", "timestamp": 1},
    {"speaker": "user", "text": "I enjoy reading and running in the park.", "timestamp": 2},
]


def make_session(student, status=LanguageTestSession.STATUS_COMPLETED, feedback=True):
    session = LanguageTestSession.objects.create(
        university=student.university,
        student=student,
        exam_type="ielts",
        level="b2",
        exercise_type="topic_discussion",
        language="en",
        duration_seconds=840,
        status=status,
        transcript=USER_TRANSCRIPT,
    )
    if feedback:
        LanguageTestFeedback.objects.create(session=session, **FEEDBACK)
    return session


class LanguageTestBase(PortalTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.assignment_paris = TutorAssignment.objects.create(
            student=cls.student_paris,
            professor=cls.prof_paris,
            school_class=cls.class_paris,
            academic_year=ACADEMIC_YEAR,
        )
        cls.assignment_lyon = TutorAssignment.objects.create(
            student=cls.student_lyon,
            professor=cls.prof_lyon,
            school_class=cls.class_lyon,
            academic_year=ACADEMIC_YEAR,
        )
        cls.paris_session = make_session(cls.student_paris)
        cls.lyon_session = make_session(cls.student_lyon)

        cls.outsider_user = create_user("outsider@paris.fr", first_name="Zoé", last_name="Hors")
        cls.outsider_membership = add_membership(
            cls.outsider_user, cls.paris, Role.STUDENT,
            student_number="P-099", program="Informatique",
        )
        cls.outsider = cls.outsider_membership.student_profile
        cls.outsider_session = make_session(cls.outsider)

    def login_student(self, university=None):
        self.client.force_login(self.student_paris_user)
        self.set_current(university or self.paris)

    def login_prof(self, university=None):
        self.client.force_login(self.prof_user)
        self.set_current(university or self.paris)


class LanguageTestPageTests(LanguageTestBase):
    def test_anonymous_redirected_to_login(self):
        for name in ("student_language_tests", "prof_language_tests"):
            response = self.client.get(reverse("coaching:%s" % name))
            self.assertEqual(response.status_code, 302)
            self.assertIn("/accounts/connexion/", response.url)

    def test_student_pages_render(self):
        self.login_student()
        for name in (
            "student_language_tests",
            "student_language_test_setup",
        ):
            response = self.client.get(reverse("coaching:%s" % name))
            self.assertEqual(response.status_code, 200)
        response = self.client.get(
            reverse("coaching:student_language_test_feedback", args=[self.paris_session.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bilan de mon test de langue")

    def test_student_cannot_open_prof_page(self):
        self.login_student()
        response = self.client.get(reverse("coaching:prof_language_tests"))
        self.assertEqual(response.status_code, 403)

    def test_professor_cannot_open_student_page(self):
        self.login_prof()
        response = self.client.get(reverse("coaching:student_language_tests"))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_open_another_student_result(self):
        self.login_student()
        response = self.client.get(
            reverse("coaching:student_language_test_feedback", args=[self.outsider_session.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_student_cannot_open_other_tenant_result(self):
        self.login_student()
        response = self.client.get(
            reverse("coaching:student_language_test_feedback", args=[self.lyon_session.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_professor_pages_render(self):
        self.login_prof()
        response = self.client.get(reverse("coaching:prof_language_tests"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Camille")
        self.assertNotContains(response, "Lucas")

        response = self.client.get(
            reverse("coaching:prof_language_test_feedback", args=[self.paris_session.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bilan de Camille")

    def test_professor_cannot_open_outsider_result(self):
        self.login_prof()
        response = self.client.get(
            reverse("coaching:prof_language_test_feedback", args=[self.outsider_session.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_professor_cannot_open_other_tenant_result(self):
        self.login_prof()
        response = self.client.get(
            reverse("coaching:prof_language_test_feedback", args=[self.lyon_session.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_closed_assignment_removes_access(self):
        self.assignment_paris.status = TutorAssignment.STATUS_CLOSED
        self.assignment_paris.save(update_fields=["status"])
        self.login_prof()
        response = self.client.get(
            reverse("coaching:prof_language_test_feedback", args=[self.paris_session.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_professor_filter_by_student(self):
        self.login_prof()
        response = self.client.get(
            reverse("coaching:prof_language_tests"),
            {"student": self.student_paris.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Camille")
        self.assertNotContains(response, "Zoé")


class LanguageTestApiTests(LanguageTestBase):
    def start_payload(self, **overrides):
        payload = {
            "examType": "ielts",
            "level": "b2",
            "language": "en",
            "exerciseType": "topic_discussion",
        }
        payload.update(overrides)
        return json.dumps(payload)

    def start(self, **overrides):
        return self.client.post(
            reverse("coaching:student_language_test_start"),
            data=self.start_payload(**overrides),
            content_type="application/json",
        )

    def test_anonymous_gets_json_401(self):
        response = self.start()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "unauthorized")

    def test_professor_gets_json_403(self):
        self.login_prof()
        response = self.start()
        self.assertEqual(response.status_code, 403)

    def test_start_creates_tenant_session(self):
        self.login_student()
        response = self.start()
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        session = LanguageTestSession.objects.get(pk=data["sessionId"])
        self.assertEqual(session.student, self.student_paris)
        self.assertEqual(session.university, self.paris)
        self.assertEqual(session.status, LanguageTestSession.STATUS_ACTIVE)
        self.assertTrue(data["sessionUrl"])

    def test_random_exercise_is_resolved(self):
        self.login_student()
        response = self.start(exerciseType="random")
        self.assertEqual(response.status_code, 200)
        session = LanguageTestSession.objects.get(
            pk=response.json()["data"]["sessionId"]
        )
        self.assertIn(session.exercise_type, ("topic_discussion", "debate"))

    def test_new_start_abandons_previous_active_session(self):
        self.login_student()
        first = self.start()
        second = self.start()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_session = LanguageTestSession.objects.get(
            pk=first.json()["data"]["sessionId"]
        )
        self.assertEqual(first_session.status, LanguageTestSession.STATUS_ABANDONED)
        self.assertIsNotNone(first_session.ended_at)

    def test_foreign_session_api_rejected(self):
        self.login_student()
        for name, method in (
            ("student_language_test_stt_token", "get"),
            ("student_language_test_reply", "post"),
            ("student_language_test_tts", "post"),
            ("student_language_test_evaluate", "post"),
        ):
            url = reverse("coaching:%s" % name, args=[self.lyon_session.pk])
            kwargs = {"data": "{}", "content_type": "application/json"} if method == "post" else {}
            response = getattr(self.client, method)(url, **kwargs)
            self.assertEqual(response.status_code, 404, name)

    def test_stt_token_returns_provider_token(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_stt_token", args=[session.pk])
        with mock.patch(
            "coaching.language.views.services.create_realtime_token",
            return_value="tok-123",
        ):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token"], "tok-123")

    def test_stt_token_provider_error_returns_502(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_stt_token", args=[session.pk])
        with mock.patch(
            "coaching.language.views.services.create_realtime_token",
            side_effect=ProviderError("indisponible"),
        ):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 502)

    def test_reply_streams_examiner_text(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_reply", args=[session.pk])
        with mock.patch(
            "coaching.language.views.services.stream_examiner_reply",
            return_value=iter(["Bonjour", " !"]),
        ):
            response = self.client.post(
                url,
                data=json.dumps({"transcript": "Hello", "history": []}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"Bonjour !")

    def test_reply_requires_transcript(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_reply", args=[session.pk])
        response = self.client.post(
            url, data=json.dumps({"transcript": "  "}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_tts_streams_audio(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_tts", args=[session.pk])
        with mock.patch(
            "coaching.language.views.services.open_tts_stream",
            return_value=iter([b"mp3"]),
        ):
            response = self.client.post(
                url,
                data=json.dumps({"text": "Bonjour", "language": "en"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"mp3")

    def test_tts_rejects_oversized_text(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_tts", args=[session.pk])
        response = self.client.post(
            url,
            data=json.dumps({"text": "x" * 4097}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_evaluate_requires_a_candidate_turn(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_evaluate", args=[session.pk])
        response = self.client.post(
            url,
            data=json.dumps({"transcript": [USER_TRANSCRIPT[0]]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_evaluate_persists_feedback_once(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_evaluate", args=[session.pk])
        with mock.patch(
            "coaching.language.views.services.evaluate_transcript",
            return_value=FEEDBACK,
        ) as evaluate:
            first = self.client.post(
                url,
                data=json.dumps({"transcript": USER_TRANSCRIPT}),
                content_type="application/json",
            )
            second = self.client.post(
                url,
                data=json.dumps({"transcript": USER_TRANSCRIPT}),
                content_type="application/json",
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(evaluate.call_count, 1)
        session.refresh_from_db()
        self.assertEqual(session.status, LanguageTestSession.STATUS_COMPLETED)
        self.assertIsNotNone(session.ended_at)
        self.assertEqual(len(session.transcript), 2)
        self.assertEqual(session.transcript[0]["speaker"], "assistant")
        self.assertEqual(session.transcript[1]["text"], USER_TRANSCRIPT[1]["text"])
        self.assertEqual(LanguageTestFeedback.objects.filter(session=session).count(), 1)
        self.assertEqual(
            first.json()["data"]["feedbackId"], second.json()["data"]["feedbackId"],
        )

    def test_evaluate_provider_error_returns_502(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ACTIVE, feedback=False,
        )
        url = reverse("coaching:student_language_test_evaluate", args=[session.pk])
        with mock.patch(
            "coaching.language.views.services.evaluate_transcript",
            side_effect=ProviderError("panne"),
        ):
            response = self.client.post(
                url,
                data=json.dumps({"transcript": USER_TRANSCRIPT}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 502)
        self.assertFalse(LanguageTestFeedback.objects.filter(session=session).exists())

    def test_abandoned_session_cannot_be_evaluated(self):
        self.login_student()
        session = make_session(
            self.student_paris, status=LanguageTestSession.STATUS_ABANDONED, feedback=False,
        )
        url = reverse("coaching:student_language_test_evaluate", args=[session.pk])
        response = self.client.post(
            url,
            data=json.dumps({"transcript": USER_TRANSCRIPT}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)


class SeedLanguageTests(PortalTestBase):
    def test_seed_is_idempotent(self):
        students = (
            ("test.ui@example.com", self.paris, "Camille"),
            ("yanis.leroy@u-paris.fr", self.paris, "Yanis"),
            ("lucas.moreau@univ-lyon.fr", self.lyon, "Lucas"),
        )
        for email, university, first_name in students:
            user = create_user(email, first_name=first_name, last_name="Test")
            membership = add_membership(user, university, Role.STUDENT)
            student = membership.student_profile
            professor = self.prof_paris if university == self.paris else self.prof_lyon
            TutorAssignment.objects.create(
                student=student,
                professor=professor,
                school_class=self.class_paris if university == self.paris else self.class_lyon,
                academic_year=ACADEMIC_YEAR,
            )

        from coaching.management.commands import seed_language_tests as seed_module

        with mock.patch.object(seed_module, "PARIS", self.paris.name), \
                mock.patch.object(seed_module, "LYON", self.lyon.name):
            call_command("seed_language_tests", force=True)
            call_command("seed_language_tests", force=True)

        self.assertEqual(LanguageTestSession.objects.count(), 3)
        self.assertEqual(LanguageTestFeedback.objects.count(), 3)
        self.assertTrue(all(
            LanguageTestSession.objects.filter(pk=session_id).exists()
            for session_id in (
                uuid.uuid5(seed_module.SEED_NAMESPACE, "camille-ielts-b2"),
                uuid.uuid5(seed_module.SEED_NAMESPACE, "yanis-cambridge-b1"),
                uuid.uuid5(seed_module.SEED_NAMESPACE, "lucas-ielts-c1"),
            )
        ))
