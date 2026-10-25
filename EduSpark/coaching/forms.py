"""Formulaires de validation du module coaching (HTML construit à la main)."""

import re
from datetime import datetime, time, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    DifficultySheet,
    JournalEntry,
    StudentTask,
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
        label="Tuteur",
        min_value=1,
        error_messages={
            "required": "Sélectionnez un tuteur.",
            "invalid": "Sélectionnez un tuteur valide.",
            "min_value": "Sélectionnez un tuteur valide.",
        },
    )
    date = BookingDateField(label="Date")
    time = ClockField(label="Créneau")
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
        label="Tuteur",
        min_value=1,
        error_messages={
            "required": "Sélectionnez un tuteur.",
            "invalid": "Sélectionnez un tuteur valide.",
            "min_value": "Sélectionnez un tuteur valide.",
        },
    )
    count = forms.IntegerField(
        label="Nombre d'étudiants",
        min_value=1,
        max_value=60,
        error_messages={
            "required": REQUIRED,
            "invalid": INVALID_INTEGER,
            "min_value": "Le nombre doit être au moins 1.",
            "max_value": "Le nombre ne peut pas dépasser 60.",
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


class AlertHandleForm(forms.Form):
    resolution_note = forms.CharField(
        label="Note de résolution",
        required=False,
        max_length=2000,
        strip=True,
        error_messages={"max_length": "2000 caractères maximum."},
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
