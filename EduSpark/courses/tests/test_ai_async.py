"""Génération du plan de cours en tâche de fond (courses.services.jobs).

Les vues sont testées avec un lancement simulé (tâche laissée « en cours »)
ou en exécution immédiate (InlineJobsMixin) ; le lanceur lui-même est testé
avec un vrai thread.
"""

import threading
import uuid
from unittest import mock

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from accounts.tenancy import Role
from courses import ai_views
from courses.services import ai, jobs
from courses.tasks import STATUS_OK, STATUS_UNAVAILABLE, generate_syllabus_task

from .base import CoursesTestCase, join, make_user

FORM = {"title": "Algorithmique", "level": "L3", "chapter_count": 4,
        "total_hours": 18, "language": "fr", "style": "equilibre"}
OK_RESULT = {
    "status": STATUS_OK,
    "chapters": [{"title": "Graphes", "objectives": ["Définir un graphe"], "duration_hours": 4}],
    "topics": ["Graphes orientés"],
    "mode": ai.MODE_LOCAL_API,
    "local_status": ai.LOCAL_USED,
    "timings": {"local": 5.12, "api": 3.3, "total": 8.42},
}


class JobRunnerTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_unknown_job_is_none_and_counts_as_ready(self):
        self.assertIsNone(jobs.get("inconnue"))
        self.assertTrue(jobs.is_ready(None))

    def test_job_runs_in_a_background_thread(self):
        release, seen = threading.Event(), {}

        def slow(value):
            seen["thread"] = threading.current_thread().name
            release.wait(5)
            return value * 2

        with mock.patch.object(jobs, "RUN_INLINE", False), \
                mock.patch.object(jobs.connections, "close_all") as close_all:
            job_id = jobs.submit(slow, 21)
            # submit() rend la main tout de suite : la tâche n'est pas finie.
            self.assertIn(jobs.get(job_id)["state"], (jobs.PENDING, jobs.STARTED))
            self.assertFalse(jobs.is_ready(jobs.get(job_id)))
            release.set()
            for _ in range(100):
                if jobs.is_ready(jobs.get(job_id)):
                    break
                threading.Event().wait(0.05)
        self.assertEqual(jobs.get(job_id), {"state": jobs.SUCCESS, "result": 42})
        self.assertTrue(seen["thread"].startswith("courses-job"))
        close_all.assert_called_once()

    def test_unexpected_error_becomes_failure(self):
        def broken():
            raise RuntimeError("boum")

        with mock.patch.object(jobs, "RUN_INLINE", True), self.assertLogs("courses.services.jobs", "ERROR"):
            job_id = jobs.submit(broken)
        self.assertEqual(jobs.get(job_id), {"state": jobs.FAILURE, "result": None})
        self.assertTrue(jobs.is_ready(jobs.get(job_id)))

    def test_job_ids_are_unique_uuids(self):
        with mock.patch.object(jobs, "RUN_INLINE", True):
            ids = {jobs.submit(lambda: None) for _ in range(20)}
        self.assertEqual(len(ids), 20)
        for job_id in ids:
            uuid.UUID(job_id)


