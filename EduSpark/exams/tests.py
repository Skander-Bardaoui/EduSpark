from datetime import timedelta
from decimal import Decimal
import io
import shutil
import tempfile
from unittest import mock
import zipfile

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, SchoolClass, StudentGroup, University
from accounts.tenancy import Role
from courses.models import (
    Course, CoursePublication, Department, Program, Subject, TeachingAssignment,
)

from .models import (
    ExamSession, GradeRecord, OralAttempt, OralTopic, ProjectCriterion,
    ProjectSubmission, Quiz, QuizAnswer, QuizAttempt, QuizChoice,
    QuizQuestion, StudentGrade,
)
from .services.ai_insights import generate_quiz_analysis, generate_student_feedback


class ExamFixtureMixin:
    def setUp(self):
        self.university = University.objects.create(name="Université Test", code="UT")
        self.other_university = University.objects.create(name="Université Voisine", code="UV")

        self.admin = User.objects.create_user(
            username="admin@test.local", email="admin@test.local",
            password="Pass12345!", first_name="Amina", last_name="Benali",
        )
        Membership.objects.create(
            user=self.admin, university=self.university, role=Role.UNIVERSITY_ADMIN,
        )

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

        self.department = Department.objects.create(
            university=self.university, name="Informatique", code="INFO",
        )
        self.program = Program.objects.create(
            university=self.university, department=self.department,
            name="Licence Informatique", code="LIC-INFO",
        )
        self.subject = Subject.objects.create(
            university=self.university, program=self.program,
            name="Algorithmique avancée", code="INF501", semester=5,
            coefficient=Decimal("3"),
        )

        self.school_class = SchoolClass.objects.create(
            university=self.university, name="Licence 3 Informatique",
            level="3e année", study_program=self.program,
            academic_year="2025-2026",
        )
        self.group = StudentGroup.objects.create(
            university=self.university, school_class=self.school_class, name="TD 1",
        )
        self.group.students.add(self.student_profile)

        self.assignment = TeachingAssignment.objects.create(
            university=self.university, school_class=self.school_class,
            subject=self.subject, professor=self.prof_profile,
        )
        self.course = Course.objects.create(
            university=self.university, subject=self.subject,
            professor=self.prof_profile, title="Algorithmique avancée",
            description="Cours complet sur les graphes et la complexité.",
        )
        CoursePublication.objects.create(
            university=self.university, course=self.course,
            school_class=self.school_class, is_published=True,
            published_at=timezone.now(),
        )

        self.record = GradeRecord.objects.get(school_class=self.school_class)
        self.now = timezone.now()
        self.session = ExamSession.objects.create(
            university=self.university, school_class=self.school_class,
            course_subject=self.subject, title="INF501 · QCM Algorithmique",
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.admin,
        )

        self.foreign_class = SchoolClass.objects.create(
            university=self.other_university, name="Master 1 Maths",
            level="Master 1", program="Mathématiques", academic_year="2025-2026",
        )
        self.foreign_session = ExamSession.objects.create(
            university=self.other_university, school_class=self.foreign_class,
            title="MAT401 · Analyse",
            opens_at=self.now,
            closes_at=self.now + timedelta(hours=2),
        )

    def _create_quiz(self, *, published=True, session=None):
        session = session or self.session
        quiz = Quiz.objects.create(
            university=self.university, session=session, course=self.course,
            instructions="Lisez attentivement chaque question.",
            duration_minutes=30, pass_score=Decimal("10"),
            question_count=1, created_by=self.prof_user,
            status=Quiz.STATUS_PUBLISHED if published else Quiz.STATUS_DRAFT,
            published_at=self.now if published else None,
        )
        question = QuizQuestion.objects.create(
            quiz=quiz, order=1, prompt="Quelle structure permet un parcours en largeur ?",
            explanation="La file (FIFO) est utilisée par le BFS.", points=Decimal("1"),
        )
        correct = QuizChoice.objects.create(
            question=question, order=1, label="Une file", is_correct=True,
        )
        wrong = QuizChoice.objects.create(
            question=question, order=2, label="Une pile", is_correct=False,
        )
        return quiz, question, correct, wrong

    def _create_published_grade(self, score="14.00", session=None, student=None):
        return StudentGrade.objects.create(
            university=self.university,
            session=session or self.session,
            student=student or self.student_profile,
            score=Decimal(score), max_score=Decimal("20"),
            status=StudentGrade.STATUS_PUBLISHED, graded_by=self.prof_user,
        )

    def _create_attempt(self, quiz, question, correct, *, score=Decimal("1"),
                        max_score=Decimal("1")):
        attempt = QuizAttempt.objects.create(
            university=self.university, quiz=quiz, student=self.student_profile,
            deadline_at=self.now + timedelta(minutes=30),
            submitted_at=self.now, score=score, max_score=max_score,
            status=QuizAttempt.STATUS_SUBMITTED,
            question_order=[question.pk],
        )
        QuizAnswer.objects.create(
            attempt=attempt, question=question, selected_choice=correct,
        )
        return attempt


