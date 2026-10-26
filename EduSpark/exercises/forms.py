"""Formulaires du module Exercices."""
from django import forms
from django.forms import inlineformset_factory

from .models import (
    Assignment, Category, Choice, Exercise, ExerciseSeries,
    Question, Rubric, RubricCriterion,
)

# ---------------------------------------------------------------------------
# Helpers de style
# ---------------------------------------------------------------------------

INPUT_CLASS = (
    "rounded border border-outline-variant/70 bg-surface px-3.5 py-2.5 "
    "text-sm text-on-surface outline-none transition-colors focus:border-primary w-full"
)
SELECT_CLASS = (
    "rounded border border-outline-variant/70 bg-surface px-3.5 py-2.5 "
    "text-sm text-on-surface outline-none transition-colors focus:border-primary w-full"
)
TEXTAREA_CLASS = (
    "rounded border border-outline-variant/70 bg-surface px-3.5 py-2.5 "
    "text-sm text-on-surface outline-none transition-colors focus:border-primary w-full"
)


def _apply_classes(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", SELECT_CLASS)
        elif isinstance(widget, forms.Textarea):
            widget.attrs.setdefault("class", TEXTAREA_CLASS)
        elif isinstance(widget, (forms.TextInput, forms.EmailInput, forms.NumberInput,
                                  forms.DateInput, forms.DateTimeInput)):
            widget.attrs.setdefault("class", INPUT_CLASS)


# ---------------------------------------------------------------------------
# Catégories
# ---------------------------------------------------------------------------

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "icon", "department", "description", "is_active")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex. Systèmes embarqués"}),
            "icon": forms.TextInput(attrs={"placeholder": "Ex. code"}),
            "department": forms.TextInput(attrs={"placeholder": "Ex. Informatique & IA"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_classes(self)


# ---------------------------------------------------------------------------
# Exercices
# ---------------------------------------------------------------------------

class ExerciseForm(forms.ModelForm):
    class Meta:
        model = Exercise
        fields = (
            "title", "subject", "level", "exercise_type", "difficulty",
            "duration_minutes", "category", "statement", "correction",
            "tags", "status", "image", "audio",
        )
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ex. Parcours en largeur"}),
            "subject": forms.TextInput(attrs={"placeholder": "Ex. Algorithmique"}),
            "level": forms.TextInput(attrs={"placeholder": "Ex. L3, M1"}),
            "duration_minutes": forms.NumberInput(attrs={"min": 1, "max": 300}),
            "statement": forms.Textarea(attrs={"rows": 6, "placeholder": "Énoncé de l'exercice..."}),
            "correction": forms.Textarea(attrs={"rows": 4, "placeholder": "Corrigé ou éléments de réponse..."}),
            "tags": forms.TextInput(attrs={"placeholder": "graphes, bfs, dfs"}),
        }

    def __init__(self, *args, university=None, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)
        if university:
            self.fields["category"].queryset = Category.objects.filter(
                university=university, is_active=True,
            )
        self.fields["category"].required = False
        _apply_classes(self)


# ---------------------------------------------------------------------------
# Questions & Choix
# ---------------------------------------------------------------------------

class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ("question_type", "text", "points", "explanation", "order")
        widgets = {
            "text": forms.Textarea(attrs={"rows": 3, "placeholder": "Texte de la question..."}),
            "explanation": forms.Textarea(attrs={"rows": 2, "placeholder": "Explication..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_classes(self)


class ChoiceForm(forms.ModelForm):
    class Meta:
        model = Choice
        fields = ("text", "is_correct", "order")
        widgets = {
            "text": forms.TextInput(attrs={"placeholder": "Texte du choix..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_classes(self)


ChoiceFormSet = inlineformset_factory(
    Question, Choice,
    form=ChoiceForm,
    extra=4,
    can_delete=True,
    max_num=8,
)


# ---------------------------------------------------------------------------
# Barèmes
# ---------------------------------------------------------------------------

class RubricForm(forms.ModelForm):
    class Meta:
        model = Rubric
        fields = ("name", "subject", "level", "icon", "status")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex. Grille TP programmation"}),
            "subject": forms.TextInput(attrs={"placeholder": "Ex. Algorithmique"}),
            "level": forms.TextInput(attrs={"placeholder": "Ex. L3, M1"}),
            "icon": forms.TextInput(attrs={"placeholder": "Ex. code"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_classes(self)


class RubricCriterionForm(forms.ModelForm):
    class Meta:
        model = RubricCriterion
        fields = ("name", "points", "description", "order")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex. Fonctionnalité"}),
            "points": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_classes(self)


CriterionFormSet = inlineformset_factory(
    Rubric, RubricCriterion,
    form=RubricCriterionForm,
    extra=2,
    can_delete=True,
    max_num=10,
)


# ---------------------------------------------------------------------------
# Séries
# ---------------------------------------------------------------------------

class ExerciseSeriesForm(forms.ModelForm):
    class Meta:
        model = ExerciseSeries
        fields = ("name", "subject", "description", "rubric", "visibility")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex. Révisions · Graphes"}),
            "subject": forms.TextInput(attrs={"placeholder": "Ex. Algorithmique avancée"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, university=None, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)
        if university:
            self.fields["rubric"].queryset = Rubric.objects.filter(university=university)
        self.fields["rubric"].required = False
        _apply_classes(self)


# ---------------------------------------------------------------------------
# Devoirs
# ---------------------------------------------------------------------------

class AssignmentForm(forms.ModelForm):
    deadline = forms.DateTimeField(
        label="Échéance",
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )

    class Meta:
        model = Assignment
        fields = (
            "title", "subject", "school_class", "instructions",
            "coefficient", "deadline", "rubric", "status",
            "expected_count",
        )
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ex. TP 3 · Détection d'anomalies"}),
            "subject": forms.TextInput(attrs={"placeholder": "Ex. Réseaux de neurones"}),
            "school_class": forms.TextInput(attrs={"placeholder": "Ex. M1 IA"}),
            "instructions": forms.Textarea(attrs={"rows": 4, "placeholder": "Consignes pour les étudiants..."}),
            "coefficient": forms.NumberInput(attrs={"min": 0.5, "max": 10, "step": 0.5}),
            "expected_count": forms.NumberInput(attrs={"min": 0}),
        }
        labels = {
            "expected_count": "Nombre d'étudiants attendus",
        }

    def __init__(self, *args, university=None, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)
        if university:
            self.fields["rubric"].queryset = Rubric.objects.filter(
                university=university, status="actif",
            )
        self.fields["rubric"].required = False
        _apply_classes(self)


# ---------------------------------------------------------------------------
# Formulaire IA (génération d'exercices)
# ---------------------------------------------------------------------------

class AIGenerateForm(forms.Form):
    """Formulaire de génération IA — subject/topic libres pour compatibilité drawer."""

    DIFFICULTY_CHOICES = (
        ("facile", "Débutant / Facile"),
        ("moyen", "Intermédiaire / Moyen"),
        ("intermediaire", "Intermédiaire"),
        ("avance", "Avancé"),
        ("difficile", "Avancé / Difficile"),
        ("expert", "Expert"),
    )
    TYPE_CHOICES = (
        ("qcm", "QCM"),
        ("vrai_faux", "Vrai / Faux"),
        ("trou", "Texte à trous"),
        ("probleme", "Problème ouvert"),
    )

    # Champ libre — n'importe quelle matière acceptée
    subject = forms.CharField(
        label="Matière",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Ex. Algorithmique"}),
    )
    # topic optionnel — si vide on utilise subject
    topic = forms.CharField(
        label="Sujet / notion",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            "class": INPUT_CLASS,
            "placeholder": "Ex. Rétropropagation, Protocole TCP/IP…",
        }),
    )
    difficulty = forms.ChoiceField(
        label="Difficulté",
        choices=DIFFICULTY_CHOICES,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    exercise_type = forms.ChoiceField(
        label="Type d'exercice",
        choices=TYPE_CHOICES,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    count = forms.IntegerField(
        label="Nombre de questions",
        min_value=1,
        max_value=20,
        initial=5,
        widget=forms.NumberInput(attrs={"class": INPUT_CLASS, "min": 1, "max": 20}),
    )

    def clean(self):
        cleaned = super().clean()
        # topic falls back to subject if not provided
        if not cleaned.get("topic"):
            cleaned["topic"] = cleaned.get("subject", "Général")
        if not cleaned.get("subject"):
            cleaned["subject"] = cleaned.get("topic", "Général")
        # Normalize difficulty: map aliases to canonical values
        diff_map = {
            "intermediaire": "moyen",
            "avance": "difficile",
        }
        diff = cleaned.get("difficulty", "moyen")
        cleaned["difficulty"] = diff_map.get(diff, diff)
        # Default exercise_type if missing
        if not cleaned.get("exercise_type"):
            cleaned["exercise_type"] = "qcm"
        return cleaned
