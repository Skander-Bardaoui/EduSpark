"""Thème clair / sombre partagé : gabarits, pages de chaque module, contrôles statiques."""

import importlib.util
import io
import re
from contextlib import redirect_stdout
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, University
from accounts.tenancy import Role

STATIC_THEME = Path(settings.BASE_DIR) / "static" / "theme"

# Une page étudiante par module.
MODULE_PAGES = {
    "users": "portal:student_class",
    "courses": "courses:student_catalogue",
    "exercises": "exercises:student_assignments",
    "exams": "exams:student_exams",
    "community": "community:student_announcements",
    "coaching": "coaching:student_dashboard",
}


def make_student(email, university):
    user = User.objects.create_user(username=email, email=email, password="Pass12345!")
    Membership.objects.create(user=user, university=university, role=Role.STUDENT, is_active=True).ensure_profile()
    return user


class ThemeTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.univ = University.objects.create(name="Université Lumière", code="UL")
        cls.other = University.objects.create(name="Université Ombre", code="UO")
        cls.student = make_student("etudiant@lumiere.test", cls.univ)

    def head(self, response):
        html = response.content.decode()
        return html[:html.index("</head>")]

    def test_anti_flash_script_runs_before_any_stylesheet(self):
        self.client.force_login(self.student)
        head = self.head(self.client.get(reverse("portal:student_class")))
        script = head.index("localStorage.getItem('eduspark-theme')")
        self.assertLess(script, head.index("theme/theme.css"))
        self.assertLess(script, head.index("cdn.tailwindcss.com"))
        self.assertLess(script, head.index("fonts.googleapis.com/css2"))
        self.assertIn("setAttribute('data-theme'", head)

    def test_portal_header_has_accessible_toggle(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("portal:student_class"))
        self.assertContains(response, 'data-theme-toggle=""')
        self.assertContains(response, 'aria-label="Changer le thème, actuellement : système"')
        self.assertContains(response, 'aria-live="polite" class="sr-only" data-theme-status=""')
        self.assertContains(response, "theme/theme.js")
        self.assertContains(response, "theme/components.css")

    def test_tailwind_colors_come_from_theme_variables(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("portal:student_class"))
        self.assertContains(response, '"rgb(var(--md-"+n+") / <alpha-value>)"')
        self.assertContains(response, 'setAttribute("data-palette","student")')
        self.assertNotContains(response, '"primary":"#')

    def test_auth_pages_load_the_theme(self):
        for name in ("accounts:login", "accounts:signup"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "theme/theme.css")
                self.assertContains(response, 'setAttribute("data-palette","auth")')
                self.assertContains(response, 'data-theme-scope="light"')

    def test_one_page_per_module_renders_with_and_without_theme_cookie(self):
        self.client.force_login(self.student)
        for module, name in MODULE_PAGES.items():
            for cookie in (None, "dark", "light"):
                with self.subTest(module=module, cookie=cookie):
                    if cookie:
                        self.client.cookies["eduspark-theme"] = cookie
                    elif "eduspark-theme" in self.client.cookies:
                        del self.client.cookies["eduspark-theme"]
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'data-theme-toggle=""')

    def test_theme_does_not_bypass_tenant_isolation(self):
        intruder = make_student("etudiant@ombre.test", self.other)
        self.client.force_login(intruder)
        self.client.cookies["eduspark-theme"] = "dark"
        for name in MODULE_PAGES.values():
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.other.name)
                self.assertNotContains(response, self.univ.name)


class ThemeStaticTests(TestCase):
    def test_theme_js_stays_under_2_kb(self):
        self.assertLess((STATIC_THEME / "theme.js").stat().st_size, 2048)

    def test_dark_theme_is_screen_only(self):
        css = (STATIC_THEME / "theme.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r'(?m)^:root\[data-theme="dark"\]')
        self.assertIn('@media screen {\n  :root[data-theme="dark"] {', css)

    def test_contrast_check_passes(self):
        path = Path(settings.BASE_DIR) / "scripts" / "check_contrast.py"
        spec = importlib.util.spec_from_file_location("check_contrast", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = io.StringIO()
        with redirect_stdout(output):
            status = module.main([])
        self.assertEqual(status, 0, output.getvalue())

    def test_tailwind_color_list_matches_theme_tokens(self):
        css = (STATIC_THEME / "theme.css").read_text(encoding="utf-8")
        root = css[css.index(":root {"):css.index("}")]
        tokens = set(re.findall(r"--md-([\w-]+):", root))
        include = (Path(settings.BASE_DIR) / "templates" / "includes" / "tailwind_theme_colors.html").read_text(encoding="utf-8")
        names = set(re.findall(r'"([\w-]+)"', include.split("names=[", 1)[1].split("]", 1)[0]))
        self.assertEqual(names, tokens)
