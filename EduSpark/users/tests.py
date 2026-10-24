from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Invitation, Membership, ProfessorProfile, SchoolClass, StudentGroup, StudentProfile, University,
)
from .services.ai import AIUnavailable
from .tenancy import SESSION_KEY, Role

User = get_user_model()


def make_user(email, password="Pass-12345!", **extra):
    return User.objects.create_user(username=email, email=email, password=password, **extra)


def add_member(user, university, role, active=True):
    membership = Membership.objects.create(user=user, university=university, role=role, is_active=active)
    membership.ensure_profile()
    return membership


class TenantTestCase(TestCase):
    """Deux universités, chacune avec un admin, un prof et un étudiant."""

    @classmethod
    def setUpTestData(cls):
        cls.u1 = University.objects.create(name="Université Alpha", code="UA", email_domain="alpha.tn")
        cls.u2 = University.objects.create(name="Université Beta", code="UB")
        cls.platform = User.objects.create_superuser("root@eduspark.tn", "root@eduspark.tn", "Pass-12345!")
        cls.admin1 = make_user("admin@alpha.tn")
        cls.admin2 = make_user("admin@beta.tn")
        cls.prof1 = make_user("prof@alpha.tn", first_name="Ada", last_name="Lovelace")
        cls.prof2 = make_user("prof@beta.tn")
        cls.student1 = make_user("etu@alpha.tn")
        add_member(cls.admin1, cls.u1, Role.UNIVERSITY_ADMIN)
        add_member(cls.admin2, cls.u2, Role.UNIVERSITY_ADMIN)
        cls.prof1_profile = add_member(cls.prof1, cls.u1, Role.PROFESSOR).professor_profile
        cls.prof2_profile = add_member(cls.prof2, cls.u2, Role.PROFESSOR).professor_profile
        cls.student1_profile = add_member(cls.student1, cls.u1, Role.STUDENT).student_profile

    def login(self, user, university=None):
        self.client.force_login(user)
        if university is not None:
            session = self.client.session
            session[SESSION_KEY] = university.pk
            session.save()


class MiddlewareTests(TenantTestCase):
    def test_university_resolved_from_membership(self):
        self.login(self.admin1)
        response = self.client.get(reverse("users:dashboard"))
        self.assertEqual(response.wsgi_request.university, self.u1)
        self.assertEqual(response.wsgi_request.university_role, Role.UNIVERSITY_ADMIN)

    def test_session_cannot_point_to_foreign_university(self):
        self.login(self.admin1, university=self.u2)
        response = self.client.get(reverse("users:dashboard"))
        self.assertEqual(response.wsgi_request.university, self.u1)

    def test_professor_in_two_universities_can_switch(self):
        add_member(self.prof1, self.u2, Role.PROFESSOR)
        self.login(self.prof1, university=self.u1)
        response = self.client.post(reverse("users:university_switch"), {"university": self.u2.pk})
        self.assertRedirects(response, reverse("users:dashboard"))
        self.assertEqual(self.client.session[SESSION_KEY], self.u2.pk)

    def test_cannot_switch_to_university_without_membership(self):
        self.login(self.prof1)
        response = self.client.post(reverse("users:university_switch"), {"university": self.u2.pk})
        self.assertEqual(response.status_code, 404)

    def test_pending_membership_gives_no_university(self):
        pending = make_user("pending@x.tn")
        add_member(pending, self.u1, Role.STUDENT, active=False)
        self.login(pending)
        response = self.client.get(reverse("users:dashboard"))
        self.assertIsNone(response.wsgi_request.university)
        self.assertContains(response, "en attente de validation")
        self.assertRedirects(self.client.get(reverse("users:class_list")), reverse("users:university_switch"))

    def test_platform_admin_can_enter_any_university(self):
        self.login(self.platform)
        self.client.post(reverse("users:university_switch"), {"university": self.u2.pk})
        response = self.client.get(reverse("users:professor_list"))
        self.assertEqual(response.wsgi_request.university, self.u2)
        self.assertContains(response, "prof@beta.tn")


