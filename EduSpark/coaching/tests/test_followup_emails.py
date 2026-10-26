"""Tests des e-mails envoyés par le suivi référent."""

from datetime import timedelta

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from coaching.tests.test_relance_flow import RelanceFlowBase


class FollowupEmailTests(RelanceFlowBase):
    def test_relance_sends_email_to_student(self):
        mail.outbox = []
        self.login_prof()
        self.client.post(
            reverse("coaching:prof_student_relance", args=[self.student_paris.pk]),
            self.relance_payload(),
        )
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.student_paris_user.email])
        self.assertIn("Relance", message.subject)
        self.assertTrue(any(
            alternative.mimetype == "text/html" for alternative in message.alternatives
        ))

    def test_alert_sends_email_to_university_admin(self):
        mail.outbox = []
        self.login_prof()
        self.client.post(
            reverse("coaching:prof_student_alert", args=[self.student_paris.pk]),
            self.alert_payload(),
        )
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.admin_paris.email])
        self.assertIn("Signalement", message.subject)
        self.assertTrue(any(
            alternative.mimetype == "text/html" for alternative in message.alternatives
        ))

    def test_appointment_request_emails_professor_and_student(self):
        mail.outbox = []
        self.login_student()
        response = self.client.post(
            reverse("coaching:student_appointment_request"),
            {
                "professor": self.prof_paris.pk,
                "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "time": "10:00",
                "topic": "Préparer le projet de bases de données",
            },
        )
        self.assertRedirects(response, reverse("coaching:student_appointments"))
        self.assertEqual(len(mail.outbox), 2)
        recipients = sorted(
            email for message in mail.outbox for email in message.to
        )
        self.assertEqual(recipients, sorted([
            self.prof_user.email,
            self.student_paris_user.email,
        ]))
        for message in mail.outbox:
            self.assertTrue(any(
                alternative.mimetype == "text/html" for alternative in message.alternatives
            ))