class AdminExamTests(ExamFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_sessions_page_is_tenant_scoped(self):
        response = self.client.get(reverse("exams:admin_exam_sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INF501 · QCM Algorithmique")
        self.assertNotContains(response, "MAT401 · Analyse")

    def test_create_session_with_window(self):
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk],
            "create-course_subject": self.subject.pk,
            "create-title": "INF502 · QCM Bases de données",
            "create-opens_at": "2026-11-06T13:30",
            "create-closes_at": "2026-11-06T15:30",
        })
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        session = ExamSession.objects.get(title="INF502 · QCM Bases de données")
        self.assertEqual(session.opens_at.hour, 13)
        self.assertEqual(session.closes_at.hour, 15)

    def test_create_session_for_multiple_classes(self):
        second_class = SchoolClass.objects.create(
            university=self.university, name="Licence 3 Génie Logiciel",
            level="3e année", study_program=self.program,
            academic_year="2025-2026",
        )
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk, second_class.pk],
            "create-course_subject": self.subject.pk,
            "create-title": "INF503 · QCM Réseaux",
            "create-opens_at": "2026-11-07T08:30",
            "create-closes_at": "2026-11-07T10:30",
        })
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        sessions = ExamSession.objects.filter(title="INF503 · QCM Réseaux")
        self.assertEqual(sessions.count(), 2)
        self.assertEqual(
            set(sessions.values_list("school_class_id", flat=True)),
            {self.school_class.pk, second_class.pk},
        )

    def test_create_session_rejects_inverted_window(self):
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk],
            "create-course_subject": self.subject.pk,
            "create-title": "Horaire invalide",
            "create-opens_at": "2026-11-06T15:30",
            "create-closes_at": "2026-11-06T13:30",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fermeture doit être postérieure")
        self.assertFalse(ExamSession.objects.filter(title="Horaire invalide").exists())

    def test_create_session_notifies_professor_and_students(self):
        mail.outbox = []
        response = self.client.post(reverse("exams:admin_exam_session_create"), {
            "create-school_classes": [self.school_class.pk],
            "create-course_subject": self.subject.pk,
            "create-title": "INF504 · QCM Compilation",
            "create-opens_at": "2026-11-08T09:00",
            "create-closes_at": "2026-11-08T11:00",
        })
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            sorted(email.to[0] for email in mail.outbox),
            ["etu@test.local", "prof@test.local"],
        )

    def test_update_and_delete_session(self):
        response = self.client.post(
            reverse("exams:admin_exam_session_update", args=[self.session.pk]),
            {
                "edit-school_class": self.school_class.pk,
                "edit-course_subject": self.subject.pk,
                "edit-title": "Titre modifié",
                "edit-opens_at": "2026-11-09T08:00",
                "edit-closes_at": "2026-11-09T10:00",
            },
        )
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "Titre modifié")

        response = self.client.post(
            reverse("exams:admin_exam_session_delete", args=[self.session.pk]),
        )
        self.assertRedirects(response, reverse("exams:admin_exam_sessions"))
        self.assertFalse(ExamSession.objects.filter(pk=self.session.pk).exists())

    def test_cannot_delete_foreign_session(self):
        response = self.client.post(
            reverse("exams:admin_exam_session_delete", args=[self.foreign_session.pk]),
        )
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

    def test_sign_and_publish_record(self):
        self._create_published_grade()
        self.client.post(reverse("exams:admin_grade_record_sign", args=[self.record.pk]))
        self.record.refresh_from_db()
        self.assertTrue(self.record.pv_signed)
        self.assertEqual(self.record.pv_signed_by, self.admin)

        response = self.client.post(
            reverse("exams:admin_grade_record_publish", args=[self.record.pk]),
            follow=True,
        )
        self.record.refresh_from_db()
        self.assertTrue(self.record.transcript_published)
        self.assertContains(response, "publié")

    def test_publish_requires_signed_pv(self):
        self._create_published_grade()
        self.client.post(reverse("exams:admin_grade_record_publish", args=[self.record.pk]))
        self.record.refresh_from_db()
        self.assertFalse(self.record.transcript_published)

    def test_publish_blocked_without_published_grade(self):
        self.client.post(reverse("exams:admin_grade_record_sign", args=[self.record.pk]))
        response = self.client.post(
            reverse("exams:admin_grade_record_publish", args=[self.record.pk]),
            follow=True,
        )
        self.record.refresh_from_db()
        self.assertFalse(self.record.transcript_published)
        self.assertContains(response, "Publication impossible")

    def test_record_detail_recalculates_from_quiz_grades(self):
        self._create_published_grade(score="14.00")
        response = self.client.post(
            reverse("exams:admin_grade_record_detail", args=[self.record.pk]),
            {"action": "recalculate"},
        )
        self.assertRedirects(
            response,
            reverse("exams:admin_grade_record_detail", args=[self.record.pk]),
        )
        self.record.refresh_from_db()
        self.assertEqual(self.record.students_count, 1)
        self.assertEqual(self.record.admitted_count, 1)
        self.assertEqual(self.record.average, Decimal("14.00"))

    def test_statistics_use_computed_record(self):
        self._create_published_grade(score="14.00")
        self.client.post(
            reverse("exams:admin_grade_record_detail", args=[self.record.pk]),
            {"action": "recalculate"},
        )
        response = self.client.get(reverse("exams:admin_statistics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "100 %")
        self.assertContains(response, "14,0")
        self.assertNotContains(response, "Master 1 Maths")


class ProfExamTests(ExamFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.prof_user)

    def test_sessions_page_lists_assigned_sessions(self):
        response = self.client.get(reverse("exams:prof_exam_sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INF501 · QCM Algorithmique")
        self.assertContains(response, "Générer avec l'IA")

    def test_unassigned_subject_cannot_create_quiz(self):
        other_subject = Subject.objects.create(
            university=self.university, program=self.program,
            name="Réseaux", code="INF502", semester=5,
        )
        session = ExamSession.objects.create(
            university=self.university, school_class=self.school_class,
            course_subject=other_subject, title="INF502 · QCM Réseaux",
            opens_at=self.now, closes_at=self.now + timedelta(hours=1),
        )
        response = self.client.get(reverse("exams:prof_quiz_create", args=[session.pk]))
        self.assertRedirects(response, reverse("exams:prof_exam_sessions"))

    def test_create_manual_quiz(self):
        response = self.client.post(
            reverse("exams:prof_quiz_create", args=[self.session.pk]),
            {
                "course": self.course.pk,
                "duration_minutes": 45,
                "pass_score": "10",
                "instructions": "Une seule tentative.",
            },
        )
        quiz = Quiz.objects.get(session=self.session)
        self.assertRedirects(response, reverse("exams:prof_quiz_edit", args=[quiz.pk]))
        self.assertEqual(quiz.duration_minutes, 45)
        self.assertEqual(quiz.status, Quiz.STATUS_DRAFT)

    def test_generate_quiz_with_ai_service(self):
        questions = [{
            "prompt": "Quelle structure permet un parcours en largeur ?",
            "explanation": "La file FIFO.",
            "choices": [
                {"label": "Une file", "is_correct": True},
                {"label": "Une pile", "is_correct": False},
                {"label": "Un arbre", "is_correct": False},
                {"label": "Un graphe", "is_correct": False},
            ],
        }]
        metadata = {
            "generated": 1, "requested": 1, "model": "test-model", "source_chars": 240,
        }
        with mock.patch(
            "exams.views.generate_quiz_questions",
            return_value=(questions, metadata),
        ):
            response = self.client.post(
                reverse("exams:prof_quiz_generate", args=[self.session.pk]),
                {
                    "course": self.course.pk,
                    "question_count": 1,
                    "difficulty": "moyen",
                    "duration_minutes": 30,
                    "pass_score": "10",
                    "shuffle_questions": "on",
                    "instructions": "Consignes",
                },
            )
        quiz = Quiz.objects.get(session=self.session)
        self.assertRedirects(response, reverse("exams:prof_quiz_edit", args=[quiz.pk]))
        self.assertEqual(quiz.questions.count(), 1)
        self.assertTrue(quiz.generated_by_ai)

    def test_publish_quiz_requires_valid_question(self):
        quiz, _question, _correct, _wrong = self._create_quiz(published=False)
        response = self.client.post(
            reverse("exams:prof_quiz_edit", args=[quiz.pk]),
            {"action": "publish"},
        )
        self.assertRedirects(response, reverse("exams:prof_exam_sessions"))
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, Quiz.STATUS_PUBLISHED)
        self.assertIsNotNone(quiz.published_at)

    def test_results_page_shows_analysis(self):
        quiz, question, correct, _wrong = self._create_quiz()
        self._create_attempt(quiz, question, correct)
        with mock.patch(
            "exams.services.ai_insights.ai_quiz_available", return_value=False,
        ):
            response = self.client.get(reverse("exams:prof_quiz_results", args=[quiz.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Camille Martin")
        self.assertContains(response, "Analyse pédagogique")

    def test_refresh_analysis(self):
        quiz, question, correct, _wrong = self._create_quiz()
        self._create_attempt(quiz, question, correct)
        with mock.patch(
            "exams.services.ai_insights.ai_quiz_available", return_value=False,
        ):
            response = self.client.post(
                reverse("exams:prof_quiz_analysis", args=[quiz.pk]),
            )
        self.assertRedirects(response, reverse("exams:prof_quiz_results", args=[quiz.pk]))
        quiz.refresh_from_db()
        self.assertEqual(quiz.ai_analysis["source"], "local")

    def test_foreign_quiz_not_accessible(self):
        foreign_quiz = Quiz.objects.create(
            university=self.other_university, session=self.foreign_session,
            status=Quiz.STATUS_PUBLISHED, published_at=self.now,
        )
        response = self.client.get(
            reverse("exams:prof_quiz_edit", args=[foreign_quiz.pk]),
        )
        self.assertEqual(response.status_code, 404)


class StudentExamTests(ExamFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.student_user)

    def test_student_exams_lists_open_quiz(self):
        self._create_quiz()
        response = self.client.get(reverse("exams:student_exams"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INF501 · QCM Algorithmique")
        self.assertContains(response, "Commencer le QCM")

    def test_student_quiz_full_flow(self):
        quiz, question, correct, wrong = self._create_quiz()
        start = self.client.post(
            reverse("exams:student_quiz_start", args=[self.session.pk]),
        )
        attempt = QuizAttempt.objects.get(quiz=quiz, student=self.student_profile)
        self.assertRedirects(
            start, reverse("exams:student_quiz_take", args=[attempt.pk]),
        )

        page = self.client.get(reverse("exams:student_quiz_take", args=[attempt.pk]))
        self.assertContains(page, question.prompt)

        save = self.client.post(
            reverse("exams:student_quiz_save", args=[attempt.pk]),
            {"q_%s" % question.pk: wrong.pk},
        )
        self.assertEqual(save.json()["saved"], 1)

        response = self.client.post(
            reverse("exams:student_quiz_submit", args=[attempt.pk]),
            {"q_%s" % question.pk: correct.pk},
        )
        self.assertRedirects(
            response, reverse("exams:student_quiz_result", args=[attempt.pk]),
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, Decimal("1.00"))
        self.assertEqual(attempt.score_20, Decimal("20.00"))

        grade = StudentGrade.objects.get(session=self.session, student=self.student_profile)
        self.assertEqual(grade.status, StudentGrade.STATUS_PUBLISHED)
        self.assertFalse(grade.is_absent)

        with mock.patch(
            "exams.services.ai_insights.ai_quiz_available", return_value=False,
        ):
            result = self.client.get(
                reverse("exams:student_quiz_result", args=[attempt.pk]),
            )
        self.assertContains(result, "QCM validé")
        self.assertContains(result, "Feedback personnalisé")

    def test_student_feedback_refresh(self):
        quiz, question, correct, _wrong = self._create_quiz()
        attempt = self._create_attempt(quiz, question, correct)
        with mock.patch(
            "exams.services.ai_insights.ai_quiz_available", return_value=False,
        ):
            response = self.client.post(
                reverse("exams:student_quiz_feedback", args=[attempt.pk]),
            )
        self.assertRedirects(
            response, reverse("exams:student_quiz_result", args=[attempt.pk]),
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.ai_feedback["source"], "local")

    def test_quiz_before_window_is_blocked(self):
        self.session.opens_at = self.now + timedelta(hours=1)
        self.session.closes_at = self.now + timedelta(hours=2)
        self.session.save(update_fields=["opens_at", "closes_at"])
        quiz, _question, _correct, _wrong = self._create_quiz()
        response = self.client.get(
            reverse("exams:student_quiz_start", args=[self.session.pk]),
        )
        self.assertRedirects(response, reverse("exams:student_exams"))
        self.assertFalse(QuizAttempt.objects.filter(quiz=quiz).exists())

    def test_quiz_after_window_is_blocked(self):
        self.session.opens_at = self.now - timedelta(hours=2)
        self.session.closes_at = self.now - timedelta(hours=1)
        self.session.save(update_fields=["opens_at", "closes_at"])
        quiz, _question, _correct, _wrong = self._create_quiz()
        response = self.client.get(
            reverse("exams:student_quiz_start", args=[self.session.pk]),
        )
        self.assertRedirects(
            response, reverse("exams:student_exams"),
            fetch_redirect_response=False,
        )
        self.assertFalse(QuizAttempt.objects.filter(quiz=quiz).exists())

    def test_auto_absence_after_window(self):
        self.session.opens_at = self.now - timedelta(hours=2)
        self.session.closes_at = self.now - timedelta(hours=1)
        self.session.save(update_fields=["opens_at", "closes_at"])
        quiz, _question, _correct, _wrong = self._create_quiz()
        response = self.client.get(reverse("exams:student_exams"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Absent")

        attempt = QuizAttempt.objects.get(quiz=quiz, student=self.student_profile)
        self.assertTrue(attempt.is_absent)
        grade = StudentGrade.objects.get(session=self.session, student=self.student_profile)
        self.assertTrue(grade.is_absent)
        self.assertEqual(grade.score, Decimal("0.00"))

        self.client.get(reverse("exams:student_exams"))
        self.assertEqual(
            QuizAttempt.objects.filter(quiz=quiz, student=self.student_profile).count(),
            1,
        )

    def test_transcript_hidden_until_published(self):
        self._create_published_grade(score="14.00")
        response = self.client.get(reverse("exams:student_transcript"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "INF501 · QCM Algorithmique")

        self.record.transcript_published = True
        self.record.published_at = self.now
        self.record.save(update_fields=["transcript_published", "published_at"])
        response = self.client.get(reverse("exams:student_transcript"))
        self.assertContains(response, "INF501 · QCM Algorithmique")
        self.assertContains(response, "14")

    def test_transcript_and_attestation_pdfs(self):
        self._create_published_grade(score="14.00")
        self.record.transcript_published = True
        self.record.published_at = self.now
        self.record.save(update_fields=["transcript_published", "published_at"])

        response = self.client.get(reverse("exams:student_transcript_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

        response = self.client.get(reverse("exams:student_attestation_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_attestation_requires_average_10(self):
        self._create_published_grade(score="8.00")
        self.record.transcript_published = True
        self.record.published_at = self.now
        self.record.save(update_fields=["transcript_published", "published_at"])

        response = self.client.get(reverse("exams:student_attestation_pdf"))
        self.assertRedirects(response, reverse("exams:student_transcript"))


class AiInsightFallbackTests(ExamFixtureMixin, TestCase):
    def test_student_feedback_local_fallback(self):
        quiz, question, correct, _wrong = self._create_quiz()
        attempt = self._create_attempt(quiz, question, correct)
        with mock.patch(
            "exams.services.ai_insights.ai_quiz_available", return_value=False,
        ):
            feedback = generate_student_feedback(attempt, force=True)
        self.assertEqual(feedback["source"], "local")
        attempt.refresh_from_db()
        self.assertEqual(attempt.ai_feedback["source"], "local")

    def test_quiz_analysis_local_fallback(self):
        quiz, question, correct, _wrong = self._create_quiz()
        attempt = self._create_attempt(quiz, question, correct)
        with mock.patch(
            "exams.services.ai_insights.ai_quiz_available", return_value=False,
        ):
            analysis = generate_quiz_analysis(quiz, [attempt], force=True)
        self.assertEqual(analysis["source"], "local")
        quiz.refresh_from_db()
        self.assertEqual(quiz.ai_analysis["source"], "local")


class ProjectOralExamTests(ExamFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.media_dir = tempfile.mkdtemp(prefix="eduspark-exams-")
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir)
        self.media_override.enable()

        self.project_session = ExamSession.objects.create(
            university=self.university, school_class=self.school_class,
            course_subject=self.subject, title="INF501 · Projet",
            exam_type=ExamSession.TYPE_PROJECT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=2),
            created_by=self.admin,
        )
        self.criterion = ProjectCriterion.objects.create(
            session=self.project_session, label="Fonctionnalités",
            description="Le projet répond au cahier des charges.", weight=2, order=1,
        )
        self.oral_session = ExamSession.objects.create(
            university=self.university, school_class=self.school_class,
            course_subject=self.subject, title="INF501 · Oral",
            exam_type=ExamSession.TYPE_ORAL,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=2),
            created_by=self.admin,
        )
        self.topic = OralTopic.objects.create(
            session=self.oral_session, title="Sujet A · Graphes",
            instructions="Présentez un algorithme de parcours.", duration_minutes=10,
        )

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)
        super().tearDown()

    def _zip_payload(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("README.md", "# Projet de test\n")
            archive.writestr("main.py", "print('bonjour')\n")
        return buffer.getvalue()

    def _submit_project(self):
        self.client.force_login(self.student_user)
        return self.client.post(
            reverse("exams:student_project_exam", args=[self.project_session.pk]),
            {"file": SimpleUploadedFile(
                "projet.zip", self._zip_payload(), content_type="application/zip",
            )},
        )

    def test_student_submits_project_zip(self):
        self.client.force_login(self.student_user)
        response = self.client.get(
            reverse("exams:student_project_exam", args=[self.project_session.pk]),
        )
        self.assertEqual(response.status_code, 200)

        response = self._submit_project()
        self.assertRedirects(
            response,
            reverse("exams:student_project_exam", args=[self.project_session.pk]),
        )
        submission = ProjectSubmission.objects.get(
            session=self.project_session, student=self.student_profile,
        )
        self.assertEqual(submission.status, ProjectSubmission.STATUS_SUBMITTED)
        self.assertEqual(submission.original_name, "projet.zip")
        self.assertGreater(submission.size, 0)
        self.assertTrue(submission.file.name.startswith("exams/projects/"))

        response = self.client.get(reverse("exams:student_exams"))
        self.assertContains(response, "Projet déposé")

    def test_project_requires_open_window_and_zip(self):
        self.project_session.closes_at = self.now - timedelta(minutes=1)
        self.project_session.save(update_fields=["closes_at"])
        self.client.force_login(self.student_user)
        response = self.client.post(
            reverse("exams:student_project_exam", args=[self.project_session.pk]),
            {"file": SimpleUploadedFile(
                "projet.txt", b"pas un zip", content_type="text/plain",
            )},
        )
        self.assertRedirects(
            response,
            reverse("exams:student_project_exam", args=[self.project_session.pk]),
        )
        self.assertFalse(ProjectSubmission.objects.exists())

    def test_professor_edits_project_criterion(self):
        self.client.force_login(self.prof_user)
        response = self.client.post(
            reverse("exams:prof_project_exam", args=[self.project_session.pk]),
            {
                "action": "edit_criterion",
                "criterion_id": self.criterion.pk,
                "label": "Fonctionnalités avancées",
                "description": "Le projet couvre les fonctionnalités bonus.",
                "weight": "4",
            },
        )
        self.assertRedirects(
            response,
            reverse("exams:prof_project_exam", args=[self.project_session.pk]),
        )
        self.criterion.refresh_from_db()
        self.assertEqual(self.criterion.label, "Fonctionnalités avancées")
        self.assertEqual(self.criterion.description, "Le projet couvre les fonctionnalités bonus.")
        self.assertEqual(self.criterion.weight, 4)

    def test_professor_edit_criterion_keeps_editor_open_on_invalid_weight(self):
        self.client.force_login(self.prof_user)
        response = self.client.post(
            reverse("exams:prof_project_exam", args=[self.project_session.pk]),
            {
                "action": "edit_criterion",
                "criterion_id": self.criterion.pk,
                "label": "Fonctionnalités",
                "description": "Le projet répond au cahier des charges.",
                "weight": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("weight", response.context["edit_criterion_form"].errors)
        self.criterion.refresh_from_db()
        self.assertEqual(self.criterion.weight, 2)

    def test_professor_cannot_edit_criterion_from_another_session(self):
        other_session = ExamSession.objects.create(
            university=self.university, school_class=self.school_class,
            course_subject=self.subject, title="INF501 · Projet bis",
            exam_type=ExamSession.TYPE_PROJECT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=2),
            created_by=self.admin,
        )
        other_criterion = ProjectCriterion.objects.create(
            session=other_session, label="Critère externe", weight=1,
        )
        self.client.force_login(self.prof_user)
        response = self.client.post(
            reverse("exams:prof_project_exam", args=[self.project_session.pk]),
            {
                "action": "edit_criterion",
                "criterion_id": other_criterion.pk,
                "label": "Critère piraté",
                "description": "",
                "weight": "5",
            },
        )
        self.assertEqual(response.status_code, 404)
        other_criterion.refresh_from_db()
        self.assertEqual(other_criterion.label, "Critère externe")
        self.assertEqual(other_criterion.weight, 1)

    def test_professor_evaluates_project_with_ai(self):
        self._submit_project()
        submission = ProjectSubmission.objects.get(
            session=self.project_session, student=self.student_profile,
        )
        self.client.force_login(self.prof_user)
        with mock.patch(
            "exams.views.evaluate_project",
            return_value={
                "score_20": 16.5, "model": "test-model",
                "criteria": [{"label": "Fonctionnalités", "score": 4}],
                "summary": "Projet solide.",
            },
        ):
            response = self.client.post(
                reverse("exams:prof_project_submission", args=[submission.pk]),
                {"action": "evaluate_ai"},
            )
        self.assertRedirects(
            response,
            reverse("exams:prof_project_submission", args=[submission.pk]),
        )
        submission.refresh_from_db()
        self.assertEqual(submission.ai_score, Decimal("16.50"))
        self.assertEqual(submission.ai_model, "test-model")
        self.assertEqual(submission.status, ProjectSubmission.STATUS_AI_EVALUATED)

    def test_professor_grades_project_and_syncs_grade(self):
        self._submit_project()
        submission = ProjectSubmission.objects.get(
            session=self.project_session, student=self.student_profile,
        )
        self.client.force_login(self.prof_user)
        response = self.client.post(
            reverse("exams:prof_project_submission", args=[submission.pk]),
            {"action": "grade", "score": "15.5", "feedback": "Bon travail"},
        )
        self.assertRedirects(
            response,
            reverse("exams:prof_project_submission", args=[submission.pk]),
        )
        submission.refresh_from_db()
        self.assertEqual(submission.final_score, Decimal("15.50"))
        self.assertEqual(submission.status, ProjectSubmission.STATUS_GRADED)
        grade = StudentGrade.objects.get(
            session=self.project_session, student=self.student_profile,
        )
        self.assertEqual(grade.score, Decimal("15.50"))
        self.assertEqual(grade.status, StudentGrade.STATUS_PUBLISHED)
        self.assertEqual(grade.comment, "Bon travail")

    def test_professor_downloads_project(self):
        self._submit_project()
        submission = ProjectSubmission.objects.get(
            session=self.project_session, student=self.student_profile,
        )
        self.client.force_login(self.prof_user)
        response = self.client.get(
            reverse("exams:prof_project_download", args=[submission.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            response["Content-Type"], ("application/zip", "application/x-zip-compressed"),
        )
        self.assertIn("projet.zip", response["Content-Disposition"])

    def test_student_draws_oral_topic(self):
        self.client.force_login(self.student_user)
        response = self.client.get(
            reverse("exams:student_oral_exam", args=[self.oral_session.pk]),
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("exams:student_oral_exam", args=[self.oral_session.pk]),
            {"action": "draw"},
        )
        self.assertRedirects(
            response,
            reverse("exams:student_oral_exam", args=[self.oral_session.pk]),
        )
        attempt = OralAttempt.objects.get(
            session=self.oral_session, student=self.student_profile,
        )
        self.assertEqual(attempt.topic, self.topic)
        self.assertEqual(attempt.status, OralAttempt.STATUS_DRAWN)
        self.assertLessEqual(attempt.preparation_deadline, self.oral_session.closes_at)

        self.client.post(
            reverse("exams:student_oral_exam", args=[self.oral_session.pk]),
            {"action": "draw"},
        )
        self.assertEqual(
            OralAttempt.objects.filter(
                session=self.oral_session, student=self.student_profile,
            ).count(),
            1,
        )

    def test_professor_grades_oral_and_syncs_grade(self):
        self.client.force_login(self.student_user)
        self.client.post(
            reverse("exams:student_oral_exam", args=[self.oral_session.pk]),
            {"action": "draw"},
        )
        attempt = OralAttempt.objects.get(
            session=self.oral_session, student=self.student_profile,
        )
        self.client.force_login(self.prof_user)
        response = self.client.post(
            reverse("exams:prof_oral_exam", args=[self.oral_session.pk]),
            {
                "action": "grade", "attempt_id": str(attempt.pk),
                "score": "14", "feedback": "Bonne prestation",
            },
        )
        self.assertRedirects(
            response,
            reverse("exams:prof_oral_exam", args=[self.oral_session.pk]),
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, Decimal("14.00"))
        self.assertEqual(attempt.status, OralAttempt.STATUS_GRADED)
        grade = StudentGrade.objects.get(
            session=self.oral_session, student=self.student_profile,
        )
        self.assertEqual(grade.score, Decimal("14.00"))
        self.assertEqual(grade.status, StudentGrade.STATUS_PUBLISHED)

    def test_project_and_oral_pages_render_for_professor(self):
        self._submit_project()
        self.client.force_login(self.prof_user)
        project_response = self.client.get(
            reverse("exams:prof_project_exam", args=[self.project_session.pk]),
        )
        oral_response = self.client.get(
            reverse("exams:prof_oral_exam", args=[self.oral_session.pk]),
        )
        self.assertEqual(project_response.status_code, 200)
        self.assertEqual(oral_response.status_code, 200)

    def test_exam_dashboard_renders_for_each_role(self):
        for user in (self.student_user, self.prof_user, self.admin):
            self.client.force_login(user)
            response = self.client.get(reverse("exams:exam_dashboard"))
            self.assertEqual(response.status_code, 200, user.username)

    def test_professor_history_renders(self):
        self._submit_project()
        self.client.force_login(self.prof_user)
        response = self.client.get(reverse("exams:prof_exam_history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Projet")

    def test_admin_sessions_page_shows_exam_types(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("exams:admin_exam_sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Projets")
        self.assertContains(response, "Oraux")