@override_settings(AI_PROVIDER="fake", AI_RATE_LIMIT_PER_HOUR=10)
class SyllabusAsyncViewTests(CoursesTestCase):
    def setUp(self):
        cache.clear()
        self.course = self.make_course()
        self.generate_url = reverse("courses:prof_ai_syllabus_generate", args=[self.course.pk])
        self.manual_url = reverse("courses:prof_ai_syllabus_manual", args=[self.course.pk])
        self.login(self.prof_user)

    def url(self, name, job_id):
        return reverse("courses:prof_ai_syllabus_%s" % name, args=[self.course.pk, job_id])

    def queue(self):
        """Lance une génération qui reste « en cours » ; renvoie l'id de la tâche."""
        job_id = str(uuid.uuid4())

        def fake_submit(func, *args):
            cache.set(jobs._key(job_id), {"state": jobs.PENDING, "result": None}, 60)
            fake_submit.args = args
            return job_id

        with mock.patch.object(jobs, "submit", side_effect=fake_submit):
            response = self.client.post(self.generate_url, FORM)
        self.assertEqual(fake_submit.args[:3], ("Algorithmique", "L3", self.course.pk))
        self.assertRedirects(response, self.url("wait", job_id))
        return job_id

    def finish(self, job_id, state=jobs.SUCCESS, result=None):
        cache.set(jobs._key(job_id), {"state": state, "result": result}, 60)

    # -- Lancement et page d'attente -------------------------------------------
    def test_generation_runs_in_background_and_request_returns_immediately(self):
        job_id = self.queue()
        page = self.client.get(self.url("wait", job_id))
        self.assertContains(page, "Génération du plan en cours")
        self.assertContains(page, 'role="status"')
        self.assertContains(page, 'aria-live="polite"')
        self.assertContains(page, 'data-status-url="%s"' % self.url("status", job_id))
        self.assertContains(page, self.url("result", job_id))
        self.assertContains(page, self.manual_url)

    def test_unknown_job_is_a_404(self):
        for name in ("wait", "status", "result"):
            with self.subTest(view=name):
                self.assertEqual(self.client.get(self.url(name, uuid.uuid4())).status_code, 404)

    def test_another_professor_cannot_follow_the_job(self):
        job_id = self.queue()
        other = make_user("autre.prof@ut.test", "Autre", "Prof")
        join(other, self.univ, Role.PROFESSOR)
        self.login(other)
        for name in ("wait", "status", "result"):
            with self.subTest(view=name):
                self.assertEqual(self.client.get(self.url(name, job_id)).status_code, 404)

    def test_student_cannot_follow_the_job(self):
        job_id = self.queue()
        self.login(self.student_user)
        self.assertEqual(self.client.get(self.url("status", job_id)).status_code, 403)

    def test_job_is_bound_to_its_course(self):
        job_id = self.queue()
        other_course = self.make_course(title="Autre cours")
        response = self.client.get(reverse("courses:prof_ai_syllabus_wait", args=[other_course.pk, job_id]))
        self.assertEqual(response.status_code, 404)

    @override_settings(AI_RATE_LIMIT_PER_HOUR=100)
    def test_session_keeps_only_the_last_jobs(self):
        for _ in range(ai_views.MAX_JOBS + 3):
            self.queue()
        self.assertEqual(len(self.client.session[ai_views.JOBS_SESSION_KEY]), ai_views.MAX_JOBS)

    # -- Statut ------------------------------------------------------------------
    def test_status_reports_the_job_state(self):
        job_id = self.queue()
        for state, ready in ((jobs.PENDING, False), (jobs.STARTED, False),
                             (jobs.SUCCESS, True), (jobs.FAILURE, True)):
            with self.subTest(state=state):
                self.finish(job_id, state)
                self.assertEqual(self.client.get(self.url("status", job_id)).json(), {"state": state, "ready": ready})

    def test_expired_job_is_reported_as_ready(self):
        job_id = self.queue()
        cache.delete(jobs._key(job_id))
        self.assertEqual(self.client.get(self.url("status", job_id)).json(), {"state": "EXPIRED", "ready": True})

    # -- Résultat ----------------------------------------------------------------
    def test_result_shows_the_preview_with_measured_timings(self):
        job_id = self.queue()
        self.finish(job_id, result=OK_RESULT)
        response = self.client.get(self.url("result", job_id))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aperçu du plan proposé")
        self.assertContains(response, 'value="Graphes"')
        self.assertContains(response, "Généré en 8.4 s (analyse locale 5.1 s · rédaction 3.3 s)")

    def test_result_not_ready_goes_back_to_the_waiting_page(self):
        job_id = self.queue()
        response = self.client.get(self.url("result", job_id))
        self.assertRedirects(response, self.url("wait", job_id), fetch_redirect_response=False)

    def test_unavailable_failed_or_expired_job_offers_manual_entry(self):
        cases = {
            "indisponible": (jobs.SUCCESS, {"status": STATUS_UNAVAILABLE, "message": "quota"}),
            "échec": (jobs.FAILURE, None),
            "expirée": (None, None),
        }
        for label, (state, result) in cases.items():
            with self.subTest(label):
                job_id = self.queue()
                if state is None:
                    cache.delete(jobs._key(job_id))
                else:
                    self.finish(job_id, state, result)
                response = self.client.get(self.url("result", job_id))
                self.assertRedirects(response, self.manual_url)
                self.assertIn(ai_views.UNAVAILABLE_MESSAGE, [str(m) for m in get_messages(response.wsgi_request)])

    # -- Exécution immédiate et limite d'appels --------------------------------
    def test_inline_execution_renders_the_preview_in_the_same_request(self):
        response = self.client.post(self.generate_url, FORM)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aperçu du plan proposé")
        self.assertContains(response, "data-ai-timings")

    def test_rate_limit_is_counted_before_launching(self):
        with override_settings(AI_RATE_LIMIT_PER_HOUR=1), \
                mock.patch.object(jobs, "submit", wraps=jobs.submit) as submit:
            self.client.post(self.generate_url, FORM)
            response = self.client.post(self.generate_url, FORM)
        self.assertEqual(submit.call_count, 1)
        self.assertRedirects(response, self.manual_url)

    # -- Tâche -------------------------------------------------------------------
    def test_task_returns_a_status_instead_of_raising(self):
        with mock.patch("courses.tasks.ai.generate_syllabus", side_effect=ai.AIUnavailable("API en panne")):
            self.assertEqual(
                generate_syllabus_task("Algo", "L3", self.course.pk, {}),
                {"status": STATUS_UNAVAILABLE, "message": "API en panne"},
            )
        result = generate_syllabus_task("Algo", "L3", self.course.pk, {})
        self.assertEqual(result["status"], STATUS_OK)
        self.assertEqual(set(result["timings"]), {"local", "api", "total"})
        self.assertGreaterEqual(result["timings"]["total"], 0)

