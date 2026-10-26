"""
Module Exercices — modèles de données.

Banque réutilisable : Exercise → Questions → Choices/Answer
Devoirs          : Assignment → AssignmentExercise → Submission
Séries           : ExerciseSeries → SeriesItem
Barèmes          : Rubric → RubricCriterion
Catégories       : Category (admin plateforme)
"""
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import University
from accounts.tenancy import Role


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uni(membership):
    """Retourne l'université d'une appartenance."""
    return membership.university if membership else None


# ---------------------------------------------------------------------------
# Catégories (admin plateforme / université)
# ---------------------------------------------------------------------------

class Category(models.Model):
    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="exercise_categories", verbose_name="Université",
    )
    name = models.CharField("Nom", max_length=100)
    icon = models.CharField("Icône Material", max_length=60, default="category")
    department = models.CharField("Département", max_length=120, blank=True)
    description = models.TextField("Description", blank=True)
    is_active = models.BooleanField("Active", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        unique_together = ("university", "name")

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Exercices
# ---------------------------------------------------------------------------

DIFFICULTY_CHOICES = (
    ("facile", "Facile"),
    ("moyen", "Moyen"),
    ("difficile", "Difficile"),
    ("expert", "Expert"),
)

TYPE_CHOICES = (
    ("qcm", "QCM"),
    ("vrai_faux", "Vrai / Faux"),
    ("trou", "Texte à trous"),
    ("code", "Code"),
    ("redaction", "Rédaction"),
    ("probleme", "Problème"),
)

STATUS_CHOICES = (
    ("brouillon", "Brouillon"),
    ("publie", "Publié"),
    ("archive", "Archivé"),
)


class Exercise(models.Model):
    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="exercises", verbose_name="Université",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="authored_exercises", verbose_name="Auteur",
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="exercises", verbose_name="Catégorie",
    )

    title = models.CharField("Titre", max_length=200)
    subject = models.CharField("Matière", max_length=120, blank=True)
    level = models.CharField("Niveau (classe)", max_length=60, blank=True,
                             help_text="Ex. L3, M1, M2")
    exercise_type = models.CharField("Type", max_length=20, choices=TYPE_CHOICES, default="qcm")
    difficulty = models.CharField("Difficulté", max_length=20, choices=DIFFICULTY_CHOICES, default="moyen")
    duration_minutes = models.PositiveSmallIntegerField("Durée (min)", default=20)
    statement = models.TextField("Énoncé")
    correction = models.TextField("Corrigé / corrigé-type", blank=True)
    tags = models.CharField("Tags", max_length=255, blank=True,
                            help_text="Mots-clés séparés par des virgules")
    status = models.CharField("Statut", max_length=20, choices=STATUS_CHOICES, default="brouillon")

    # Multimodal
    image = models.ImageField("Image illustrative", upload_to="exercises/images/", blank=True, null=True)
    audio = models.FileField("Fichier audio", upload_to="exercises/audio/", blank=True, null=True)
    image_prompt = models.TextField("Prompt image IA", blank=True)

    # IA
    ai_generated = models.BooleanField("Généré par IA", default=False)
    ai_validated = models.BooleanField("Validé par le prof", default=False)

    usage_count = models.PositiveIntegerField("Nb d'utilisations", default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        verbose_name = "Exercice"
        verbose_name_plural = "Exercices"

    def __str__(self):
        return self.title

    def get_difficulty_display_class(self):
        mapping = {
            "facile": "bg-primary-fixed text-primary",
            "moyen": "bg-secondary-fixed text-on-secondary-fixed",
            "difficile": "bg-tertiary-fixed text-on-tertiary-fixed",
            "expert": "bg-error-container text-on-error-container",
        }
        return mapping.get(self.difficulty, "bg-surface-container text-on-surface")

    def get_type_display_class(self):
        mapping = {
            "qcm": "bg-primary-fixed text-primary",
            "code": "bg-secondary-fixed text-on-secondary-fixed",
            "redaction": "bg-tertiary-fixed text-on-tertiary-fixed",
            "vrai_faux": "bg-primary-fixed text-primary",
            "trou": "bg-secondary-fixed text-on-secondary-fixed",
            "probleme": "bg-tertiary-fixed text-on-tertiary-fixed",
        }
        return mapping.get(self.exercise_type, "bg-surface-container text-on-surface")


# ---------------------------------------------------------------------------
# Questions et choix (QCM / Vrai-Faux / Texte à trous)
# ---------------------------------------------------------------------------

class Question(models.Model):
    QUESTION_TYPES = (
        ("qcm", "QCM"),
        ("vrai_faux", "Vrai / Faux"),
        ("trou", "Trou"),
        ("ouverte", "Ouverte"),
    )
    exercise = models.ForeignKey(
        Exercise, on_delete=models.CASCADE,
        related_name="questions", verbose_name="Exercice",
    )
    order = models.PositiveSmallIntegerField("Ordre", default=1)
    question_type = models.CharField("Type", max_length=20, choices=QUESTION_TYPES, default="qcm")
    text = models.TextField("Question")
    points = models.DecimalField("Points", max_digits=5, decimal_places=2, default=1)
    explanation = models.TextField("Explication de la réponse", blank=True)

    class Meta:
        ordering = ("exercise", "order")
        verbose_name = "Question"

    def __str__(self):
        return f"Q{self.order} — {self.exercise.title}"


class Choice(models.Model):
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE,
        related_name="choices", verbose_name="Question",
    )
    text = models.CharField("Texte du choix", max_length=500)
    is_correct = models.BooleanField("Correct", default=False)
    order = models.PositiveSmallIntegerField("Ordre", default=1)

    class Meta:
        ordering = ("question", "order")
        verbose_name = "Choix"

    def __str__(self):
        return f"{'✓' if self.is_correct else '✗'} {self.text[:60]}"