class IsolationTests(TenantTestCase):
    """Un utilisateur ne voit jamais les données d'une autre université."""

    def test_lists_only_show_current_university(self):
        self.login(self.admin1)
        response = self.client.get(reverse("users:professor_list"))
        self.assertContains(response, "prof@alpha.tn")
        self.assertNotContains(response, "prof@beta.tn")

    def test_detail_update_delete_of_foreign_object_is_404(self):
        self.login(self.admin1)
        pk = self.prof2_profile.pk
        for name in ("professor_detail", "professor_update", "professor_delete"):
            self.assertEqual(self.client.get(reverse(f"users:{name}", args=[pk])).status_code, 404, name)
        self.assertEqual(self.client.post(reverse("users:professor_delete", args=[pk])).status_code, 404)
        self.assertTrue(ProfessorProfile.objects.filter(pk=pk).exists())

    def test_foreign_class_and_group_are_404(self):
        foreign = SchoolClass.objects.create(university=self.u2, name="B1")
        group = StudentGroup.objects.create(school_class=foreign, name="G1")
        self.login(self.admin1)
        self.assertEqual(self.client.get(reverse("users:class_detail", args=[foreign.pk])).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("users:group_update", args=[foreign.pk, group.pk])).status_code, 404,
        )
        self.assertEqual(self.client.get(reverse("users:group_create", args=[foreign.pk])).status_code, 404)

    def test_foreign_university_detail_is_404(self):
        self.login(self.admin1)
        self.assertEqual(self.client.get(reverse("users:university_detail", args=[self.u2.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("users:university_detail", args=[self.u1.pk])).status_code, 200)

    def test_created_objects_get_current_university(self):
        self.login(self.admin1)
        self.client.post(reverse("users:class_create"), {"name": "3A", "academic_year": "2025-2026"})
        self.assertEqual(SchoolClass.objects.get(name="3A").university, self.u1)

    def test_group_students_limited_to_university(self):
        school_class = SchoolClass.objects.create(university=self.u1, name="3A")
        foreign_student = add_member(make_user("etu@beta.tn"), self.u2, Role.STUDENT).student_profile
        self.login(self.admin1)
        response = self.client.post(
            reverse("users:group_create", args=[school_class.pk]),
            {"name": "G1", "students": [foreign_student.pk]},
        )
        self.assertEqual(response.status_code, 200)  # choix invalide
        self.assertFalse(StudentGroup.objects.exists())


class PermissionTests(TenantTestCase):
    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("users:professor_list"))
        self.assertRedirects(response, f"{reverse('users:login')}?next={reverse('users:professor_list')}")

    def test_role_matrix(self):
        cases = [
            (self.student1, "users:student_list", 403),
            (self.student1, "users:professor_list", 200),
            (self.student1, "users:class_list", 200),
            (self.student1, "users:invitation_list", 403),
            (self.prof1, "users:student_list", 200),
            (self.prof1, "users:professor_create", 403),
            (self.prof1, "users:class_create", 403),
            (self.admin1, "users:professor_create", 200),
            (self.admin1, "users:invitation_create", 200),
            (self.admin1, "users:university_list", 403),
            (self.admin1, "users:account_list", 403),
            (self.platform, "users:university_list", 200),
            (self.platform, "users:account_list", 200),
        ]
        for user, name, expected in cases:
            with self.subTest(user=user.email, url=name):
                self.login(user)
                self.assertEqual(self.client.get(reverse(name)).status_code, expected)

    def test_university_admin_cannot_invite_university_admin(self):
        self.login(self.admin1)
        response = self.client.post(reverse("users:invitation_create"), {
            "email": "new@alpha.tn", "role": Role.UNIVERSITY_ADMIN, "expires_at": "2099-01-01T10:00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invitation.objects.filter(email="new@alpha.tn").exists())

    def test_university_admin_edits_own_university_with_limited_form(self):
        self.login(self.admin1)
        response = self.client.post(reverse("users:university_update", args=[self.u1.pk]), {
            "code": "UA2", "city": "Tunis", "name": "Piratée", "is_active": "",
        })
        self.assertRedirects(response, reverse("users:university_detail", args=[self.u1.pk]))
        self.u1.refresh_from_db()
        self.assertEqual((self.u1.code, self.u1.name, self.u1.is_active), ("UA2", "Université Alpha", True))
        self.assertEqual(self.client.get(reverse("users:university_update", args=[self.u2.pk])).status_code, 404)


class CrudTests(TenantTestCase):
    def test_platform_admin_university_crud(self):
        self.login(self.platform)
        response = self.client.post(reverse("users:university_create"), {"name": "Université Gamma", "is_active": "on"})
        gamma = University.objects.get(name="Université Gamma")
        self.assertRedirects(response, reverse("users:university_detail", args=[gamma.pk]))
        self.assertEqual(gamma.slug, "universite-gamma")
        response = self.client.get(reverse("users:university_list"), {"q": "gamma"})
        self.assertContains(response, "Université Gamma")
        self.assertNotContains(response, "Université Beta")
        self.client.post(reverse("users:university_delete", args=[gamma.pk]))
        self.assertFalse(University.objects.filter(pk=gamma.pk).exists())

    def test_create_professor_new_account_sends_password_link(self):
        self.login(self.admin1)
        response = self.client.post(reverse("users:professor_create"), {
            "email": "Nouveau@Alpha.tn", "first_name": "Alan", "last_name": "Turing",
            "department": "Informatique", "speciality": "IA", "grade": "professeur",
        })
        profile = ProfessorProfile.objects.get(membership__user__email="nouveau@alpha.tn")
        self.assertRedirects(response, reverse("users:professor_detail", args=[profile.pk]))
        self.assertEqual((profile.university, profile.department, profile.grade), (self.u1, "Informatique", "professeur"))
        self.assertFalse(profile.user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reinitialiser/", mail.outbox[0].body)

    def test_existing_professor_joins_second_university(self):
        self.login(self.admin2)
        self.client.post(reverse("users:professor_create"), {
            "email": "prof@alpha.tn", "first_name": "x", "last_name": "y", "department": "Maths",
        })
        self.assertEqual(User.objects.filter(email="prof@alpha.tn").count(), 1)
        self.assertEqual(self.prof1.memberships.count(), 2)
        self.assertEqual(ProfessorProfile.objects.get(university=self.u2, membership__user=self.prof1).department, "Maths")
        self.assertEqual(self.prof1_profile.department, "")  # profil de l'autre université intact

    def test_delete_professor_keeps_account(self):
        self.login(self.admin1)
        self.client.post(reverse("users:professor_delete", args=[self.prof1_profile.pk]))
        self.assertFalse(Membership.objects.filter(user=self.prof1, university=self.u1).exists())
        self.assertTrue(User.objects.filter(pk=self.prof1.pk).exists())

    def test_student_search_and_filters(self):
        self.student1_profile.program = "Génie logiciel"
        self.student1_profile.save()
        other = add_member(make_user("autre@alpha.tn"), self.u1, Role.STUDENT).student_profile
        other.program = "Réseaux"
        other.save()
        self.login(self.admin1)
        response = self.client.get(reverse("users:student_list"), {"filiere": "Réseaux"})
        self.assertContains(response, "autre@alpha.tn")
        self.assertNotContains(response, "etu@alpha.tn")
        response = self.client.get(reverse("users:student_list"), {"q": "etu@"})
        self.assertContains(response, "etu@alpha.tn")
        self.assertNotContains(response, "autre@alpha.tn")

    def test_class_and_group_crud(self):
        self.login(self.admin1)
        self.client.post(reverse("users:class_create"), {
            "name": "3A", "level": "3e année", "academic_year": "2025-2026", "professors": [self.prof1_profile.pk],
        })
        school_class = SchoolClass.objects.get(name="3A")
        self.assertEqual(list(school_class.professors.all()), [self.prof1_profile])
        self.client.post(reverse("users:group_create", args=[school_class.pk]), {
            "name": "G1", "capacity": 30, "students": [self.student1_profile.pk],
        })
        group = StudentGroup.objects.get(name="G1")
        self.assertEqual((group.university, list(group.students.all())), (self.u1, [self.student1_profile]))
        # Doublon de nom refusé
        response = self.client.post(reverse("users:group_create", args=[school_class.pk]), {"name": "G1"})
        self.assertEqual(response.status_code, 200)
        self.client.post(reverse("users:class_delete", args=[school_class.pk]))
        self.assertFalse(StudentGroup.objects.exists())
        self.assertTrue(StudentProfile.objects.filter(pk=self.student1_profile.pk).exists())

    def test_every_admin_page_renders(self):
        school_class = SchoolClass.objects.create(university=self.u1, name="3A")
        group = StudentGroup.objects.create(school_class=school_class, name="G1")
        invitation = Invitation.objects.create(university=self.u1, email="x@y.tn", role=Role.STUDENT)
        self.login(self.admin1)
        urls = [
            reverse("users:dashboard"), reverse("users:profile"), reverse("users:university_switch"),
            reverse("users:university_detail", args=[self.u1.pk]), reverse("users:university_update", args=[self.u1.pk]),
            reverse("users:professor_list"), reverse("users:professor_create"),
            reverse("users:professor_detail", args=[self.prof1_profile.pk]),
            reverse("users:professor_update", args=[self.prof1_profile.pk]),
            reverse("users:professor_delete", args=[self.prof1_profile.pk]),
            reverse("users:student_list"), reverse("users:student_create"),
            reverse("users:student_detail", args=[self.student1_profile.pk]),
            reverse("users:student_update", args=[self.student1_profile.pk]),
            reverse("users:class_list"), reverse("users:class_create"),
            reverse("users:class_detail", args=[school_class.pk]), reverse("users:class_update", args=[school_class.pk]),
            reverse("users:group_create", args=[school_class.pk]),
            reverse("users:group_update", args=[school_class.pk, group.pk]),
            reverse("users:group_delete", args=[school_class.pk, group.pk]),
            reverse("users:invitation_list"), reverse("users:invitation_create"),
            reverse("users:invitation_detail", args=[invitation.pk]),
            reverse("users:invitation_update", args=[invitation.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.login(self.platform)
        for url in (reverse("users:university_list"), reverse("users:university_create"),
                    reverse("users:account_list"), reverse("users:account_detail", args=[self.prof1.pk]),
                    reverse("users:account_update", args=[self.prof1.pk]), reverse("users:dashboard")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class SignupTests(TenantTestCase):
    def _signup(self, email, role=Role.STUDENT, university=None):
        return self.client.post(reverse("users:signup"), {
            "full_name": "Jean Dupont", "email": email, "password1": "Tres-Secret-2026",
            "role": role, "university": (university or self.u1).pk,
        })

    def test_student_with_official_domain_is_validated(self):
        self._signup("jean@alpha.tn")
        membership = Membership.objects.get(user__email="jean@alpha.tn")
        self.assertTrue(membership.is_active)
        self.assertTrue(StudentProfile.objects.filter(membership=membership).exists())

    def test_other_signups_wait_for_validation(self):
        self._signup("jean@gmail.com")
        self.assertFalse(Membership.objects.get(user__email="jean@gmail.com").is_active)
        self.client.logout()
        self._signup("prof@alpha-mail.tn", role=Role.PROFESSOR)
        self.assertFalse(Membership.objects.get(user__email="prof@alpha-mail.tn").is_active)

    def test_admin_validates_pending_signup(self):
        self._signup("jean@gmail.com")
        membership = Membership.objects.get(user__email="jean@gmail.com")
        self.login(self.admin1)
        self.assertContains(self.client.get(reverse("users:dashboard")), "jean@gmail.com")
        self.client.post(reverse("users:membership_decide", args=[membership.pk]), {"decision": "approve"})
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)

    def test_signup_cannot_create_admin(self):
        self._signup("hacker@alpha.tn", role=Role.UNIVERSITY_ADMIN)
        self.assertFalse(User.objects.filter(email="hacker@alpha.tn").exists())


class InvitationTests(TenantTestCase):
    def test_invite_new_user_and_accept(self):
        self.login(self.admin1)
        self.client.post(reverse("users:invitation_create"), {
            "email": "nouveau@x.tn", "role": Role.PROFESSOR, "expires_at": "2099-01-01T10:00",
        })
        invitation = Invitation.objects.get(email="nouveau@x.tn")
        self.assertEqual((invitation.university, invitation.invited_by), (self.u1, self.admin1))
        self.assertEqual(len(mail.outbox), 1)
        self.client.logout()

        url = reverse("users:invitation_accept", args=[invitation.token])
        self.assertContains(self.client.get(url), "Créer mon compte")
        response = self.client.post(url, {
            "first_name": "Grace", "last_name": "Hopper",
            "new_password1": "Tres-Secret-2026", "new_password2": "Tres-Secret-2026",
        })
        self.assertRedirects(response, reverse("users:dashboard"))
        user = User.objects.get(email="nouveau@x.tn")
        self.assertTrue(user.check_password("Tres-Secret-2026"))
        self.assertTrue(ProfessorProfile.objects.filter(membership__user=user, university=self.u1).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.STATUS_ACCEPTED)
        self.assertEqual(self.client.get(url).context["state"], "invalid")

    def test_existing_user_accepts_with_own_account_only(self):
        invitation = Invitation.objects.create(university=self.u2, email="prof@alpha.tn", role=Role.PROFESSOR)
        url = reverse("users:invitation_accept", args=[invitation.token])
        self.assertEqual(self.client.get(url).context["state"], "login")
        self.login(self.student1)
        self.assertEqual(self.client.get(url).context["state"], "wrong_account")
        self.login(self.prof1)
        self.client.post(url)
        self.assertTrue(Membership.objects.filter(user=self.prof1, university=self.u2, is_active=True).exists())
        self.assertEqual(self.client.session[SESSION_KEY], self.u2.pk)

    def test_revoked_invitation_is_unusable(self):
        invitation = Invitation.objects.create(university=self.u1, email="z@z.tn", role=Role.STUDENT)
        self.login(self.admin1)
        self.client.post(reverse("users:invitation_action", args=[invitation.pk, "revoquer"]))
        self.client.logout()
        response = self.client.get(reverse("users:invitation_accept", args=[invitation.token]))
        self.assertEqual(response.context["state"], "invalid")

    def test_platform_admin_invites_university_admin(self):
        self.login(self.platform)
        self.client.post(reverse("users:university_invite_admin", args=[self.u2.pk]), {"email": "boss@beta.tn"})
        invitation = Invitation.objects.get(email="boss@beta.tn")
        self.assertEqual((invitation.university, invitation.role), (self.u2, Role.UNIVERSITY_ADMIN))


@override_settings(LANGUAGE_CODE="fr")
class AIFeatureTests(TenantTestCase):
    """L'IA est une fonctionnalité : sans elle, le profil reste utilisable."""

    def test_ai_unavailable_shows_message_and_keeps_input(self):
        self.login(self.prof1)
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}):
            response = self.client.post(reverse("users:profile"), {
                "action": "ai_bio", "first_name": "Ada", "last_name": "Lovelace", "bio": "mots-clés : algorithmes",
            })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pas configuré")
        self.assertContains(response, "mots-clés : algorithmes")
        self.prof1.refresh_from_db()
        self.assertEqual(self.prof1.bio, "")

    def test_ai_suggestion_is_not_saved_automatically(self):
        self.prof1_profile.speciality = "Algorithmique"
        self.prof1_profile.save()
        self.login(self.prof1)
        with mock.patch("users.views.core.generate_profile_bio", return_value="Je suis Ada.") as generate:
            response = self.client.post(reverse("users:profile"), {"action": "ai_bio", "bio": ""})
        self.assertContains(response, "Je suis Ada.")
        self.assertEqual(generate.call_args.kwargs["extra"]["Spécialité"], "Algorithmique")
        self.assertEqual(generate.call_args.kwargs["university"], self.u1)
        self.prof1.refresh_from_db()
        self.assertEqual(self.prof1.bio, "")
        self.client.post(reverse("users:profile"), {"action": "save", "first_name": "Ada", "bio": "Je suis Ada."})
        self.prof1.refresh_from_db()
        self.assertEqual(self.prof1.bio, "Je suis Ada.")

    def test_ai_error_from_service_is_displayed(self):
        self.login(self.student1)
        with mock.patch("users.views.core.generate_profile_bio", side_effect=AIUnavailable("Service en panne.")):
            response = self.client.post(reverse("users:profile"), {"action": "ai_bio"})
        self.assertContains(response, "Service en panne.")


class APITests(TenantTestCase):
    def test_jwt_login_and_me_with_university_header(self):
        add_member(self.prof1, self.u2, Role.PROFESSOR)
        response = self.client.post(
            reverse("users:token_obtain"), {"username": "PROF@alpha.tn", "password": "Pass-12345!"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["memberships"]), 2)
        auth = {"HTTP_AUTHORIZATION": f"Bearer {response.json()['access']}"}
        me = self.client.get(reverse("users:me"), HTTP_X_UNIVERSITY=self.u2.slug, **auth).json()
        self.assertEqual((me["current_university"]["id"], me["current_role"]), (self.u2.pk, Role.PROFESSOR))
        # Une université sans appartenance n'est jamais retenue
        foreign = University.objects.create(name="Gamma")
        me = self.client.get(reverse("users:me"), HTTP_X_UNIVERSITY=foreign.slug, **auth).json()
        self.assertNotEqual(me["current_university"]["id"], foreign.pk)
