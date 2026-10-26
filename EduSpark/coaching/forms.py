"""Formulaires de validation du module coaching (HTML construit à la main)."""

import re
from datetime import datetime, time, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    AttendanceSession,
    DifficultySheet,
    JournalEntry,
    PerseveranceAlert,
    StudentGoal,
    StudentTask,
    StudySession,
    TutoringSlot,
)

CLOCK_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
BOOKING_WINDOW_DAYS = 90
MIN_LEAD_MINUTES = 15

REQUIRED = "Ce champ est obligatoire."
INVALID_CHOICE = "Choisissez une valeur dans la liste."
INVALID_INTEGER = "Saisissez un nombre entier valide."


def validate_clock(value):
    if not CLOCK_PATTERN.match(value or ""):
        raise ValidationError("Saisissez une heure valide au format HH:MM (24 h).")
    hour, minute = (int(part) for part in value.split(":"))
    if minute not in (0, 30):
        raise ValidationError("Choisissez un créneau sur une demi-heure (:00 ou :30).")
    if not (time(7, 0) <= time(hour, minute) <= time(20, 30)):
        raise ValidationError("Choisissez une heure comprise entre 07:00 et 20:30.")


def combine_clock(day, clock):
    hour, minute = (int(part) for part in clock.split(":"))
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class ClockField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 5)
        kwargs.setdefault("validators", [validate_clock])
        kwargs.setdefault("error_messages", {
            "required": REQUIRED,
            "invalid": "Saisissez une heure valide au format HH:MM (24 h).",
        })
        super().__init__(**kwargs)


class BookingDateField(forms.DateField):
    def __init__(self, window_days=BOOKING_WINDOW_DAYS, **kwargs):
        self.window_days = window_days
        kwargs.setdefault("error_messages", {
            "required": REQUIRED,
            "invalid": "Saisissez une date valide (format AAAA-MM-JJ).",
        })
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        if value is None:
            return value
        today = timezone.localdate()
        if value < today:
            raise ValidationError("La date ne peut pas être dans le passé.")
        if value > today + timedelta(days=self.window_days):
            raise ValidationError(
                "La date doit être comprise dans les %d prochains jours."
                % self.window_days
            )
        return value


class TaskForm(forms.Form):
    title = forms.CharField(
        label="Intitulé",
        min_length=3,
        max_length=200,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "3 caractères minimum.",
            "max_length": "200 caractères maximum.",
        },
    )
    horizon = forms.ChoiceField(
        label="Horizon",
        choices=StudentTask.HORIZON_CHOICES,
        initial=StudentTask.HORIZON_TODAY,
        error_messages={
            "required": REQUIRED,
            "invalid_choice": INVALID_CHOICE,
        },
    )

    def clean_title(self):
        title = self.cleaned_data["title"]
        if not any(character.isalnum() for character in title):
            raise ValidationError("Indiquez au moins une lettre ou un chiffre.")
        return title


class JournalEntryForm(forms.Form):
    title = forms.CharField(
        label="Titre",
        min_length=3,
        max_length=200,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "3 caractères minimum.",
            "max_length": "200 caractères maximum.",
        },
    )
    sentiment = forms.ChoiceField(
        label="Ressenti",
        choices=JournalEntry.SENTIMENT_CHOICES,
        error_messages={
            "required": REQUIRED,
            "invalid_choice": INVALID_CHOICE,
        },
    )
    reflection = forms.CharField(
        label="Réflexion",
        min_length=20,
        max_length=5000,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "20 caractères minimum.",
            "max_length": "5000 caractères maximum.",
        },
    )

    def clean_title(self):
        title = self.cleaned_data["title"]
        if not any(character.isalnum() for character in title):
            raise ValidationError("Indiquez au moins une lettre ou un chiffre.")
        return title

    def clean_reflection(self):
        reflection = self.cleaned_data["reflection"]
        if len(reflection.split()) < 3:
            raise ValidationError("Détaillez la réflexion en au moins trois mots.")
        return reflection


class AppointmentForm(forms.Form):
    professor = forms.IntegerField(
        label="Interlocuteur",
        min_value=1,
        error_messages={
            "required": "Sélectionnez un interlocuteur.",
            "invalid": "Sélectionnez un interlocuteur valide.",
            "min_value": "Sélectionnez un interlocuteur valide.",
        },
    )
    date = BookingDateField(label="Date")
    time = ClockField(label="Créneau")
    slot = forms.IntegerField(required=False, min_value=1)
    topic = forms.CharField(
        label="Motif",
        min_length=5,
        max_length=200,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "5 caractères minimum.",
            "max_length": "200 caractères maximum.",
        },
    )
    comment = forms.CharField(
        label="Commentaire",
        required=False,
        max_length=1000,
        strip=True,
        error_messages={
            "max_length": "1000 caractères maximum.",
        },
    )

    def clean(self):
        data = super().clean()
        day = data.get("date")
        clock = data.get("time")
        if day and clock:
            start = combine_clock(day, clock)
            if start <= timezone.now() + timedelta(minutes=MIN_LEAD_MINUTES):
                raise ValidationError(
                    "Choisissez un créneau au moins %d minutes après l'heure actuelle."
                    % MIN_LEAD_MINUTES
                )
        return data