# ---------------------------------------------------------------------------
# Barèmes
# ---------------------------------------------------------------------------

RUBRIC_STATUS = (
    ("actif", "Actif"),
    ("brouillon", "Brouillon"),
    ("archive", "Archivé"),
)


class Rubric(models.Model):
    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="rubrics", verbose_name="Université",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="authored_rubrics",
    )
    name = models.CharField("Nom du barème", max_length=200)
    subject = models.CharField("Matière", max_length=120, blank=True)
    level = models.CharField("Niveau", max_length=60, blank=True)
    icon = models.CharField("Icône Material", max_length=60, default="checklist")
    status = models.CharField("Statut", max_length=20, choices=RUBRIC_STATUS, default="brouillon")
    usage_count = models.PositiveIntegerField("Nb d'utilisations", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        verbose_name = "Barème"
        verbose_name_plural = "Barèmes"

    def __str__(self):
        return self.name

    @property
    def total_points(self):
        return sum(c.points for c in self.criteria.all())


class RubricCriterion(models.Model):
    rubric = models.ForeignKey(
        Rubric, on_delete=models.CASCADE,
        related_name="criteria", verbose_name="Barème",
    )
    name = models.CharField("Critère", max_length=200)
    points = models.PositiveSmallIntegerField("Points")
    description = models.TextField("Description", blank=True)
    order = models.PositiveSmallIntegerField("Ordre", default=1)

    class Meta:
        ordering = ("rubric", "order")
        verbose_name = "Critère"

    def __str__(self):
        return f"{self.rubric} — {self.name}"


# ---------------------------------------------------------------------------
# Séries d'exercices
# ---------------------------------------------------------------------------

SERIES_VISIBILITY = (
    ("brouillon", "Brouillon"),
    ("publiee", "Publiée"),
    ("privee", "Privée"),
)


class ExerciseSeries(models.Model):
    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="exercise_series",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="authored_series",
    )
    rubric = models.ForeignKey(
        Rubric, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="series",
    )
    name = models.CharField("Nom de la série", max_length=200)
    subject = models.CharField("Matière", max_length=120, blank=True)
    description = models.TextField("Description", blank=True)
    visibility = models.CharField("Visibilité", max_length=20, choices=SERIES_VISIBILITY, default="brouillon")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        verbose_name = "Série"
        verbose_name_plural = "Séries"

    def __str__(self):
        return self.name

    @property
    def exercise_count(self):
        return self.items.count()


class SeriesItem(models.Model):
    series = models.ForeignKey(ExerciseSeries, on_delete=models.CASCADE, related_name="items")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="series_items")
    order = models.PositiveSmallIntegerField("Ordre", default=1)

    class Meta:
        ordering = ("series", "order")
        unique_together = ("series", "exercise")


# ---------------------------------------------------------------------------
# Devoirs
# ---------------------------------------------------------------------------

ASSIGNMENT_STATUS = (
    ("brouillon", "Brouillon"),
    ("ouvert", "Ouvert"),
    ("correction", "À corriger"),
    ("termine", "Terminé"),
)


