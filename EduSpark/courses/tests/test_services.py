"""Fonctions de service : grille hebdomadaire, prochaine séance, sélection de classe, publication."""

from datetime import date, datetime, time

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from accounts.models import SchoolClass
from courses.models import CoursePublication, ScheduleSlot
from courses.services import (
    build_week_grid, format_date, format_minutes, next_session, pick_class, set_publication,
    student_classes,
)

from .base import CoursesTestCase


def slot(weekday, start, end, pk=None):
    return ScheduleSlot(
        pk=pk, weekday=weekday, start_time=time.fromisoformat(start), end_time=time.fromisoformat(end),
    )


class FormattingTests(SimpleTestCase):
    def test_format_minutes(self):
        self.assertEqual(
            [format_minutes(value) for value in (0, 45, 60, 90, 180, 210, None)],
            ["0 min", "45 min", "1 h", "1 h 30", "3 h", "3 h 30", "0 min"],
        )

    def test_format_date_is_french(self):
        self.assertEqual(format_date(date(2026, 10, 26)), "26 octobre")
        self.assertEqual(format_date(date(2026, 2, 3)), "3 février")


class WeekGridTests(SimpleTestCase):
    monday = date(2026, 10, 26)

    def test_columns_are_weekdays_and_sessions_are_sorted_by_time(self):
        slots = [slot(0, "14:00", "15:30", 3), slot(0, "08:30", "10:00", 1), slot(2, "10:15", "11:45", 2)]
        grid = build_week_grid(slots, today=date(2026, 10, 28))
        self.assertEqual([d["label"] for d in grid["days"]], ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"])
        self.assertEqual([s.pk for s in grid["days"][0]["slots"]], [1, 3])
        self.assertEqual([s.pk for s in grid["days"][2]["slots"]], [2])
        self.assertEqual(grid["days"][1]["slots"], [])
        self.assertEqual(grid["slot_count"], 3)
        self.assertEqual(grid["total_minutes"], 90 + 90 + 90)
        self.assertEqual(grid["total_label"], "4 h 30")
        self.assertFalse(grid["show_saturday"])

    def test_dates_and_today_marker(self):
        grid = build_week_grid([], today=date(2026, 10, 28))  # un mercredi
        self.assertEqual(grid["days"][0]["date"], self.monday)
        self.assertEqual([d["is_today"] for d in grid["days"]], [False, False, True, False, False])
        self.assertEqual(grid["week_label"], "Semaine du 26 octobre au 30 octobre 2026")
        self.assertEqual(grid["days"][0]["date_label"], "26 octobre")

    def test_saturday_column_appears_with_a_saturday_session(self):
        grid = build_week_grid([slot(5, "09:00", "11:00")], today=self.monday)
        self.assertTrue(grid["show_saturday"])
        self.assertEqual(len(grid["days"]), 6)
        self.assertEqual(grid["week_label"], "Semaine du 26 octobre au 31 octobre 2026")

    def test_week_spanning_two_months_and_years(self):
        grid = build_week_grid([], today=date(2026, 12, 30))
        self.assertEqual(grid["week_label"], "Semaine du 28 décembre au 1 janvier 2027")


class NextSessionTests(SimpleTestCase):
    slots = [slot(0, "08:30", "10:00", 1), slot(2, "14:00", "15:30", 2)]

    def at(self, day, hour, minute=0):
        return timezone.make_aware(datetime(2026, 10, day, hour, minute))  # le 26 octobre 2026 est un lundi

    def test_ongoing_session(self):
        result = next_session(self.slots, now=self.at(26, 9))
        self.assertEqual((result["slot"].pk, result["ongoing"], result["when"]), (1, True, "En cours"))

    def test_later_today(self):
        result = next_session(self.slots, now=self.at(28, 10))  # mercredi 10 h
        self.assertEqual((result["slot"].pk, result["when"]), (2, "Aujourd'hui à 14:00"))

    def test_tomorrow(self):
        result = next_session(self.slots, now=self.at(27, 10))  # mardi
        self.assertEqual((result["slot"].pk, result["when"]), (2, "Demain à 14:00"))

    def test_later_this_week(self):
        result = next_session(self.slots, now=self.at(26, 11))  # lundi 11 h, après la séance du matin
        self.assertEqual((result["slot"].pk, result["when"]), (2, "Mercredi à 14:00"))

    def test_wraps_to_next_week(self):
        result = next_session(self.slots, now=self.at(28, 16))  # mercredi 16 h : tout est passé
        self.assertEqual((result["slot"].pk, result["when"]), (1, "Lundi à 08:30"))
        self.assertEqual(result["start"].date(), date(2026, 11, 2))

    def test_session_ending_exactly_now_is_over(self):
        result = next_session([slot(0, "08:30", "10:00", 1)], now=self.at(26, 10))
        self.assertFalse(result["ongoing"])
        self.assertEqual(result["start"].date(), date(2026, 11, 2))

    def test_no_session(self):
        self.assertIsNone(next_session([], now=self.at(26, 9)))


class PickClassTests(CoursesTestCase):
    def test_pick_class(self):
        classes = [self.school_class, self.class_gl]
        self.assertEqual(pick_class(classes, None), self.school_class)
        self.assertEqual(pick_class(classes, ""), self.school_class)
        self.assertEqual(pick_class(classes, str(self.class_gl.pk)), self.class_gl)
        self.assertEqual(pick_class(classes, "abc"), self.school_class)
        self.assertEqual(pick_class(classes, str(self.other_class.pk)), self.school_class)
        self.assertIsNone(pick_class([], "1"))

    def test_student_classes(self):
        self.assertEqual(list(student_classes(self.student)), [self.school_class])
        self.assertEqual(list(student_classes(self.student3)), [])
        self.assertEqual(list(student_classes(None)), [])
        self.assertTrue(isinstance(student_classes(self.student).first(), SchoolClass))


class PublicationServiceTests(CoursesTestCase):
    def test_publish_and_withdraw(self):
        course = self.make_course()
        publication = set_publication(course, self.school_class, True)
        self.assertTrue(publication.is_published)
        self.assertIsNotNone(publication.published_at)
        publication = set_publication(course, self.school_class, False)
        self.assertFalse(publication.is_published)
        self.assertIsNone(publication.published_at)
        self.assertEqual(CoursePublication.objects.count(), 1)

    def test_refuses_a_class_where_the_subject_is_not_taught(self):
        course = self.make_course()
        with self.assertRaises(ValidationError):
            set_publication(course, self.class_gl, True)
        self.assertFalse(CoursePublication.objects.exists())

    def test_refuses_a_class_taught_by_someone_else(self):
        course = self.make_course(professor=self.prof2, subject=self.subject2)
        with self.assertRaises(ValidationError):
            set_publication(course, self.class_gl, True)