class SlotForm(forms.Form):
    date = BookingDateField(label="Date")
    time = ClockField(label="Créneau")
    mode = forms.ChoiceField(
        label="Modalité",
        choices=TutoringSlot.MODE_CHOICES,
        initial=TutoringSlot.MODE_INDIVIDUAL,
        error_messages={
            "required": REQUIRED,
            "invalid_choice": INVALID_CHOICE,
        },
    )

    def clean(self):
        data = super().clean()
        day = data.get("date")
        clock = data.get("time")
        if day and clock:
            start = combine_clock(day, clock)
            if start <= timezone.now() + timedelta(minutes=MIN_LEAD_MINUTES):
                raise ValidationError(
                    "Choisissez un créneau au moins %d minutes après l'heure actuelle."
                    % MIN_LEAD_MINUTES
                )
        return data


class AttendanceDateField(forms.DateField):
    """Date de séance : aujourd'hui ou dans les 180 derniers jours."""

    def __init__(self, window_days=180, **kwargs):
        self.window_days = window_days
        kwargs.setdefault("error_messages", {
            "required": REQUIRED,
            "invalid": "Saisissez une date valide (format AAAA-MM-JJ).",
        })
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        if value is None:
            return value
        today = timezone.localdate()
        if value > today:
            raise ValidationError("La séance ne peut pas être dans le futur.")
        if value < today - timedelta(days=self.window_days):
            raise ValidationError(
                "La date doit être comprise dans les %d derniers jours."
                % self.window_days
            )
        return value


class AttendanceSessionForm(forms.Form):
    school_class = forms.IntegerField(
        label="Classe",
        min_value=1,
        error_messages={
            "required": "Sélectionnez une classe.",
            "invalid": "Sélectionnez une classe valide.",
            "min_value": "Sélectionnez une classe valide.",
        },
    )
    title = forms.CharField(
        label="Module",
        min_length=3,
        max_length=160,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "3 caractères minimum.",
            "max_length": "160 caractères maximum.",
        },
    )
    kind = forms.ChoiceField(
        label="Type de séance",
        choices=AttendanceSession.KIND_CHOICES,
        initial=AttendanceSession.KIND_TD,
        error_messages={
            "required": REQUIRED,
            "invalid_choice": INVALID_CHOICE,
        },
    )
    date = AttendanceDateField(label="Date")
    time = ClockField(label="Heure")
    duration_minutes = forms.IntegerField(
        label="Durée (min)",
        min_value=15,
        max_value=480,
        initial=90,
        error_messages={
            "required": REQUIRED,
            "invalid": INVALID_INTEGER,
            "min_value": "La durée doit être au moins 15 minutes.",
            "max_value": "La durée ne peut pas dépasser 480 minutes.",
        },
    )


class DifficultySheetForm(forms.Form):
    student = forms.IntegerField(
        label="Étudiant",
        min_value=1,
        error_messages={
            "required": "Sélectionnez un étudiant.",
            "invalid": "Sélectionnez un étudiant valide.",
            "min_value": "Sélectionnez un étudiant valide.",
        },
    )
    category = forms.ChoiceField(
        label="Type de difficulté",
        choices=DifficultySheet.CATEGORY_CHOICES,
        error_messages={
            "required": REQUIRED,
            "invalid_choice": INVALID_CHOICE,
        },
    )
    observation = forms.CharField(
        label="Constat",
        min_length=10,
        max_length=2000,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "10 caractères minimum.",
            "max_length": "2000 caractères maximum.",
        },
    )
    action_plan = forms.CharField(
        label="Plan d'accompagnement",
        required=False,
        max_length=2000,
        strip=True,
        error_messages={"max_length": "2000 caractères maximum."},
    )
    severity = forms.ChoiceField(
        label="Gravité",
        choices=DifficultySheet.SEVERITY_CHOICES,
        initial=DifficultySheet.SEVERITY_MODERATE,
        required=False,
        error_messages={"invalid_choice": INVALID_CHOICE},
    )

    def clean_observation(self):
        observation = self.cleaned_data["observation"]
        if len(observation.split()) < 2:
            raise ValidationError("Décrivez le constat en au moins deux mots.")
        return observation