class Assignment(models.Model):
    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="assignments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="created_assignments",
    )
    rubric = models.ForeignKey(
        Rubric, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assignments",
    )

    title = models.CharField("Titre", max_length=200)
    subject = models.CharField("Matière", max_length=120, blank=True)
    school_class = models.CharField("Classe", max_length=80, blank=True)
    instructions = models.TextField("Consignes", blank=True)
    coefficient = models.DecimalField("Coefficient", max_digits=4, decimal_places=2, default=1)
    deadline = models.DateTimeField("Échéance", null=True, blank=True)
    status = models.CharField("Statut", max_length=20, choices=ASSIGNMENT_STATUS, default="brouillon")

    # Statistiques dénormalisées (mise à jour par signals)
    submissions_count = models.PositiveIntegerField("Dépôts reçus", default=0)
    expected_count = models.PositiveIntegerField("Dépôts attendus", default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        verbose_name = "Devoir"
        verbose_name_plural = "Devoirs"

    def __str__(self):
        return self.title

    @property
    def submission_rate(self):
        if not self.expected_count:
            return 0
        return int(self.submissions_count / self.expected_count * 100)

    @property
    def status_badge_class(self):
        mapping = {
            "brouillon": "bg-surface-container text-on-surface-variant",
            "ouvert": "bg-primary-fixed text-primary",
            "correction": "bg-tertiary-fixed text-on-tertiary-fixed",
            "termine": "bg-surface-container text-on-surface-variant",
        }
        return mapping.get(self.status, "bg-surface-container text-on-surface-variant")

    @property
    def is_overdue(self):
        return self.deadline and self.deadline < timezone.now() and self.status == "ouvert"


class AssignmentExercise(models.Model):
    """Exercice inclus dans un devoir (pivot)."""
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="items")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="assignment_items")
    order = models.PositiveSmallIntegerField("Ordre", default=1)
    points_override = models.DecimalField(
        "Points (surcharge)", max_digits=5, decimal_places=2, null=True, blank=True,
    )

    class Meta:
        ordering = ("assignment", "order")
        unique_together = ("assignment", "exercise")


# ---------------------------------------------------------------------------
# Soumissions étudiants (devoirs)
# ---------------------------------------------------------------------------

SUBMISSION_STATUS = (
    ("brouillon", "Brouillon"),
    ("rendu", "Rendu"),
    ("corrige", "Corrigé"),
)


class StudentSubmission(models.Model):
    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE,
        related_name="submissions",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="submissions",
    )
    status = models.CharField("Statut", max_length=20, choices=SUBMISSION_STATUS, default="brouillon")
    content = models.TextField("Contenu / réponse", blank=True)
    file = models.FileField("Fichier rendu", upload_to="submissions/", blank=True, null=True)
    grade = models.DecimalField("Note /20", max_digits=4, decimal_places=2, null=True, blank=True)
    feedback = models.TextField("Commentaire du correcteur", blank=True)
    submitted_at = models.DateTimeField("Rendu le", null=True, blank=True)
    graded_at = models.DateTimeField("Corrigé le", null=True, blank=True)
    progress_pct = models.PositiveSmallIntegerField("Progression %", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        unique_together = ("assignment", "student")
        verbose_name = "Soumission"

    def __str__(self):
        return f"{self.student} → {self.assignment}"

    @property
    def status_badge_class(self):
        mapping = {
            "brouillon": "bg-surface-container-high text-on-surface",
            "rendu": "bg-surface-container-highest text-primary",
            "corrige": "bg-primary-fixed text-primary",
        }
        return mapping.get(self.status, "")

    def submit(self):
        self.status = "rendu"
        self.submitted_at = timezone.now()
        self.progress_pct = 100
        self.save(update_fields=["status", "submitted_at", "progress_pct", "updated_at"])
        # Mise à jour compteur devoir
        Assignment.objects.filter(pk=self.assignment_id).update(
            submissions_count=models.F("submissions_count") + 1,
        )


# ---------------------------------------------------------------------------
# Tentatives d'entraînement (séries libres)
# ---------------------------------------------------------------------------

class PracticeAttempt(models.Model):
    RESULT_CHOICES = (
        ("reussi", "Réussi"),
        ("a_revoir", "À revoir"),
        ("parfait", "Parfait"),
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="practice_attempts",
    )
    series = models.ForeignKey(
        ExerciseSeries, on_delete=models.CASCADE,
        related_name="attempts",
    )
    score = models.PositiveSmallIntegerField("Score obtenu", default=0)
    max_score = models.PositiveSmallIntegerField("Score max", default=0)
    duration_minutes = models.PositiveSmallIntegerField("Durée (min)", default=0)
    result = models.CharField("Résultat", max_length=20, choices=RESULT_CHOICES, default="a_revoir")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Tentative d'entraînement"

    def __str__(self):
        return f"{self.student} — {self.series} {self.score}/{self.max_score}"

    @property
    def result_badge_class(self):
        mapping = {
            "reussi": "bg-primary-fixed text-primary",
            "parfait": "bg-primary-fixed text-primary",
            "a_revoir": "bg-tertiary-fixed text-on-tertiary-fixed",
        }
        return mapping.get(self.result, "")
