"""Tests du relevé de présences et du calcul d'assiduité."""

from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.tests import PortalTestBase

from coaching.models import (
    AttendanceRecord,
    AttendanceSession,
    DifficultySheet,
    TutorAssignment,
)
from coaching.services import attendance_metrics


class AttendanceRateTests(PortalTestBase):
    def setUp(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.paris)
        self.session = AttendanceSession.objects.create(
            university=self.paris,
            professor=self.prof_paris,
            school_class=self.class_paris,
            title="Algorithmique",
            starts_at=timezone.make_aware(datetime.combine(
                timezone.localdate(), time(9, 0),
            )),
            status=AttendanceSession.STATUS_COMPLETED,
        )
        self.assignment = TutorAssignment.objects.create(
            student=self.student_paris,
            professor=self.prof_paris,
            school_class=self.class_paris,
            academic_year="2025-2026",
            average_grade="13.00",
            previous_average="13.00",
            attendance_rate=0,
            assignments_submitted=10,
            assignments_total=10,
        )

    def add_record(self, status, session=None):
        if session is None:
            self._session_seq = getattr(self, "_session_seq", 0) + 1
            session = AttendanceSession.objects.create(
                university=self.paris,
                professor=self.prof_paris,
                school_class=self.class_paris,
                title="Séance %d" % self._session_seq,
                starts_at=timezone.make_aware(datetime.combine(
                    timezone.localdate(), time(9, 0),
                )) + timedelta(days=self._session_seq),
                status=AttendanceSession.STATUS_COMPLETED,
            )
        return AttendanceRecord.objects.create(
            university=self.paris,
            session=session,
            student=self.student_paris,
            status=status,
        )

    def test_late_counts_as_present_and_excused_is_excluded(self):
        self.add_record(AttendanceRecord.STATUS_PRESENT)
        self.add_record(AttendanceRecord.STATUS_LATE)
        self.add_record(AttendanceRecord.STATUS_ABSENT)
        self.add_record(AttendanceRecord.STATUS_EXCUSED)
        metrics = attendance_metrics(self.student_paris)
        self.assertEqual(metrics["attended"], 2)
        self.assertEqual(metrics["counted"], 3)
        self.assertEqual(metrics["excused"], 1)
        self.assertEqual(metrics["rate"], 67)

    def test_signal_updates_assignment_rate_and_risk(self):
        self.add_record(AttendanceRecord.STATUS_PRESENT)
        self.add_record(AttendanceRecord.STATUS_PRESENT)
        self.add_record(AttendanceRecord.STATUS_ABSENT)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.attendance_rate, 67)
        self.assertEqual(self.assignment.risk_level, TutorAssignment.RISK_HIGH)

    def test_deleting_last_record_resets_attendance(self):
        record = self.add_record(AttendanceRecord.STATUS_PRESENT)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.attendance_rate, 100)
        record.delete()
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.attendance_rate, 0)

    def test_difficulty_sheet_rate_is_synchronised(self):
        sheet = DifficultySheet.objects.create(
            university=self.paris,
            student=self.student_paris,
            professor=self.prof_paris,
            school_class=self.class_paris,
            category=DifficultySheet.CATEGORY_ATTENDANCE,
            severity=DifficultySheet.SEVERITY_HIGH,
            observation="Absences répétées.",
            average_grade="13.00",
            attendance_rate=0,
            assignments_submitted=1,
            assignments_total=2,
        )
        self.add_record(AttendanceRecord.STATUS_PRESENT)
        self.add_record(AttendanceRecord.STATUS_ABSENT)
        sheet.refresh_from_db()
        self.assertEqual(sheet.attendance_rate, 50)

    def test_cancelled_session_is_ignored(self):
        self.add_record(AttendanceRecord.STATUS_PRESENT)
        self.add_record(AttendanceRecord.STATUS_ABSENT, session=self.session)
        self.session.status = AttendanceSession.STATUS_CANCELLED
        self.session.save(update_fields=["status"])
        self.assertEqual(attendance_metrics(self.student_paris)["rate"], 100)

    def test_professor_can_list_sessions(self):
        response = self.client.get(reverse("coaching:prof_attendance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Présences")

    def test_attendance_list_stays_in_current_university(self):
        self.client.force_login(self.prof_user)
        self.set_current(self.lyon)
        response = self.client.get(reverse("coaching:prof_attendance"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.student_paris_user.email)

    def test_professor_can_create_session(self):
        response = self.client.post(
            reverse("coaching:prof_attendance_create"),
            {
                "school_class": self.class_paris.pk,
                "title": "Réseaux",
                "kind": AttendanceSession.KIND_TD,
                "date": timezone.localdate().isoformat(),
                "time": "11:00",
                "duration_minutes": 90,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AttendanceSession.objects.filter(
            professor=self.prof_paris,
            school_class=self.class_paris,
            title="Réseaux",
        ).exists())

    def test_professor_can_open_and_save_attendance(self):
        url = reverse("coaching:prof_attendance_session", args=[self.session.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Feuille de présence")

        response = self.client.post(
            reverse("coaching:prof_attendance_save", args=[self.session.pk]),
            {"status_%d" % self.student_paris.pk: AttendanceRecord.STATUS_ABSENT},
        )
        self.assertRedirects(response, reverse("coaching:prof_attendance"))
        record = AttendanceRecord.objects.get(session=self.session, student=self.student_paris)
        self.assertEqual(record.status, AttendanceRecord.STATUS_ABSENT)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.attendance_rate, 0)

    def test_professor_cannot_mark_another_university_session(self):
        self.client.force_login(self.prof_lyon_only_user)
        self.set_current(self.lyon)
        response = self.client.get(
            reverse("coaching:prof_attendance_session", args=[self.session.pk]),
        )
        self.assertEqual(response.status_code, 404)
