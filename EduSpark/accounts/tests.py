from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Invitation,
    Membership,
    ProfessorProfile,
    SchoolClass,
    StudentGroup,
    StudentProfile,
    University,
)
from .tenancy import Role, SESSION_KEY, resolve_tenant

PASSWORD = "Pass12345!"


def create_user(email, password=PASSWORD, **extra):
    return User.objects.create_user(username=email, email=email, password=password, **extra)


def create_university(name, domain="", **extra):
    return University.objects.create(name=name, email_domain=domain, **extra)


def add_membership(user, university, role, is_active=True, **profile_fields):
    membership, created = Membership.objects.get_or_create(
        user=user, university=university,
        defaults={"role": role, "is_active": is_active},
    )
    if not created:
        membership.role = role
        membership.is_active = is_active
        membership.save(update_fields=["role", "is_active"])
    profile = membership.ensure_profile()
    if profile is not None and profile_fields:
        for name, value in profile_fields.items():
            setattr(profile, name, value)
        profile.save()
    return membership


def invitation_payload(**overrides):
    data = {
        "email": "invite@example.com",
        "role": Role.PROFESSOR,
        "message": "",
        "expires_at": (timezone.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M"),
    }
    data.update(overrides)
    return data


class PortalTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.paris = create_university("Université Paris Test", "paris.fr")
        cls.lyon = create_university("Université Lyon Test", "lyon.fr")

        cls.platform = User.objects.create_superuser(
            username="platform@example.com", email="platform@example.com", password=PASSWORD,
        )
        cls.admin_paris = create_user("admin.paris@example.com", first_name="Sophie", last_name="Bernard")
        add_membership(cls.admin_paris, cls.paris, Role.UNIVERSITY_ADMIN)
        cls.admin_lyon = create_user("admin.lyon@example.com", first_name="Julien", last_name="Morel")
        add_membership(cls.admin_lyon, cls.lyon, Role.UNIVERSITY_ADMIN)

        cls.prof_user = create_user("prof@example.com", first_name="Hélène", last_name="Vasseur")
        cls.prof_paris_membership = add_membership(
            cls.prof_user, cls.paris, Role.PROFESSOR,
            department="Informatique", speciality="Systèmes distribués", grade="maitre_conferences",
        )
        cls.prof_paris = cls.prof_paris_membership.professor_profile
        cls.prof_lyon_membership = add_membership(
            cls.prof_user, cls.lyon, Role.PROFESSOR,
            department="Mathématiques", speciality="Probabilités", grade="professeur",
        )
        cls.prof_lyon = cls.prof_lyon_membership.professor_profile

        cls.prof_paris_only_user = create_user(
            "prof.paris@example.com", first_name="Ada", last_name="Paris",
        )
        cls.prof_paris_only_membership = add_membership(
            cls.prof_paris_only_user, cls.paris, Role.PROFESSOR, department="Informatique",
        )
        cls.prof_paris_only = cls.prof_paris_only_membership.professor_profile
        cls.prof_lyon_only_user = create_user(
            "prof.lyon@example.com", first_name="Marc", last_name="Lyon",
        )
        cls.prof_lyon_only_membership = add_membership(
            cls.prof_lyon_only_user, cls.lyon, Role.PROFESSOR, department="Mathématiques",
        )
        cls.prof_lyon_only = cls.prof_lyon_only_membership.professor_profile

        cls.student_paris_user = create_user(
            "etudiant.paris@paris.fr", first_name="Camille", last_name="Martin",
        )
        cls.student_paris_membership = add_membership(
            cls.student_paris_user, cls.paris, Role.STUDENT,
            student_number="P-001", program="Informatique", promotion="2026",
        )
        cls.student_paris = cls.student_paris_membership.student_profile
        cls.student_lyon_user = create_user(
            "etudiant.lyon@lyon.fr", first_name="Lucas", last_name="Lyon",
        )
        cls.student_lyon_membership = add_membership(
            cls.student_lyon_user, cls.lyon, Role.STUDENT,
            student_number="L-001", program="Mathématiques", promotion="2026",
        )
        cls.student_lyon = cls.student_lyon_membership.student_profile

        cls.class_paris = SchoolClass.objects.create(
            university=cls.paris, name="L3 Informatique", level="3e année",
            program="Informatique", academic_year="2025-2026",
        )
        cls.class_paris.professors.set([cls.prof_paris])
        cls.class_lyon = SchoolClass.objects.create(
            university=cls.lyon, name="M1 Mathématiques", level="Master 1",
            program="Mathématiques", academic_year="2025-2026",
        )
        cls.class_lyon.professors.set([cls.prof_lyon])

        cls.group_paris = StudentGroup.objects.create(
            school_class=cls.class_paris, name="TD A", capacity=20,
        )
        cls.group_paris.students.set([cls.student_paris])
        cls.group_lyon = StudentGroup.objects.create(
            school_class=cls.class_lyon, name="Groupe 1", capacity=20,
        )
        cls.group_lyon.students.set([cls.student_lyon])

    def set_current(self, university):
        session = self.client.session
        session[SESSION_KEY] = university.pk
        session.save()

    def tenant_request(self, user, session_university=None):
        if session_university is not None:
            self.set_current(session_university)
        request = RequestFactory().get("/")
        request.user = user
        request.session = self.client.session
        return request


class TenantResolutionTests(PortalTestBase):
    def test_active_membership_is_selected(self):
        request = self.tenant_request(self.admin_paris)
        resolve_tenant(request)
        self.assertEqual(request.university, self.paris)
        self.assertEqual(request.membership.university, self.paris)
        self.assertEqual(request.university_role, Role.UNIVERSITY_ADMIN)

    def test_foreign_session_is_ignored(self):
        request = self.tenant_request(self.admin_paris, session_university=self.lyon)
        resolve_tenant(request)
        self.assertEqual(request.university, self.paris)
        self.assertEqual(request.session[SESSION_KEY], self.paris.pk)

    def test_multi_university_professor_switch(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.paris)
        response = self.client.get(reverse("portal:prof_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["profile"].department, "Informatique")

        response = self.client.post(
            reverse("portal:university_switch"), {"university": self.lyon.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[SESSION_KEY], self.lyon.pk)

        response = self.client.get(reverse("portal:prof_profile"))
        self.assertEqual(response.context["profile"].department, "Mathématiques")

    def test_pending_membership_has_no_university(self):
        pending = create_user("pending@example.com", first_name="En", last_name="Attente")
        add_membership(pending, self.paris, Role.STUDENT, is_active=False)

        request = self.tenant_request(pending)
        resolve_tenant(request)
        self.assertIsNone(request.university)
        self.assertIsNone(request.membership)

        self.client.force_login(pending)
        response = self.client.get(reverse("portal:student_profile"))
        self.assertRedirects(response, reverse("portal:university_switch"))
        response = self.client.get(reverse("portal:university_switch"))
        self.assertContains(response, "en attente de validation")

    def test_platform_admin_has_no_university(self):
        request = self.tenant_request(self.platform, session_university=self.lyon)
        resolve_tenant(request)
        self.assertIsNone(request.university)
        self.assertIsNone(request.membership)
        self.assertEqual(request.university_role, Role.PLATFORM_ADMIN)
        self.assertNotIn(SESSION_KEY, request.session)

    def test_platform_admin_without_session_has_no_university(self):
        request = self.tenant_request(self.platform)
        resolve_tenant(request)
        self.assertIsNone(request.university)


class IsolationTests(PortalTestBase):
    def setUp(self):
        self.client.force_login(self.admin_paris)

    def test_lists_are_scoped_to_current_university(self):
        response = self.client.get(reverse("portal:admin_teachers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "prof@example.com")
        self.assertNotContains(response, "prof.lyon@example.com")

        response = self.client.get(reverse("portal:admin_students"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "etudiant.paris@paris.fr")
        self.assertNotContains(response, "etudiant.lyon@lyon.fr")

        response = self.client.get(reverse("portal:admin_classes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "L3 Informatique")
        self.assertNotContains(response, "M1 Mathématiques")

    def test_foreign_objects_return_404(self):
        foreign_urls = (
            reverse("portal:admin_teacher_update", args=[self.prof_lyon_only.pk]),
            reverse("portal:admin_teacher_delete", args=[self.prof_lyon_only.pk]),
            reverse("portal:admin_student_update", args=[self.student_lyon.pk]),
            reverse("portal:admin_class_detail", args=[self.class_lyon.pk]),
            reverse("portal:admin_class_update", args=[self.class_lyon.pk]),
            reverse("portal:admin_class_delete", args=[self.class_lyon.pk]),
            reverse("portal:admin_group_update", args=[self.class_paris.pk, self.group_lyon.pk]),
            reverse("portal:admin_group_delete", args=[self.class_paris.pk, self.group_lyon.pk]),
            reverse("portal:admin_university_update", args=[self.lyon.pk]),
        )
        for url in foreign_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_foreign_invitation_returns_404(self):
        invitation = Invitation.objects.create(
            university=self.lyon, email="autre@example.com", role=Role.PROFESSOR,
        )
        response = self.client.get(reverse("portal:admin_invitation_update", args=[invitation.pk]))
        self.assertEqual(response.status_code, 404)

    def test_foreign_professor_is_refused_in_class_form(self):
        initial = SchoolClass.objects.count()
        response = self.client.post(reverse("portal:admin_class_create"), {
            "name": "Classe invalide",
            "level": "M1",
            "program": "Test",
            "academic_year": "2025-2026",
            "description": "",
            "professors": [self.prof_lyon_only.pk],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SchoolClass.objects.count(), initial)
        self.assertTrue(response.context["form"].errors.get("professors"))

    def test_foreign_student_is_refused_in_group_form(self):
        initial = StudentGroup.objects.filter(school_class=self.class_paris).count()
        response = self.client.post(
            reverse("portal:admin_group_create", args=[self.class_paris.pk]),
            {"name": "Groupe invalide", "capacity": 10, "students": [self.student_lyon.pk]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            StudentGroup.objects.filter(school_class=self.class_paris).count(), initial,
        )

    def test_university_admin_cannot_edit_foreign_university(self):
        response = self.client.post(reverse("portal:admin_university_update", args=[self.lyon.pk]), {
            "code": "HACK", "city": "X", "country": "X", "website": "", "description": "",
        })
        self.assertEqual(response.status_code, 404)
        self.lyon.refresh_from_db()
        self.assertEqual(self.lyon.code, "")


class PermissionTests(PortalTestBase):
    def test_platform_admin_sees_platform_pages(self):
        self.client.force_login(self.platform)
        self.set_current(self.paris)
        self.assertEqual(self.client.get(reverse("portal:admin_universities")).status_code, 200)
        self.assertEqual(self.client.get(reverse("portal:admin_accounts")).status_code, 200)
        self.assertEqual(self.client.get(reverse("portal:admin_platform_settings")).status_code, 200)

    def test_university_admin_cannot_access_platform_pages(self):
        self.client.force_login(self.admin_paris)
        for name in ("portal:admin_universities", "portal:admin_accounts", "portal:admin_platform_settings"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_professor_and_student_cannot_access_admin_pages(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.paris)
        self.assertEqual(self.client.get(reverse("portal:admin_students")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:admin_invitations")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:admin_university")).status_code, 403)

        self.client.force_login(self.student_paris_user)
        self.set_current(self.paris)
        self.assertEqual(self.client.get(reverse("portal:admin_teachers")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:admin_classes")).status_code, 403)

    def test_portal_pages_are_role_specific(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.paris)
        self.assertEqual(self.client.get(reverse("portal:student_profile")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:student_class")).status_code, 403)

        self.client.force_login(self.student_paris_user)
        self.set_current(self.paris)
        self.assertEqual(self.client.get(reverse("portal:prof_profile")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:prof_classes")).status_code, 403)

    def test_university_admin_cannot_invite_another_admin(self):
        self.client.force_login(self.admin_paris)
        response = self.client.post(
            reverse("portal:admin_invitation_create"),
            invitation_payload(role=Role.UNIVERSITY_ADMIN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invitation.objects.exists())
        self.assertTrue(response.context["form"].errors.get("role"))


class CrudTests(PortalTestBase):
    def test_platform_creates_university(self):
        self.client.force_login(self.platform)
        response = self.client.post(reverse("portal:admin_university_create"), {
            "name": "Université Nouvelle",
            "code": "UN",
            "city": "Lille",
            "country": "France",
            "email_domain": "univ-lille.fr",
            "website": "",
            "description": "",
            "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        university = University.objects.get(name="Université Nouvelle")
        self.assertEqual(university.slug, "universite-nouvelle")
        self.assertEqual(university.email_domain, "univ-lille.fr")
        self.assertEqual(response.url, reverse("portal:admin_university_detail", args=[university.pk]))

    def test_create_professor_with_new_account(self):
        self.client.force_login(self.admin_paris)
        response = self.client.post(reverse("portal:admin_teacher_create"), {
            "email": "nouveau.prof@example.com",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "department": "Informatique",
            "speciality": "Calcul",
            "grade": "professeur",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="nouveau.prof@example.com")
        membership = Membership.objects.get(user=user, university=self.paris)
        self.assertEqual(membership.role, Role.PROFESSOR)
        self.assertTrue(membership.is_active)
        self.assertEqual(membership.professor_profile.department, "Informatique")
        self.assertEqual(len(mail.outbox), 1)

    def test_reuse_existing_account_in_second_university(self):
        self.client.force_login(self.admin_lyon)
        initial_users = User.objects.count()
        response = self.client.post(reverse("portal:admin_teacher_create"), {
            "email": self.prof_paris_only_user.email,
            "first_name": "Ada",
            "last_name": "Paris",
            "department": "Réseaux",
            "speciality": "Protocoles",
            "grade": "maitre_assistant",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.count(), initial_users)
        membership = Membership.objects.get(user=self.prof_paris_only_user, university=self.lyon)
        self.assertEqual(membership.role, Role.PROFESSOR)
        self.assertEqual(membership.professor_profile.department, "Réseaux")
        self.prof_paris_only.refresh_from_db()
        self.assertEqual(self.prof_paris_only.department, "Informatique")
        self.assertEqual(len(mail.outbox), 0)

    def test_create_update_and_delete_student(self):
        self.client.force_login(self.admin_paris)
        response = self.client.post(reverse("portal:admin_student_create"), {
            "email": "nouvel.etudiant@paris.fr",
            "first_name": "Nina",
            "last_name": "Test",
            "student_number": "P-999",
            "program": "Informatique",
            "promotion": "2027",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="nouvel.etudiant@paris.fr")
        profile = StudentProfile.objects.get(membership__user=user, university=self.paris)
        self.assertEqual(profile.student_number, "P-999")
        self.assertEqual(profile.promotion, "2027")

        response = self.client.post(reverse("portal:admin_student_update", args=[profile.pk]), {
            "student_number": "P-999",
            "program": "Génie logiciel",
            "promotion": "2027",
            "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.program, "Génie logiciel")
        self.assertTrue(profile.membership.is_active)

        response = self.client.post(reverse("portal:admin_student_delete", args=[profile.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Membership.objects.filter(user=user, university=self.paris).exists())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_create_class_group_then_delete(self):
        self.client.force_login(self.admin_paris)
        response = self.client.post(reverse("portal:admin_class_create"), {
            "name": "M1 Test",
            "level": "Master 1",
            "program": "Génie logiciel",
            "academic_year": "2025-2026",
            "description": "",
            "professors": [self.prof_paris.pk],
        })
        self.assertEqual(response.status_code, 302)
        school_class = SchoolClass.objects.get(university=self.paris, name="M1 Test")
        self.assertEqual(response.url, reverse("portal:admin_class_detail", args=[school_class.pk]))
        self.assertIn(self.prof_paris, school_class.professors.all())

        response = self.client.post(
            reverse("portal:admin_group_create", args=[school_class.pk]),
            {"name": "Groupe test", "capacity": 2, "students": [self.student_paris.pk]},
        )
        self.assertEqual(response.status_code, 302)
        group = StudentGroup.objects.get(school_class=school_class, name="Groupe test")
        self.assertEqual(group.university, self.paris)
        self.assertIn(self.student_paris, group.students.all())

        response = self.client.post(
            reverse("portal:admin_group_delete", args=[school_class.pk, group.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(StudentGroup.objects.filter(pk=group.pk).exists())

        response = self.client.post(reverse("portal:admin_class_delete", args=[school_class.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SchoolClass.objects.filter(pk=school_class.pk).exists())

    def test_removing_professor_keeps_account_and_other_membership(self):
        self.client.force_login(self.admin_paris)
        response = self.client.post(reverse("portal:admin_teacher_delete", args=[self.prof_paris.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Membership.objects.filter(user=self.prof_user, university=self.paris).exists())
        self.assertTrue(Membership.objects.filter(user=self.prof_user, university=self.lyon).exists())
        self.assertTrue(User.objects.filter(pk=self.prof_user.pk).exists())

    def test_platform_deletes_university(self):
        self.client.force_login(self.platform)
        self.set_current(self.paris)
        response = self.client.post(reverse("portal:admin_university_delete", args=[self.lyon.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(University.objects.filter(pk=self.lyon.pk).exists())


class SignUpTests(PortalTestBase):
    def signup(self, **overrides):
        data = {
            "full_name": "Nouvelle Étudiante",
            "email": "nouvelle@paris.fr",
            "password1": "MotDePasse123!",
            "password2": "MotDePasse123!",
            "role": "etudiant",
            "university": self.paris.pk,
        }
        data.update(overrides)
        return self.client.post(reverse("accounts:signup"), data)

    def test_official_domain_is_auto_validated(self):
        response = self.signup()
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="nouvelle@paris.fr")
        membership = Membership.objects.get(user=user, university=self.paris)
        self.assertEqual(membership.role, Role.STUDENT)
        self.assertTrue(membership.is_active)
        self.assertTrue(StudentProfile.objects.filter(membership=membership).exists())

    def test_other_domain_is_pending(self):
        response = self.signup(email="nouvelle@gmail.com")
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="nouvelle@gmail.com")
        membership = Membership.objects.get(user=user, university=self.paris)
        self.assertFalse(membership.is_active)
        self.assertTrue(StudentProfile.objects.filter(membership=membership).exists())

    def test_professor_registration_is_always_pending(self):
        response = self.signup(
            full_name="Nouveau Professeur",
            email="professeur@paris.fr",
            role="prof",
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="professeur@paris.fr")
        membership = Membership.objects.get(user=user, university=self.paris)
        self.assertEqual(membership.role, Role.PROFESSOR)
        self.assertFalse(membership.is_active)

    def test_platform_admin_role_cannot_be_self_assigned(self):
        response = self.signup(role=Role.UNIVERSITY_ADMIN, email="pirate@paris.fr")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="pirate@paris.fr").exists())
        self.assertTrue(response.context["form"].errors.get("role"))

    def test_university_admin_approves_and_rejects_registrations(self):
        approved_user = create_user("a.valider@example.com")
        approved = add_membership(approved_user, self.paris, Role.STUDENT, is_active=False)
        rejected_user = create_user("a.refuser@example.com")
        rejected = add_membership(rejected_user, self.paris, Role.STUDENT, is_active=False)

        self.client.force_login(self.admin_paris)
        response = self.client.post(
            reverse("portal:admin_membership_decide", args=[approved.pk]),
            {"decision": "approve"},
        )
        self.assertEqual(response.status_code, 302)
        approved.refresh_from_db()
        self.assertTrue(approved.is_active)
        self.assertTrue(StudentProfile.objects.filter(membership=approved).exists())

        response = self.client.post(
            reverse("portal:admin_membership_decide", args=[rejected.pk]),
            {"decision": "reject"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Membership.objects.filter(pk=rejected.pk).exists())

    def test_admin_cannot_decide_a_foreign_registration(self):
        user = create_user("pending.lyon@example.com")
        membership = add_membership(user, self.lyon, Role.STUDENT, is_active=False)
        self.client.force_login(self.admin_paris)
        response = self.client.post(
            reverse("portal:admin_membership_decide", args=[membership.pk]),
            {"decision": "approve"},
        )
        self.assertEqual(response.status_code, 404)
        membership.refresh_from_db()
        self.assertFalse(membership.is_active)


class InvitationTests(PortalTestBase):
    def test_admin_creates_invitation_with_email(self):
        self.client.force_login(self.admin_paris)
        response = self.client.post(
            reverse("portal:admin_invitation_create"),
            invitation_payload(role=Role.PROFESSOR, email="future.prof@example.com"),
        )
        self.assertEqual(response.status_code, 302)
        invitation = Invitation.objects.get(email="future.prof@example.com")
        self.assertEqual(invitation.university, self.paris)
        self.assertEqual(invitation.invited_by, self.admin_paris)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(invitation.token), mail.outbox[0].body)

    def test_platform_admin_can_invite_university_admin(self):
        self.client.force_login(self.platform)
        response = self.client.post(
            reverse("portal:admin_university_invite_admin", args=[self.paris.pk]),
            {"email": "future.admin@example.com"},
        )
        self.assertRedirects(
            response, reverse("portal:admin_university_detail", args=[self.paris.pk]),
        )
        self.assertTrue(Invitation.objects.filter(
            university=self.paris, email="future.admin@example.com", role=Role.UNIVERSITY_ADMIN,
        ).exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_accept_with_new_account(self):
        invitation = Invitation.objects.create(
            university=self.paris, email="nouvelle.recrue@example.com", role=Role.PROFESSOR,
        )
        url = reverse("accounts:invitation_accept", args=[invitation.token])
        response = self.client.get(url)
        self.assertEqual(response.context["state"], "signup")

        response = self.client.post(url, {
            "first_name": "Nouvelle",
            "last_name": "Recrue",
            "new_password1": "MotDePasse123!",
            "new_password2": "MotDePasse123!",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="nouvelle.recrue@example.com")
        membership = Membership.objects.get(user=user, university=self.paris)
        self.assertEqual(membership.role, Role.PROFESSOR)
        self.assertTrue(membership.is_active)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.STATUS_ACCEPTED)
        self.assertEqual(self.client.session[SESSION_KEY], self.paris.pk)

    def test_existing_account_is_asked_to_login_first(self):
        existing = create_user("deja.la@example.com")
        invitation = Invitation.objects.create(
            university=self.paris, email=existing.email, role=Role.STUDENT,
        )
        url = reverse("accounts:invitation_accept", args=[invitation.token])
        response = self.client.get(url)
        self.assertEqual(response.context["state"], "login")
        self.assertIn(reverse("accounts:login"), response.context["login_url"])
        self.assertIn(url, response.context["login_url"])

        self.client.force_login(existing)
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Membership.objects.filter(user=existing, university=self.paris).exists())
        self.assertTrue(StudentProfile.objects.filter(membership__user=existing).exists())

    def test_wrong_account_cannot_accept(self):
        other = create_user("autre@example.com")
        invitation = Invitation.objects.create(
            university=self.paris, email="destinataire@example.com", role=Role.STUDENT,
        )
        self.client.force_login(other)
        url = reverse("accounts:invitation_accept", args=[invitation.token])
        response = self.client.get(url)
        self.assertEqual(response.context["state"], "wrong_account")
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.STATUS_PENDING)
        self.assertFalse(Membership.objects.filter(user=other, university=self.paris).exists())

    def test_revoked_and_expired_invitations_are_invalid(self):
        revoked = Invitation.objects.create(
            university=self.paris, email="revoquee@example.com", role=Role.STUDENT,
            status=Invitation.STATUS_REVOKED,
        )
        expired = Invitation.objects.create(
            university=self.paris, email="expiree@example.com", role=Role.STUDENT,
            expires_at=timezone.now() - timedelta(days=1),
        )
        for invitation in (revoked, expired):
            with self.subTest(pk=invitation.pk):
                response = self.client.get(
                    reverse("accounts:invitation_accept", args=[invitation.token]),
                )
                self.assertEqual(response.context["state"], "invalid")

    def test_resend_and_revoke(self):
        invitation = Invitation.objects.create(
            university=self.paris, email="relance@example.com", role=Role.STUDENT,
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.client.force_login(self.admin_paris)
        response = self.client.post(
            reverse("portal:admin_invitation_action", args=[invitation.pk, "renvoyer"]),
        )
        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertGreater(invitation.expires_at, timezone.now() + timedelta(days=6))
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.post(
            reverse("portal:admin_invitation_action", args=[invitation.pk, "revoquer"]),
        )
        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.STATUS_REVOKED)


class ProfileAndAuthTests(PortalTestBase):
    def test_professor_edits_only_current_university_profile(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.paris)
        response = self.client.post(reverse("portal:prof_profile"), {
            "first_name": "Hélène",
            "last_name": "Vasseur",
            "email": self.prof_user.email,
            "department": "Réseaux",
            "speciality": "Systèmes distribués",
            "grade": "professeur",
        })
        self.assertEqual(response.status_code, 302)
        self.prof_paris.refresh_from_db()
        self.prof_lyon.refresh_from_db()
        self.assertEqual(self.prof_paris.department, "Réseaux")
        self.assertEqual(self.prof_paris.grade, "professeur")
        self.assertEqual(self.prof_lyon.department, "Mathématiques")
        self.assertEqual(self.prof_lyon.grade, "professeur")

    def test_student_edits_profile(self):
        self.client.force_login(self.student_paris_user)
        self.set_current(self.paris)
        response = self.client.post(reverse("portal:student_profile"), {
            "first_name": "Camille",
            "last_name": "Martine",
            "email": self.student_paris_user.email,
            "student_number": "P-001",
            "program": "Génie logiciel",
            "promotion": "2027",
        })
        self.assertEqual(response.status_code, 302)
        self.student_paris.refresh_from_db()
        self.assertEqual(self.student_paris.program, "Génie logiciel")
        self.assertEqual(self.student_paris.promotion, "2027")
        self.student_paris_user.refresh_from_db()
        self.assertEqual(self.student_paris_user.last_name, "Martine")

    def test_student_sees_classes_and_classmates(self):
        self.client.force_login(self.student_paris_user)
        self.set_current(self.paris)
        response = self.client.get(reverse("portal:student_class"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "L3 Informatique")
        self.assertContains(response, "TD A")

    def test_professor_lists_universities_and_classes(self):
        self.client.force_login(self.prof_user)
        response = self.client.get(reverse("portal:prof_universities"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.paris.name)
        self.assertContains(response, self.lyon.name)

        self.set_current(self.paris)
        response = self.client.get(reverse("portal:prof_classes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "L3 Informatique")
        self.assertNotContains(response, "M1 Mathématiques")

    def test_professor_changes_password(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.paris)
        response = self.client.post(reverse("portal:prof_settings"), {
            "old_password": PASSWORD,
            "new_password1": "NouveauMotDePasse123!",
            "new_password2": "NouveauMotDePasse123!",
        })
        self.assertEqual(response.status_code, 302)
        self.prof_user.refresh_from_db()
        self.assertTrue(self.prof_user.check_password("NouveauMotDePasse123!"))

    def test_login_accepts_local_next(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": self.admin_paris.email,
            "password": PASSWORD,
            "next": "/accounts/connexion/",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/accounts/connexion/")

    def test_login_refuses_external_next(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": self.student_paris_user.email,
            "password": PASSWORD,
            "next": "https://evil.example.com/phishing",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("coaching:student_dashboard"))

    def test_jwt_me_is_unchanged(self):
        access = RefreshToken.for_user(self.prof_user).access_token
        response = self.client.get(
            reverse("accounts:me"), HTTP_AUTHORIZATION="Bearer %s" % access,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["email"], self.prof_user.email)
        self.assertEqual(payload["role"], "prof")


class PageRenderTests(PortalTestBase):
    """Chaque écran doit se rendre sans erreur pour le rôle attendu."""

    def assert_pages(self, names, args_by_name=None):
        args_by_name = args_by_name or {}
        for name in names:
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=args_by_name.get(name)))
                self.assertEqual(response.status_code, 200)

    def test_platform_pages_render(self):
        self.client.force_login(self.platform)
        self.assert_pages(
            (
                "portal:admin_universities",
                "portal:admin_university_create",
                "portal:admin_university_detail",
                "portal:admin_university_update",
                "portal:admin_university_delete",
                "portal:admin_accounts",
                "portal:admin_account_update",
                "portal:admin_account_delete",
                "portal:admin_platform_settings",
                "portal:admin_profile",
            ),
            {
                "portal:admin_university_detail": [self.paris.pk],
                "portal:admin_university_update": [self.paris.pk],
                "portal:admin_university_delete": [self.paris.pk],
                "portal:admin_account_update": [self.admin_paris.pk],
                "portal:admin_account_delete": [self.admin_paris.pk],
            },
        )

    def test_platform_admin_has_no_tenant_pages(self):
        self.client.force_login(self.platform)
        for name in (
            "portal:admin_university",
            "portal:admin_invitations",
            "portal:admin_invitation_create",
            "portal:admin_teachers",
            "portal:admin_students",
            "portal:admin_classes",
        ):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertRedirects(response, reverse("portal:admin_universities"))

    def test_university_admin_pages_render(self):
        self.client.force_login(self.admin_paris)
        invitation = Invitation.objects.create(
            university=self.paris, email="rendu.admin@example.com", role=Role.STUDENT,
        )
        self.assert_pages(
            (
                "portal:admin_university",
                "portal:admin_university_update",
                "portal:admin_teachers",
                "portal:admin_teacher_create",
                "portal:admin_teacher_update",
                "portal:admin_teacher_delete",
                "portal:admin_students",
                "portal:admin_student_create",
                "portal:admin_student_update",
                "portal:admin_student_delete",
                "portal:admin_classes",
                "portal:admin_class_create",
                "portal:admin_class_detail",
                "portal:admin_class_update",
                "portal:admin_class_delete",
                "portal:admin_group_create",
                "portal:admin_group_update",
                "portal:admin_group_delete",
                "portal:admin_invitations",
                "portal:admin_invitation_create",
                "portal:admin_invitation_update",
                "portal:admin_invitation_delete",
            ),
            {
                "portal:admin_university_update": [self.paris.pk],
                "portal:admin_teacher_update": [self.prof_paris.pk],
                "portal:admin_teacher_delete": [self.prof_paris.pk],
                "portal:admin_student_update": [self.student_paris.pk],
                "portal:admin_student_delete": [self.student_paris.pk],
                "portal:admin_class_detail": [self.class_paris.pk],
                "portal:admin_class_update": [self.class_paris.pk],
                "portal:admin_class_delete": [self.class_paris.pk],
                "portal:admin_group_create": [self.class_paris.pk],
                "portal:admin_group_update": [self.class_paris.pk, self.group_paris.pk],
                "portal:admin_group_delete": [self.class_paris.pk, self.group_paris.pk],
                "portal:admin_invitation_update": [invitation.pk],
                "portal:admin_invitation_delete": [invitation.pk],
            },
        )

    def test_professor_pages_render(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.paris)
        self.assert_pages((
            "portal:prof_profile",
            "portal:prof_universities",
            "portal:prof_classes",
            "portal:prof_settings",
        ))

    def test_student_pages_render(self):
        self.client.force_login(self.student_paris_user)
        self.set_current(self.paris)
        self.assert_pages(("portal:student_profile", "portal:student_class"))

    def test_auth_pages_render_with_next_and_universities(self):
        response = self.client.get(reverse("accounts:login") + "?next=/mes-cours/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="next"')
        self.assertContains(response, 'value="/mes-cours/"')

        response = self.client.get(reverse("accounts:signup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="university"')
        self.assertContains(response, self.paris.name)
        self.assertContains(response, self.lyon.name)

        response = self.client.get(
            reverse("accounts:signup") + "?university=" + self.paris.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, '<option value="%s" selected>' % self.paris.pk, html=False,
        )


class RoleScopedPortalTests(PortalTestBase):
    """La navigation et les pages suivent le rôle exercé dans l'université courante."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.multi_user = create_user("multi@example.com", first_name="Maya", last_name="Pont")
        add_membership(cls.multi_user, cls.lyon, Role.UNIVERSITY_ADMIN)
        cls.multi_prof = add_membership(
            cls.multi_user, cls.paris, Role.PROFESSOR,
            department="Informatique", speciality="Réseaux", grade="maitre_assistant",
        ).professor_profile

    def nav_labels(self, response):
        return {
            item["label"]
            for section in response.context["portal_nav_sections"]
            for item in section["items"]
        }

    def test_sidebar_follows_current_university_role(self):
        self.client.force_login(self.multi_user)
        self.set_current(self.lyon)
        response = self.client.get(reverse("portal:admin_students"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["portal_scope_label"], "Admin université")
        labels = self.nav_labels(response)
        self.assertIn("Enseignants & Chercheurs", labels)
        self.assertIn("Invitations & Rôles", labels)
        self.assertNotIn("Mes Cours", labels)
        self.assertNotIn("Catalogue des cours", labels)
        self.assertNotIn("Universités", labels)

        self.set_current(self.paris)
        response = self.client.get(reverse("coaching:prof_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["portal_scope_label"], "Professeur")
        labels = self.nav_labels(response)
        self.assertIn("Mes Cours", labels)
        self.assertNotIn("Enseignants & Chercheurs", labels)
        self.assertNotIn("Invitations & Rôles", labels)
        self.assertNotIn("Comptes & Accès", labels)

    def test_sidebar_has_no_account_section(self):
        pages = (
            (self.admin_paris, "coaching:admin_dashboard"),
            (self.prof_user, "coaching:prof_dashboard"),
            (self.student_paris_user, "coaching:student_dashboard"),
        )
        for user, page in pages:
            with self.subTest(page=page):
                self.client.force_login(user)
                response = self.client.get(reverse(page))
                self.assertEqual(response.status_code, 200)
                sections = [
                    section["label"] for section in response.context["portal_nav_sections"]
                ]
                self.assertNotIn("Compte", sections)
                labels = self.nav_labels(response)
                for label in (
                    "Mon Profil", "Mon Profil & Paramètres", "Mon Profil & Grades",
                    "Mes Universités", "Ma Classe & Groupes", "Paramètres du compte",
                ):
                    self.assertNotIn(label, labels)

    def test_content_pages_use_membership_role(self):
        self.client.force_login(self.multi_user)
        self.set_current(self.lyon)
        self.assertEqual(self.client.get(reverse("coaching:admin_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("courses:admin_courses")).status_code, 200)
        self.assertEqual(self.client.get(reverse("portal:admin_students")).status_code, 200)
        self.assertEqual(self.client.get(reverse("coaching:prof_dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("courses:prof_course")).status_code, 403)
        self.assertEqual(self.client.get(reverse("courses:student_catalogue")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:prof_profile")).status_code, 403)

        self.set_current(self.paris)
        self.assertEqual(self.client.get(reverse("coaching:prof_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("courses:prof_course")).status_code, 200)
        self.assertEqual(self.client.get(reverse("portal:prof_profile")).status_code, 200)
        self.assertEqual(self.client.get(reverse("coaching:admin_dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("courses:admin_courses")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:admin_students")).status_code, 403)

    def test_switch_redirects_to_new_role_home(self):
        self.client.force_login(self.multi_user)
        self.set_current(self.paris)
        response = self.client.post(
            reverse("portal:university_switch"), {"university": self.lyon.pk},
        )
        self.assertRedirects(response, reverse("coaching:admin_dashboard"))

    def test_university_admin_cannot_switch(self):
        self.client.force_login(self.multi_user)
        self.set_current(self.lyon)
        response = self.client.get(reverse("portal:admin_students"))
        self.assertNotIn("Changer d'université", self.nav_labels(response))
        self.assertNotContains(response, reverse("portal:university_switch"))

        response = self.client.get(reverse("portal:university_switch"))
        self.assertRedirects(response, reverse("coaching:admin_dashboard"))

        response = self.client.post(
            reverse("portal:university_switch"), {"university": self.paris.pk},
        )
        self.assertRedirects(response, reverse("coaching:admin_dashboard"))
        self.assertEqual(self.client.session[SESSION_KEY], self.lyon.pk)

    def test_login_redirects_using_selected_university_role(self):
        session = self.client.session
        session[SESSION_KEY] = self.paris.pk
        session.save()
        response = self.client.post(reverse("accounts:login"), {
            "username": self.multi_user.email,
            "password": PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("coaching:prof_dashboard"))
        self.assertEqual(self.client.session[SESSION_KEY], self.paris.pk)

    def test_pending_user_gets_minimal_navigation(self):
        pending = create_user("pending.role@example.com")
        add_membership(pending, self.paris, Role.STUDENT, is_active=False)
        self.client.force_login(pending)

        response = self.client.get(reverse("portal:university_switch"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["portal_scope_label"], "En attente")
        self.assertEqual(response.context["portal_home_url_name"], "portal:university_switch")
        self.assertEqual(self.nav_labels(response), set())
        self.assertContains(response, "Choisir une université")
        self.assertNotContains(response, "Catalogue des cours")

        for name in ("courses:student_catalogue", "coaching:student_dashboard", "portal:student_profile"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertRedirects(response, reverse("portal:university_switch"))

    def test_platform_admin_nav_and_tenant_free_access(self):
        self.client.force_login(self.platform)
        response = self.client.get(reverse("portal:admin_universities"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["portal_scope_label"], "Admin plateforme")
        self.assertEqual(response.context["portal_home_url_name"], "portal:admin_universities")
        self.assertFalse(response.context["portal_has_university"])
        labels = self.nav_labels(response)
        self.assertIn("Universités", labels)
        self.assertIn("Comptes & Accès", labels)
        self.assertNotIn("Changer d'université", labels)
        self.assertNotIn("Tableau de bord Admin", labels)
        self.assertContains(response, "Toutes les universités")
        self.assertNotContains(response, "Changer d'université")
        self.assertEqual(self.client.get(reverse("portal:admin_platform_settings")).status_code, 200)
        self.assertEqual(self.client.get(reverse("portal:admin_profile")).status_code, 200)

        response = self.client.get(reverse("portal:university_switch"))
        self.assertRedirects(response, reverse("portal:admin_universities"))

        for name in ("coaching:student_dashboard", "portal:admin_students"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertRedirects(response, reverse("portal:admin_universities"))

        # Une session héritée ne rattache pas l'admin plateforme à l'université.
        self.set_current(self.paris)
        response = self.client.get(reverse("portal:admin_university_detail", args=[self.paris.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(
            self.client.get(reverse("coaching:student_dashboard")).status_code, 302,
        )

    def test_university_admin_nav_hides_platform_sections(self):
        self.client.force_login(self.admin_paris)
        response = self.client.get(reverse("portal:admin_students"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["portal_scope_label"], "Admin université")
        labels = self.nav_labels(response)
        self.assertIn("Étudiants & Inscriptions", labels)
        self.assertNotIn("Universités", labels)
        self.assertNotIn("Comptes & Accès", labels)
        self.assertNotIn("Changer d'université", labels)
        self.assertNotContains(response, reverse("portal:university_switch"))
        self.assertEqual(self.client.get(reverse("portal:admin_universities")).status_code, 403)

        response = self.client.get(reverse("portal:admin_profile"))
        self.assertNotContains(response, "Changer d'université")
        self.assertContains(response, "Rattachement unique")

    def test_switch_page_uses_role_theme(self):
        expected = (
            (self.prof_user, "prof", "portal/base_prof.html"),
            (self.student_paris_user, "etudiant", "portal/base_student.html"),
        )
        for user, role, base_template in expected:
            with self.subTest(role=role):
                self.client.force_login(user)
                response = self.client.get(reverse("portal:university_switch"))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["portal_role"], role)
                self.assertEqual(response.context["portal_base_template"], base_template)
                self.assertContains(response, 'data-portal-role="%s"' % role)

        self.client.force_login(self.admin_paris)
        response = self.client.get(reverse("portal:university_switch"))
        self.assertRedirects(response, reverse("coaching:admin_dashboard"))

        self.client.force_login(self.platform)
        response = self.client.get(reverse("portal:university_switch"))
        self.assertRedirects(response, reverse("portal:admin_universities"))

    def test_notifications_follow_visible_navigation(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.paris)
        response = self.client.get(reverse("coaching:prof_dashboard"))
        self.assertEqual(len(response.context["portal_notifications"]), 3)

        pending = create_user("pending.notif@example.com")
        add_membership(pending, self.paris, Role.STUDENT, is_active=False)
        self.client.force_login(pending)
        response = self.client.get(reverse("portal:university_switch"))
        self.assertEqual(response.context["portal_role"], "etudiant")
        self.assertEqual(response.context["portal_notifications"], ())

        self.client.force_login(self.platform)
        response = self.client.get(reverse("portal:admin_universities"))
        self.assertEqual(response.context["portal_notifications"], ())
