"""Tests du flux manuel de relance et de signalement référent scolarité."""

from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SchoolClass
from accounts.tests import PortalTestBase, add_membership, create_user
from accounts.tenancy import Role

from coaching.models import (
    PerseveranceAlert,
    TutorAssignment,
    TutorNotification,
)

ACADEMIC_YEAR = "2025-2026"

TYPE = PerseveranceAlert.TYPE_ENGAGEMENT
OPEN = PerseveranceAlert.STATUS_OPEN
TAKEN = PerseveranceAlert.STATUS_TAKEN
CLOSED = PerseveranceAlert.STATUS_CLOSED
HIGH = PerseveranceAlert.PRIORITY_HIGH
NORMAL = PerseveranceAlert.PRIORITY_NORMAL


class RelanceFlowBase(PortalTestBase):
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
        cls.notification_paris = TutorNotification.objects.create(
            university=cls.paris, student=cls.student_paris, professor=cls.prof_paris,
            kind=TutorNotification.KIND_RELANCE,
            title="Faire le point", message="Bonjour Camille, faisons le point sur ta progression.",
        )
        cls.notification_lyon = TutorNotification.objects.create(
            university=cls.lyon, student=cls.student_lyon, professor=cls.prof_lyon,
            kind=TutorNotification.KIND_RELANCE,
            title="Relance Lyon", message="Bonjour Lucas, faisons le point ensemble.",
        )
        cls.outsider_user = create_user("outsider.paris@example.com", first_name="Zoé", last_name="Hors")
        cls.outsider_membership = add_membership(
            cls.outsider_user, cls.paris, Role.STUDENT,
            student_number="P-099", program="Informatique",
        )
        cls.outsider = cls.outsider_membership.student_profile
        cls.notification_outsider = TutorNotification.objects.create(
            university=cls.paris, student=cls.outsider, professor=cls.prof_paris,
            kind=TutorNotification.KIND_RELANCE,
            title="Relance Zoé", message="Message destiné à Zoé uniquement.",
        )

    def login_student(self, university=None):
        self.client.force_login(self.student_paris_user)
        self.set_current(university or self.paris)

    def login_prof(self, university=None):
        self.client.force_login(self.prof_user)
        self.set_current(university or self.paris)

    def login_admin(self, university=None):
        self.client.force_login(self.admin_paris)
        self.set_current(university or self.paris)

    def relance_payload(self, **overrides):
        data = {
            "subject": "Faire le point sur ta progression",
            "message": (
                "Bonjour Camille, je souhaite que l'on fasse le point sur ta "
                "progression cette semaine. Peux-tu me répondre ici ?"
            ),
        }
        data.update(overrides)
        return data

    def alert_payload(self, **overrides):
        data = {
            "detail": "Participation en nette baisse depuis deux semaines, je souhaite un accompagnement.",
            "priority": HIGH,
        }
        data.update(overrides)
        return data


class RelancePermissionTests(RelanceFlowBase):
    def test_anonymous_redirected_to_login(self):
        url = reverse("coaching:prof_student_relance", args=[self.student_paris.pk])
        response = self.client.post(url, self.relance_payload())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/connexion/", response.url)

    def test_student_cannot_relance(self):
        self.login_student()
        url = reverse("coaching:prof_student_relance", args=[self.student_paris.pk])
        self.assertEqual(self.client.post(url, self.relance_payload()).status_code, 403)

    def test_professor_cannot_open_student_notifications(self):
        self.login_prof()
        response = self.client.get(reverse("coaching:student_notifications"))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_read_another_student_notification(self):
        self.login_student()
        url = reverse("coaching:student_notification_read", args=[self.notification_outsider.pk])
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_student_cannot_read_other_tenant_notification(self):
        self.login_student()
        url = reverse("coaching:student_notification_read", args=[self.notification_lyon.pk])
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_student_cannot_reply_to_foreign_notification(self):
        self.login_student()
        url = reverse("coaching:student_notification_reply", args=[self.notification_lyon.pk])
        response = self.client.post(url, {"reply": "Bonjour merci beaucoup"})
        self.assertEqual(response.status_code, 404)


