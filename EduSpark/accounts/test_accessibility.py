"""Menu Accessibilité : nettoyage des préférences, enregistrement, isolation et affichage."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .accessibility import DEFAULTS, clean_preferences
from .models import Membership, University
from .tenancy import Role

PASSWORD = "Pass12345!"
URL = "portal:accessibility_preferences"


def create_member(email, university, role):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD)
    membership = Membership.objects.create(user=user, university=university, role=role, is_active=True)
    membership.ensure_profile()
    return user


class CleanPreferencesTests(TestCase):
    def test_defaults_when_nothing_is_given(self):
        self.assertEqual(clean_preferences(None), DEFAULTS)
        self.assertEqual(clean_preferences([]), DEFAULTS)

    def test_unknown_keys_are_ignored(self):
        prefs = clean_preferences({"text_size": 150, "evil": "<script>", "__proto__": {}})
        self.assertNotIn("evil", prefs)
        self.assertNotIn("__proto__", prefs)
        self.assertEqual(prefs["text_size"], 150)
        self.assertEqual(set(prefs), set(DEFAULTS))

    def test_invalid_values_fall_back_to_defaults(self):
        prefs = clean_preferences({
            "text_size": 300, "theme": "violet", "speech_rate": 3, "contrast": 1,
            "spacing": None, "dyslexia_font": "oui",
        })
        for key in ("text_size", "theme", "speech_rate", "contrast", "spacing", "dyslexia_font"):
            self.assertEqual(prefs[key], DEFAULTS[key], key)

    def test_string_true_is_refused_for_booleans(self):
        self.assertIs(clean_preferences({"contrast": "true"})["contrast"], False)
        self.assertIs(clean_preferences({"contrast": True})["contrast"], True)

    def test_boolean_is_not_a_valid_size(self):
        self.assertEqual(clean_preferences({"text_size": True, "speech_rate": True}), DEFAULTS)

    def test_valid_values_are_kept(self):
        data = {
            "text_size": 175, "theme": "dark", "contrast": True, "dyslexia_font": True, "spacing": True,
            "reduce_motion": True, "underline_links": True, "strong_focus": True, "big_cursor": True,
            "reading_guide": True, "speech_rate": 0.75,
        }
        self.assertEqual(clean_preferences(data), data)


class AccessibilityViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.univ = University.objects.create(name="Université Accessible")
        cls.alice = create_member("alice@acc.test", cls.univ, Role.STUDENT)
        cls.bob = create_member("bob@acc.test", cls.univ, Role.STUDENT)

    def post(self, data, raw=None):
        body = raw if raw is not None else json.dumps(data)
        return self.client.post(reverse(URL), body, content_type="application/json")

    def test_post_saves_and_returns_cleaned_preferences(self):
        self.client.force_login(self.alice)
        response = self.post({"text_size": 150, "contrast": True, "theme": "nuit", "unknown": 1})
        self.assertEqual(response.status_code, 200)
        expected = dict(DEFAULTS, text_size=150, contrast=True)
        self.assertEqual(response.json(), expected)
        self.alice.profil.refresh_from_db()
        self.assertEqual(self.alice.profil.accessibility, expected)

    def test_anonymous_is_redirected_to_login(self):
        response = self.post({"contrast": True})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_get_is_not_allowed(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse(URL)).status_code, 405)

    def test_invalid_json_is_rejected(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.post(None, raw="{pas du json").status_code, 400)
        self.assertEqual(self.post(None, raw="[1, 2]").status_code, 400)
        self.alice.profil.refresh_from_db()
        self.assertEqual(self.alice.profil.accessibility, {})

    def test_csrf_token_is_required(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.alice)
        response = client.post(reverse(URL), json.dumps({"contrast": True}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_preferences_of_one_user_do_not_affect_another(self):
        self.client.force_login(self.alice)
        self.post({"text_size": 175, "big_cursor": True})
        self.bob.profil.refresh_from_db()
        self.assertEqual(self.bob.profil.accessibility, {})

        self.client.force_login(self.bob)
        page = self.client.get(reverse("portal:student_profile"))
        self.assertIsNone(page.context["accessibility_prefs"])
        self.assertContains(page, '<script id="a11y-prefs" type="application/json">null</script>', html=False)


class AccessibilityPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.univ = University.objects.create(name="Université Accessible")
        cls.admin = create_member("admin@acc.test", cls.univ, Role.UNIVERSITY_ADMIN)
        cls.prof = create_member("prof@acc.test", cls.univ, Role.PROFESSOR)
        cls.student = create_member("etudiant@acc.test", cls.univ, Role.STUDENT)

    def test_three_profile_pages_show_the_accessibility_section(self):
        for user, name in ((self.admin, "portal:admin_profile"), (self.prof, "portal:prof_profile"),
                           (self.student, "portal:student_profile")):
            with self.subTest(page=name):
                self.client.force_login(user)
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertIn('id="profile-accessibility"', html)
                self.assertIn('id="profile-a11y-title">Accessibilité</h2>', html)
                # Ids uniques : la section et le panneau de la barre coexistent.
                self.assertIn('id="profile-contrast-label"', html)
                self.assertIn('id="panel-contrast-label"', html)
                self.assertLess(html.index('id="profile-edit"'), html.index('id="profile-accessibility"'))

    def test_portal_page_has_the_button_panel_and_saved_preferences(self):
        self.student.profil.accessibility = {"text_size": 125, "dyslexia_font": True}
        self.student.profil.save()
        self.client.force_login(self.student)
        response = self.client.get(reverse("portal:student_class"))
        self.assertContains(response, 'aria-label="Accessibilité (Alt+A)"')
        self.assertContains(response, 'aria-haspopup="dialog"')
        self.assertContains(response, 'role="dialog"')
        self.assertContains(response, 'aria-modal="true"')
        self.assertContains(response, 'role="switch"')
        prefs = response.context["accessibility_prefs"]
        self.assertEqual(prefs["text_size"], 125)
        self.assertTrue(prefs["dyslexia_font"])
        html = response.content.decode()
        start = html.index('<script id="a11y-prefs" type="application/json">') + len('<script id="a11y-prefs" type="application/json">')
        self.assertEqual(json.loads(html[start:html.index("</script>", start)]), prefs)
        # Le script d'application précoce est dans <head>, avant le rendu.
        self.assertLess(html.index('id="a11y-prefs"'), html.index("</head>"))
