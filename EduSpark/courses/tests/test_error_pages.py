"""Pages d'erreur personnalisées (403, 404, 500) servies par les gabarits du module cours."""

from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.views.defaults import server_error

from courses.models import Course

from .base import CoursesTestCase


@override_settings(DEBUG=False)
class ErrorPagesTests(CoursesTestCase):
    def assertErrorPage(self, response, code, heading):
        self.assertEqual(response.status_code, code)
        html = response.content.decode()
        self.assertIn('<p class="code">Erreur %d</p>' % code, html)
        self.assertIn('<h1 id="error-title">%s</h1>' % heading, html)
        # Structure accessible : contenu principal, titre unique, navigation, thème.
        self.assertIn('<main id="main-content">', html)
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn('href="#main-content"', html)
        self.assertIn("theme/theme.css", html)

    def test_unknown_url_shows_custom_404(self):
        self.login(self.student_user)
        self.assertErrorPage(self.client.get("/cette-page-n-existe-pas/"), 404, "Page introuvable")

    def test_course_of_another_university_is_a_custom_404(self):
        course = Course.objects.create(professor=self.other_prof, subject=self.other_subject, title="Ailleurs")
        self.login(self.prof_user)
        response = self.client.get(reverse("courses:prof_course_detail", args=[course.pk]))
        self.assertErrorPage(response, 404, "Page introuvable")

    def test_wrong_role_shows_custom_403_with_reason(self):
        self.login(self.student_user)
        response = self.client.get(reverse("courses:prof_course_create"))
        self.assertErrorPage(response, 403, "Accès refusé")
        self.assertContains(response, "Votre rôle ne permet pas d&#x27;accéder à cette page.", status_code=403)

    def test_server_error_page_renders_without_context(self):
        response = server_error(RequestFactory().get("/"))
        self.assertErrorPage(response, 500, "Une erreur est survenue")