class RelanceTests(RelanceFlowBase):
    def setUp(self):
        super().setUp()
        self.assignment_paris.last_contact_at = None
        self.assignment_paris.save(update_fields=["last_contact_at"])

    def test_valid_relance_creates_notification_and_updates_contact(self):
        self.login_prof()
        url = reverse("coaching:prof_student_relance", args=[self.student_paris.pk])
        response = self.client.post(url, self.relance_payload())
        self.assertRedirects(response, reverse("coaching:prof_followup"))
        notification = TutorNotification.objects.filter(
            student=self.student_paris, kind=TutorNotification.KIND_RELANCE,
        ).latest("created_at")
        self.assertEqual(notification.title, "Faire le point sur ta progression")
        self.assertEqual(notification.professor, self.prof_paris)
        self.assertIsNone(notification.read_at)
        self.assignment_paris.refresh_from_db()
        self.assertIsNotNone(self.assignment_paris.last_contact_at)

    def test_anti_spam_blocks_second_relance(self):
        self.login_prof()
        url = reverse("coaching:prof_student_relance", args=[self.student_paris.pk])
        self.client.post(url, self.relance_payload())
        count = TutorNotification.objects.filter(student=self.student_paris).count()
        self.client.post(url, self.relance_payload())
        self.assertEqual(
            TutorNotification.objects.filter(student=self.student_paris).count(), count,
        )

    def test_invalid_relance_does_not_create(self):
        self.login_prof()
        url = reverse("coaching:prof_student_relance", args=[self.student_paris.pk])
        before = TutorNotification.objects.filter(student=self.student_paris).count()
        response = self.client.post(url, self.relance_payload(subject="abc", message="court"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            TutorNotification.objects.filter(student=self.student_paris).count(), before,
        )

    def test_followup_renders_relance_prefill(self):
        self.login_prof()
        response = self.client.get(reverse("coaching:prof_followup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-prefill-subject")
        self.assertContains(response, "data-prefill-message")


class StudentNotificationTests(RelanceFlowBase):
    def setUp(self):
        super().setUp()
        self.notification_paris.read_at = None
        self.notification_paris.reply = None
        self.notification_paris.replied_at = None
        self.notification_paris.save(update_fields=["read_at", "reply", "replied_at"])

    def test_page_lists_notifications_and_kpis(self):
        self.login_student()
        response = self.client.get(reverse("coaching:student_notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Faire le point")
        self.assertContains(response, "Non lue")
        self.assertEqual(response.context["total_count"], 1)
        self.assertEqual(response.context["unread_count"], 1)
        self.assertEqual(response.context["replied_count"], 0)

    def test_mark_read_sets_read_at(self):
        self.login_student()
        url = reverse("coaching:student_notification_read", args=[self.notification_paris.pk])
        response = self.client.post(url)
        self.assertRedirects(response, reverse("coaching:student_notifications"))
        self.notification_paris.refresh_from_db()
        self.assertIsNotNone(self.notification_paris.read_at)

    def test_reply_persists_and_marks_read(self):
        self.login_student()
        url = reverse("coaching:student_notification_reply", args=[self.notification_paris.pk])
        response = self.client.post(url, {"reply": "Merci pour votre message, je réserve un créneau."})
        self.assertRedirects(response, reverse("coaching:student_notifications"))
        self.notification_paris.refresh_from_db()
        self.assertEqual(self.notification_paris.reply, "Merci pour votre message, je réserve un créneau.")
        self.assertIsNotNone(self.notification_paris.replied_at)
        self.assertIsNotNone(self.notification_paris.read_at)

    def test_reply_is_updatable(self):
        self.login_student()
        url = reverse("coaching:student_notification_reply", args=[self.notification_paris.pk])
        self.client.post(url, {"reply": "Première réponse courte."})
        self.client.post(url, {"reply": "Deuxième réponse plus complète."})
        self.notification_paris.refresh_from_db()
        self.assertEqual(self.notification_paris.reply, "Deuxième réponse plus complète.")

    def test_invalid_reply_rejected(self):
        self.login_student()
        url = reverse("coaching:student_notification_reply", args=[self.notification_paris.pk])
        response = self.client.post(url, {"reply": "a"})
        self.assertEqual(response.status_code, 302)
        self.notification_paris.refresh_from_db()
        self.assertIsNone(self.notification_paris.reply)

    def test_professor_sees_reply_on_followup(self):
        self.notification_paris.reply = "Merci, je réserve le créneau de jeudi."
        self.notification_paris.replied_at = timezone.now()
        self.notification_paris.save(update_fields=["reply", "replied_at"])
        self.login_prof()
        response = self.client.get(reverse("coaching:prof_followup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Merci, je réserve le créneau de jeudi.")


class AlertFlowTests(RelanceFlowBase):
    def setUp(self):
        super().setUp()
        PerseveranceAlert.objects.filter(
            student=self.student_paris, alert_type=TYPE,
        ).delete()

    def test_alert_creates_with_reported_by_and_priority(self):
        self.login_prof()
        url = reverse("coaching:prof_student_alert", args=[self.student_paris.pk])
        response = self.client.post(url, self.alert_payload())
        self.assertRedirects(response, reverse("coaching:prof_followup"))
        alert = PerseveranceAlert.objects.get(student=self.student_paris, alert_type=TYPE)
        self.assertEqual(alert.status, OPEN)
        self.assertEqual(alert.priority, HIGH)
        self.assertEqual(alert.reported_by, self.prof_paris)
        self.assertIn("Camille", alert.title)

    def test_alert_strengthens_open_alert(self):
        self.login_prof()
        url = reverse("coaching:prof_student_alert", args=[self.student_paris.pk])
        self.client.post(url, self.alert_payload(priority=NORMAL))
        self.client.post(url, self.alert_payload(
            priority=HIGH,
            detail="Nouveau signalement plus grave avec des précisions supplémentaires.",
        ))
        alerts = PerseveranceAlert.objects.filter(student=self.student_paris, alert_type=TYPE)
        self.assertEqual(alerts.count(), 1)
        alert = alerts.get()
        self.assertEqual(alert.priority, HIGH)
        self.assertEqual(alert.detail, "Nouveau signalement plus grave avec des précisions supplémentaires.")

    def test_invalid_alert_does_not_create(self):
        self.login_prof()
        url = reverse("coaching:prof_student_alert", args=[self.student_paris.pk])
        response = self.client.post(url, {"detail": "court", "priority": HIGH})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PerseveranceAlert.objects.filter(student=self.student_paris, alert_type=TYPE).exists())

    def test_admin_take_then_close_full_lifecycle(self):
        alert = PerseveranceAlert.objects.create(
            university=self.paris, student=self.student_paris, school_class=self.class_paris,
            alert_type=TYPE, title="Signalement pédagogique · Camille Martin",
            detail="Baisse de participation depuis deux semaines.",
            priority=HIGH, reported_by=self.prof_paris, detected_at=timezone.now(),
        )
        self.login_admin()
        take_url = reverse("coaching:admin_alert_take", args=[alert.pk])
        close_url = reverse("coaching:admin_alert_close", args=[alert.pk])

        response = self.client.post(close_url, {"resolution_note": "Entretien réalisé avec le référent."})
        alert.refresh_from_db()
        self.assertEqual(alert.status, OPEN)

        response = self.client.post(take_url, {"handling_note": "Rendez-vous planifié avec le référent."})
        self.assertRedirects(response, reverse("coaching:admin_monitoring"))
        alert.refresh_from_db()
        self.assertEqual(alert.status, TAKEN)
        self.assertEqual(alert.taken_by, self.admin_paris)
        self.assertEqual(alert.handling_note, "Rendez-vous planifié avec le référent.")

        response = self.client.post(close_url, {"resolution_note": "a"})
        alert.refresh_from_db()
        self.assertEqual(alert.status, TAKEN)

        response = self.client.post(close_url, {"resolution_note": "Entretien réalisé, l'étudiante est rassurée."})
        alert.refresh_from_db()
        self.assertEqual(alert.status, CLOSED)
        self.assertIsNotNone(alert.closed_at)
        self.assertEqual(alert.resolution_note, "Entretien réalisé, l'étudiante est rassurée.")

    def test_admin_cannot_act_on_foreign_tenant_alert(self):
        alert = PerseveranceAlert.objects.create(
            university=self.lyon, student=self.student_lyon, school_class=self.class_lyon,
            alert_type=TYPE, title="Signalement Lyon",
            detail="Situation à surveiller pour cet étudiant.", detected_at=timezone.now(),
        )
        self.login_admin()
        response = self.client.post(
            reverse("coaching:admin_alert_take", args=[alert.pk]), {"handling_note": ""},
        )
        self.assertEqual(response.status_code, 404)

    def test_professor_sees_alert_status(self):
        PerseveranceAlert.objects.create(
            university=self.paris, student=self.student_paris, school_class=self.class_paris,
            alert_type=TYPE, title="Signalement pédagogique · Camille Martin",
            detail="Baisse de participation.", priority=HIGH, reported_by=self.prof_paris,
            status=TAKEN, taken_by=self.admin_paris, taken_at=timezone.now(),
            handling_note="Rendez-vous planifié.", detected_at=timezone.now(),
        )
        self.login_prof()
        response = self.client.get(reverse("coaching:prof_followup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prise en charge")


class ComputedRiskTests(PortalTestBase):
    def make(self, **overrides):
        data = {
            "university": self.paris,
            "student": self.student_paris,
            "professor": self.prof_paris,
            "school_class": self.class_paris,
            "academic_year": ACADEMIC_YEAR,
        }
        data.update(overrides)
        return TutorAssignment.objects.create(**data)

    def test_low_when_no_indicators(self):
        assignment = self.make()
        self.assertEqual(assignment.risk_level, TutorAssignment.RISK_LOW)

    def test_high_when_average_below_10(self):
        assignment = self.make(average_grade="9.40", attendance_rate=90, assignments_submitted=8, assignments_total=10)
        self.assertEqual(assignment.risk_level, TutorAssignment.RISK_HIGH)

    def test_watch_when_average_below_12(self):
        assignment = self.make(average_grade="11.40", attendance_rate=90, assignments_submitted=9, assignments_total=10)
        self.assertEqual(assignment.risk_level, TutorAssignment.RISK_WATCH)

    def test_recomputes_on_indicator_change(self):
        assignment = self.make(average_grade="13.00", attendance_rate=95, assignments_submitted=9, assignments_total=10)
        self.assertEqual(assignment.risk_level, TutorAssignment.RISK_LOW)
        assignment.average_grade = "9.00"
        assignment.save(update_fields=["average_grade"])
        assignment.refresh_from_db()
        self.assertEqual(assignment.risk_level, TutorAssignment.RISK_HIGH)


class SeedRelanceFlowTests(PortalTestBase):
    def test_seed_is_idempotent(self):
        prof = create_user("prof.test@eduspark.local", first_name="Hélène", last_name="Vasseur")
        add_membership(prof, self.paris, Role.PROFESSOR, department="Informatique")
        add_membership(prof, self.lyon, Role.PROFESSOR, department="Mathématiques")
        for email, first, last in (
            ("test.ui@example.com", "Camille", "Martin"),
            ("ines.bernard@u-paris.fr", "Ines", "Bernard"),
            ("yanis.leroy@u-paris.fr", "Yanis", "Leroy"),
        ):
            add_membership(create_user(email, first_name=first, last_name=last), self.paris, Role.STUDENT)
        for email, first, last in (
            ("lucas.moreau@univ-lyon.fr", "Lucas", "Moreau"),
            ("sofia.benali@univ-lyon.fr", "Sofia", "Benali"),
        ):
            add_membership(create_user(email, first_name=first, last_name=last), self.lyon, Role.STUDENT)

        class_paris = SchoolClass.objects.create(
            university=self.paris, name="Licence 3 Informatique", level="3e année",
            program="Informatique", academic_year=ACADEMIC_YEAR,
        )
        class_lyon = SchoolClass.objects.create(
            university=self.lyon, name="Master 1 Mathématiques", level="Master 1",
            program="Mathématiques", academic_year=ACADEMIC_YEAR,
        )
        class_paris.professors.set([self.prof_paris])
        class_lyon.professors.set([self.prof_lyon])

        from coaching.management.commands import seed_coaching as seed_module

        with mock.patch.object(seed_module, "PARIS", self.paris.name), \
                mock.patch.object(seed_module, "LYON", self.lyon.name):
            call_command("seed_coaching", force=True)
            call_command("seed_coaching", force=True)

        self.assertEqual(TutorNotification.objects.filter(kind=TutorNotification.KIND_RELANCE).count(), 2)
        self.assertEqual(PerseveranceAlert.objects.count(), 7)

        yanis = TutorNotification.objects.get(
            student__membership__user__email="yanis.leroy@u-paris.fr",
            kind=TutorNotification.KIND_RELANCE,
        )
        self.assertIsNotNone(yanis.read_at)
        self.assertTrue(yanis.reply)
        camille = TutorNotification.objects.get(
            student__membership__user__email="test.ui@example.com",
            kind=TutorNotification.KIND_RELANCE,
        )
        self.assertIsNone(camille.read_at)

        closed = PerseveranceAlert.objects.get(
            student__membership__user__email="ines.bernard@u-paris.fr",
            alert_type=TYPE,
        )
        self.assertEqual(closed.status, CLOSED)
        self.assertEqual(closed.reported_by.membership.user.email, "prof.test@eduspark.local")
        self.assertIsNotNone(closed.closed_at)
        self.assertTrue(closed.resolution_note)