class GoalDateField(forms.DateField):
    """Échéance d'objectif : aujourd'hui ou dans les 365 prochains jours."""

    def __init__(self, window_days=365, **kwargs):
        self.window_days = window_days
        kwargs.setdefault("error_messages", {
            "required": REQUIRED,
            "invalid": "Saisissez une date valide (format AAAA-MM-JJ).",
        })
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        if value is None:
            return value
        today = timezone.localdate()
        if value < today:
            raise ValidationError("L'échéance ne peut pas être dans le passé.")
        if value > today + timedelta(days=self.window_days):
            raise ValidationError(
                "L'échéance doit être comprise dans les %d prochains jours."
                % self.window_days
            )
        return value


class StudentGoalForm(forms.Form):
    title = forms.CharField(
        label="Intitulé",
        min_length=3,
        max_length=200,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "3 caractères minimum.",
            "max_length": "200 caractères maximum.",
        },
    )
    description = forms.CharField(
        label="Description",
        required=False,
        max_length=2000,
        strip=True,
        error_messages={"max_length": "2000 caractères maximum."},
    )
    course_code = forms.CharField(
        label="Code UE",
        required=False,
        max_length=20,
        strip=True,
        error_messages={"max_length": "20 caractères maximum."},
    )
    semester = forms.CharField(
        label="Semestre",
        max_length=30,
        initial="Semestre 1",
        strip=True,
        error_messages={
            "required": REQUIRED,
            "max_length": "30 caractères maximum.",
        },
    )
    target_date = GoalDateField(label="Échéance", required=False)
    skills_total = forms.IntegerField(
        label="Compétences visées",
        required=False,
        min_value=0,
        max_value=50,
        initial=0,
        error_messages={
            "invalid": INVALID_INTEGER,
            "min_value": "Indiquez un nombre positif.",
            "max_value": "50 compétences maximum.",
        },
    )

    def clean_title(self):
        title = self.cleaned_data["title"]
        if not any(character.isalnum() for character in title):
            raise ValidationError("Indiquez au moins une lettre ou un chiffre.")
        return title


class GoalProgressForm(forms.Form):
    progress = forms.IntegerField(
        label="Avancement (%)",
        min_value=0,
        max_value=100,
        error_messages={
            "required": REQUIRED,
            "invalid": INVALID_INTEGER,
            "min_value": "L'avancement doit être compris entre 0 et 100.",
            "max_value": "L'avancement doit être compris entre 0 et 100.",
        },
    )
    skills_acquired = forms.IntegerField(
        label="Compétences acquises",
        required=False,
        min_value=0,
        max_value=50,
        error_messages={
            "invalid": INVALID_INTEGER,
            "min_value": "Indiquez un nombre positif.",
            "max_value": "50 compétences maximum.",
        },
    )


class StudySessionForm(forms.Form):
    title = forms.CharField(
        label="Intitulé",
        min_length=3,
        max_length=200,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "3 caractères minimum.",
            "max_length": "200 caractères maximum.",
        },
    )
    course_code = forms.CharField(
        label="Code UE",
        required=False,
        max_length=20,
        strip=True,
        error_messages={"max_length": "20 caractères maximum."},
    )
    kind = forms.ChoiceField(
        label="Type",
        choices=StudySession.KIND_CHOICES,
        initial=StudySession.KIND_REVISION,
        error_messages={
            "required": REQUIRED,
            "invalid_choice": INVALID_CHOICE,
        },
    )
    date = BookingDateField(window_days=120, label="Date")
    time = ClockField(label="Heure")
    duration_minutes = forms.IntegerField(
        label="Durée (min)",
        min_value=15,
        max_value=240,
        initial=60,
        error_messages={
            "required": REQUIRED,
            "invalid": INVALID_INTEGER,
            "min_value": "La durée doit être au moins 15 minutes.",
            "max_value": "La durée ne peut pas dépasser 240 minutes.",
        },
    )
    location = forms.CharField(
        label="Lieu",
        required=False,
        max_length=120,
        strip=True,
        error_messages={"max_length": "120 caractères maximum."},
    )

    def clean(self):
        data = super().clean()
        day = data.get("date")
        clock = data.get("time")
        if day and clock:
            start = combine_clock(day, clock)
            if start <= timezone.now() + timedelta(minutes=MIN_LEAD_MINUTES):
                raise ValidationError(
                    "Choisissez un créneau au moins %d minutes après l'heure actuelle."
                    % MIN_LEAD_MINUTES
                )
        return data


class DifficultyNoteForm(forms.Form):
    note = forms.CharField(
        label="Note de suivi",
        min_length=5,
        max_length=2000,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "5 caractères minimum.",
            "max_length": "2000 caractères maximum.",
        },
    )


class TutorAllocationForm(forms.Form):
    school_class = forms.IntegerField(
        label="Classe",
        min_value=1,
        error_messages={
            "required": "Sélectionnez une classe.",
            "invalid": "Sélectionnez une classe valide.",
            "min_value": "Sélectionnez une classe valide.",
        },
    )
    professor = forms.IntegerField(
        label="Référent pédagogique",
        min_value=1,
        error_messages={
            "required": "Sélectionnez un référent.",
            "invalid": "Sélectionnez un référent valide.",
            "min_value": "Sélectionnez un référent valide.",
        },
    )


class AutoAllocationForm(forms.Form):
    school_class = forms.IntegerField(
        label="Classe",
        min_value=1,
        error_messages={
            "required": "Sélectionnez une classe.",
            "invalid": "Sélectionnez une classe valide.",
            "min_value": "Sélectionnez une classe valide.",
        },
    )


class RelanceForm(forms.Form):
    subject = forms.CharField(
        label="Objet",
        min_length=5,
        max_length=200,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "5 caractères minimum.",
            "max_length": "200 caractères maximum.",
        },
    )
    message = forms.CharField(
        label="Message",
        min_length=20,
        max_length=2000,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "20 caractères minimum.",
            "max_length": "2000 caractères maximum.",
        },
    )

    def clean_subject(self):
        subject = self.cleaned_data["subject"]
        if not any(character.isalnum() for character in subject):
            raise ValidationError("Indiquez un objet avec au moins une lettre ou un chiffre.")
        return subject

    def clean_message(self):
        message = self.cleaned_data["message"]
        if len(message.split()) < 3:
            raise ValidationError("Détaillez le message en au moins trois mots.")
        return message


class NotificationReplyForm(forms.Form):
    reply = forms.CharField(
        label="Réponse",
        min_length=5,
        max_length=500,
        strip=True,
        error_messages={
            "required": "Rédigez une réponse pour votre tuteur.",
            "min_length": "5 caractères minimum.",
            "max_length": "500 caractères maximum.",
        },
    )

    def clean_reply(self):
        reply = self.cleaned_data["reply"]
        if len(reply.split()) < 2:
            raise ValidationError("Écrivez une réponse d'au moins deux mots.")
        return reply


class AlertReportForm(forms.Form):
    detail = forms.CharField(
        label="Signalement",
        min_length=20,
        max_length=2000,
        strip=True,
        error_messages={
            "required": REQUIRED,
            "min_length": "20 caractères minimum.",
            "max_length": "2000 caractères maximum.",
        },
    )
    priority = forms.ChoiceField(
        label="Priorité",
        choices=PerseveranceAlert.PRIORITY_CHOICES,
        initial=PerseveranceAlert.PRIORITY_NORMAL,
        error_messages={
            "required": REQUIRED,
            "invalid_choice": INVALID_CHOICE,
        },
    )

    def clean_detail(self):
        detail = self.cleaned_data["detail"]
        if len(detail.split()) < 2:
            raise ValidationError("Décrivez le signalement en au moins deux mots.")
        return detail


class AlertHandleForm(forms.Form):
    handling_note = forms.CharField(
        label="Note de prise en charge",
        required=False,
        max_length=2000,
        strip=True,
        error_messages={"max_length": "2000 caractères maximum."},
    )


class AlertCloseForm(forms.Form):
    resolution_note = forms.CharField(
        label="Note de résolution",
        min_length=5,
        max_length=2000,
        strip=True,
        error_messages={
            "required": "Rédigez une note de résolution pour clôturer l'alerte.",
            "min_length": "5 caractères minimum.",
            "max_length": "2000 caractères maximum.",
        },
    )


class DeclineRequestForm(forms.Form):
    note = forms.CharField(
        label="Motif du refus",
        required=False,
        max_length=2000,
        strip=True,
        error_messages={"max_length": "2000 caractères maximum."},
    )


class JournalFeedbackForm(forms.Form):
    feedback = forms.CharField(
        label="Retour du tuteur",
        min_length=5,
        max_length=2000,
        strip=True,
        error_messages={
            "required": "Rédigez un retour pour l'étudiant.",
            "min_length": "5 caractères minimum.",
            "max_length": "2000 caractères maximum.",
        },
    )


class SessionSummaryForm(forms.Form):
    summary_points = forms.CharField(
        label="Points abordés",
        min_length=5,
        max_length=2000,
        strip=True,
        error_messages={
            "required": "Résumez les points abordés.",
            "min_length": "5 caractères minimum.",
            "max_length": "2000 caractères maximum.",
        },
    )
    summary_actions = forms.CharField(
        label="Actions décidées",
        required=False,
        max_length=2000,
        strip=True,
        error_messages={"max_length": "2000 caractères maximum."},
    )


class DifficultyPlanForm(forms.Form):
    action_plan = forms.CharField(
        label="Plan d'action",
        min_length=5,
        max_length=2000,
        strip=True,
        error_messages={
            "required": "Rédigez le plan d'action.",
            "min_length": "5 caractères minimum.",
            "max_length": "2000 caractères maximum.",
        },
    )
