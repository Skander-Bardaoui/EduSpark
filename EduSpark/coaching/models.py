"""Données du module Suivi Référent (coaching), cloisonnées par université."""

import uuid
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import (
    ProfessorProfile,
    SchoolClass,
    StudentGroup,
    StudentProfile,
    University,
)

from .language.config import (
    DEFAULT_LANGUAGE,
    EXAM_CHOICES,
    EXERCISE_CHOICES,
    LANGUAGE_CHOICES,
    LEVEL_CHOICES,
    SCORE_MAX,
    VERDICT_LABELS,
)


class _TenantModel(models.Model):
    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="+", verbose_name="Université",
    )

    class Meta:
        abstract = True

    def tenant_errors(self):
        errors = []
        for field in ("student", "professor", "school_class", "student_group"):
            related = getattr(self, field, None)
            if related is not None and related.university_id != self.university_id:
                errors.append(
                    ValidationError("%s n'appartient pas à l'université courante." % field)
                )
        return errors


class TutorAssignment(_TenantModel):
    """Référent pédagogique chargé du suivi global d'un étudiant pour une année."""

    STATUS_ACTIVE = "active"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Actif"),
        (STATUS_CLOSED, "Clôturé"),
    )

    RISK_LOW = "low"
    RISK_WATCH = "watch"
    RISK_HIGH = "high"
    RISK_CHOICES = (
        (RISK_LOW, "Faible"),
        (RISK_WATCH, "Vigilance"),
        (RISK_HIGH, "Haute"),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="tutor_assignments", verbose_name="Étudiant",
    )
    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.CASCADE,
        related_name="tutor_assignments", verbose_name="Tuteur",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tutor_assignments", verbose_name="Classe",
    )
    academic_year = models.CharField("Année universitaire", max_length=9)
    status = models.CharField(
        "Statut", max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )
    average_grade = models.DecimalField(
        "Moyenne", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    previous_average = models.DecimalField(
        "Moyenne précédente", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    attendance_rate = models.PositiveSmallIntegerField("Assiduité (%)", default=0)
    assignments_submitted = models.PositiveSmallIntegerField("Devoirs rendus", default=0)
    assignments_total = models.PositiveSmallIntegerField("Devoirs attendus", default=0)
    risk_level = models.CharField(
        "Niveau de risque", max_length=10, choices=RISK_CHOICES, default=RISK_LOW,
    )
    risk_reason = models.TextField("Motif de vigilance", blank=True)
    last_contact_at = models.DateTimeField("Dernier contact", null=True, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Affecté par",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("student__membership__user__last_name", "student__membership__user__first_name")
        verbose_name = "Tutorat étudiant"
        verbose_name_plural = "Tutorats étudiants"
        constraints = [
            models.UniqueConstraint(
                fields=("student", "academic_year"),
                condition=models.Q(status="active"),
                name="unique_active_tutor_per_student_year",
            ),
        ]
        indexes = [
            models.Index(fields=("university", "status"), name="coach_assign_uni_status_idx"),
            models.Index(fields=("professor", "status"), name="coach_assign_prof_status_idx"),
        ]

    def __str__(self):
        return "%s → %s" % (self.student, self.professor)

    @property
    def delta(self):
        if self.average_grade is None or self.previous_average is None:
            return None
        return self.average_grade - self.previous_average

    @property
    def assignments_ratio(self):
        if not self.assignments_total:
            return None
        return "%d/%d" % (self.assignments_submitted, self.assignments_total)

    def computed_risk_level(self):
        """Niveau de vigilance déduit des indicateurs (moyenne, assiduité, rendus)."""
        def number(value):
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        average = number(self.average_grade)
        previous = number(self.previous_average)
        attendance = self.attendance_rate or 0
        submitted = self.assignments_submitted or 0
        total = self.assignments_total or 0
        completion = (submitted / total) if total else None

        if average is None and previous is None and not attendance:
            return self.RISK_LOW

        if (
            (average is not None and average < 10)
            or attendance < 75
            or (completion is not None and completion < 0.5)
        ):
            return self.RISK_HIGH
        if (
            (average is not None and average < 12)
            or attendance < 85
            or (completion is not None and completion < 0.75)
            or (average is not None and previous is not None and previous - average > 0.5)
        ):
            return self.RISK_WATCH
        return self.RISK_LOW

    def clean(self):
        errors = self.tenant_errors()
        if self.student_id:
            if self.university_id != self.student.university_id:
                errors.append(ValidationError("L'étudiant n'appartient pas à cette université."))
        if self.professor_id and self.professor.university_id != self.university_id:
            errors.append(ValidationError("Le tuteur n'appartient pas à cette université."))
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        self.risk_level = self.computed_risk_level()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "risk_level" not in update_fields:
            kwargs["update_fields"] = list(update_fields) + ["risk_level"]
        super().save(*args, **kwargs)


class TutoringSlot(_TenantModel):
    """Créneau de permanence ouvert, réservé ou annulé."""

    MODE_INDIVIDUAL = "individual"
    MODE_GROUP = "group"
    MODE_VIDEO = "video"
    MODE_CHOICES = (
        (MODE_INDIVIDUAL, "Individuel"),
        (MODE_GROUP, "Collectif"),
        (MODE_VIDEO, "Visio"),
    )

    STATUS_OPEN = "open"
    STATUS_BOOKED = "booked"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_OPEN, "Disponible"),
        (STATUS_BOOKED, "Réservé"),
        (STATUS_CANCELLED, "Annulé"),
    )

    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.CASCADE,
        related_name="tutoring_slots", verbose_name="Tuteur",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tutoring_slots", verbose_name="Classe",
    )
    starts_at = models.DateTimeField("Début")
    ends_at = models.DateTimeField("Fin")
    mode = models.CharField(
        "Modalité", max_length=12, choices=MODE_CHOICES, default=MODE_INDIVIDUAL,
    )
    location = models.CharField("Lieu", max_length=120, blank=True)
    meeting_url = models.URLField("Lien visio", blank=True)
    status = models.CharField(
        "Statut", max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN,
    )
    reference = models.CharField("Référence", max_length=40, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Créé par",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ("starts_at",)
        verbose_name = "Créneau de tutorat"
        verbose_name_plural = "Créneaux de tutorat"
        constraints = [
            models.UniqueConstraint(
                fields=("professor", "starts_at"), name="unique_slot_per_professor_start",
            ),
            models.UniqueConstraint(
                fields=("professor", "reference"),
                condition=~models.Q(reference=""),
                name="unique_slot_reference_per_professor",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="tutoring_slot_end_after_start",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.professor, self.starts_at)

    def clean(self):
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError("La fin du créneau doit être postérieure au début.")

    def save(self, *args, **kwargs):
        if self.professor_id:
            self.university_id = self.professor.university_id
        super().save(*args, **kwargs)


class TutoringSession(_TenantModel):
    """Demande étudiante, rendez-vous confirmé ou entretien réalisé."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "En attente"),
        (STATUS_ACCEPTED, "Confirmé"),
        (STATUS_DECLINED, "Refusé"),
        (STATUS_COMPLETED, "Réalisé"),
        (STATUS_CANCELLED, "Annulé"),
    )

    PRIORITY_HIGH = "high"
    PRIORITY_NORMAL = "normal"
    PRIORITY_LOW = "low"
    PRIORITY_CHOICES = (
        (PRIORITY_HIGH, "Haute"),
        (PRIORITY_NORMAL, "Normale"),
        (PRIORITY_LOW, "Basse"),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="tutoring_sessions", verbose_name="Étudiant",
    )
    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.CASCADE,
        related_name="tutoring_sessions", verbose_name="Tuteur",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tutoring_sessions", verbose_name="Classe",
    )
    slot = models.ForeignKey(
        TutoringSlot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sessions", verbose_name="Créneau",
    )
    preferred_at = models.DateTimeField("Créneau souhaité", null=True, blank=True)
    scheduled_at = models.DateTimeField("Rendez-vous", null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField("Durée (min)", default=30)
    mode = models.CharField(
        "Modalité", max_length=12, choices=TutoringSlot.MODE_CHOICES,
        default=TutoringSlot.MODE_INDIVIDUAL,
    )
    location = models.CharField("Lieu", max_length=120, blank=True)
    meeting_url = models.URLField("Lien visioconférence", blank=True)
    topic = models.CharField("Motif", max_length=200)
    student_comment = models.TextField("Commentaire de l'étudiant", blank=True)
    priority = models.CharField(
        "Priorité", max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL,
    )
    status = models.CharField(
        "Statut", max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING,
    )
    decision_note = models.TextField("Réponse du tuteur", blank=True)
    summary_points = models.TextField("Points abordés", blank=True)
    summary_actions = models.TextField("Actions décidées", blank=True)
    completed_at = models.DateTimeField("Réalisé le", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Créé par",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Décidé par",
    )
    decided_at = models.DateTimeField("Décidé le", null=True, blank=True)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Rendez-vous de tutorat"
        verbose_name_plural = "Rendez-vous de tutorat"
        constraints = [
            models.UniqueConstraint(
                fields=("student", "professor"),
                condition=models.Q(status="pending"),
                name="unique_pending_request_per_pair",
            ),
        ]
        indexes = [
            models.Index(fields=("professor", "status"), name="coach_session_prof_status_idx"),
            models.Index(fields=("student", "status"), name="coach_session_stud_status_idx"),
        ]

    def __str__(self):
        return "%s ↔ %s" % (self.student, self.professor)

    @property
    def display_at(self):
        return self.scheduled_at or self.preferred_at

    @property
    def effective_meeting_url(self):
        """Lien visio du rendez-vous, ou celui du créneau s'il n'y en a pas."""
        if self.meeting_url:
            return self.meeting_url
        return self.slot.meeting_url if self.slot_id else ""

    def clean(self):
        errors = []
        if self.student_id and self.student.university_id != self.university_id:
            errors.append(ValidationError("L'étudiant n'appartient pas à cette université."))
        if self.professor_id and self.professor.university_id != self.university_id:
            errors.append(ValidationError("Le tuteur n'appartient pas à cette université."))
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        super().save(*args, **kwargs)


class StudentGoal(_TenantModel):
    """Objectif d'apprentissage semestriel suivi par l'étudiant."""

    STATUS_IN_PROGRESS = "in_progress"
    STATUS_AT_RISK = "at_risk"
    STATUS_ACHIEVED = "achieved"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_IN_PROGRESS, "En cours"),
        (STATUS_AT_RISK, "En retard"),
        (STATUS_ACHIEVED, "Objectif atteint"),
        (STATUS_ARCHIVED, "Archivé"),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="goals", verbose_name="Étudiant",
    )
    title = models.CharField("Intitulé", max_length=200)
    description = models.TextField("Description", blank=True)
    course_code = models.CharField("Code UE", max_length=20, blank=True)
    status = models.CharField(
        "Statut", max_length=12, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS,
    )
    progress = models.PositiveSmallIntegerField("Avancement (%)", default=0)
    skills_acquired = models.PositiveSmallIntegerField("Compétences acquises", default=0)
    skills_total = models.PositiveSmallIntegerField("Compétences visées", default=0)
    target_date = models.DateField("Échéance", null=True, blank=True)
    grade = models.DecimalField(
        "Note obtenue", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    semester = models.CharField("Semestre", max_length=30, default="Semestre 1")
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("target_date", "title")
        verbose_name = "Objectif étudiant"
        verbose_name_plural = "Objectifs étudiants"
        constraints = [
            models.UniqueConstraint(
                fields=("student", "semester", "title"),
                name="unique_goal_per_student_semester",
            ),
            models.CheckConstraint(
                condition=models.Q(progress__lte=100), name="student_goal_progress_lte_100",
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        super().save(*args, **kwargs)


class StudySession(_TenantModel):
    """Session de travail planifiée par l'étudiant (cours, révision, examen)."""

    KIND_COURSE = "course"
    KIND_REVISION = "revision"
    KIND_EXAM = "exam"
    KIND_CHOICES = (
        (KIND_COURSE, "Cours"),
        (KIND_REVISION, "Révision"),
        (KIND_EXAM, "Examen"),
    )

    STATUS_SCHEDULED = "scheduled"
    STATUS_POSTPONED = "postponed"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_SCHEDULED, "Programmé"),
        (STATUS_POSTPONED, "Reporté"),
        (STATUS_COMPLETED, "Complété"),
        (STATUS_CANCELLED, "Annulé"),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="study_sessions", verbose_name="Étudiant",
    )
    title = models.CharField("Intitulé", max_length=200)
    course_code = models.CharField("Code UE", max_length=20, blank=True)
    kind = models.CharField("Type", max_length=10, choices=KIND_CHOICES, default=KIND_REVISION)
    starts_at = models.DateTimeField("Début")
    duration_minutes = models.PositiveSmallIntegerField("Durée (min)", default=60)
    status = models.CharField(
        "Statut", max_length=12, choices=STATUS_CHOICES, default=STATUS_SCHEDULED,
    )
    location = models.CharField("Lieu", max_length=120, blank=True)
    notes = models.TextField("Notes", blank=True)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ("starts_at",)
        verbose_name = "Session de travail"
        verbose_name_plural = "Sessions de travail"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gt=0), name="study_duration_positive",
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        super().save(*args, **kwargs)


class StudentTask(_TenantModel):
    """Tâche académique de l'étudiant."""

    HORIZON_TODAY = "today"
    HORIZON_WEEK = "week"
    HORIZON_CHOICES = (
        (HORIZON_TODAY, "Aujourd'hui"),
        (HORIZON_WEEK, "Cette semaine"),
    )

    PRIORITY_HIGH = "high"
    PRIORITY_NORMAL = "normal"
    PRIORITY_LOW = "low"
    PRIORITY_CHOICES = (
        (PRIORITY_HIGH, "Prioritaire"),
        (PRIORITY_NORMAL, "Normale"),
        (PRIORITY_LOW, "Basse"),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="tasks", verbose_name="Étudiant",
    )
    title = models.CharField("Intitulé", max_length=200)
    context_label = models.CharField("Contexte", max_length=160, blank=True)
    horizon = models.CharField(
        "Horizon", max_length=10, choices=HORIZON_CHOICES, default=HORIZON_TODAY,
    )
    priority = models.CharField(
        "Priorité", max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL,
    )
    due_at = models.DateField("Échéance", null=True, blank=True)
    is_done = models.BooleanField("Terminée", default=False)
    completed_at = models.DateTimeField("Terminée le", null=True, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("is_done", "due_at", "-created_at")
        verbose_name = "Tâche étudiant"
        verbose_name_plural = "Tâches étudiant"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        if self.is_done and self.completed_at is None:
            self.completed_at = timezone.now()
        elif not self.is_done:
            self.completed_at = None
        super().save(*args, **kwargs)


class JournalEntry(_TenantModel):
    """Entrée du journal de progression d'un étudiant."""

    SENTIMENT_CONFIDENCE = "confidence"
    SENTIMENT_NEUTRAL = "neutral"
    SENTIMENT_ATTENTION = "attention"
    SENTIMENT_PRIDE = "pride"
    SENTIMENT_CHOICES = (
        (SENTIMENT_CONFIDENCE, "Confiance"),
        (SENTIMENT_NEUTRAL, "Neutre"),
        (SENTIMENT_ATTENTION, "Point d'attention"),
        (SENTIMENT_PRIDE, "Fierté"),
    )
    SENTIMENT_CONFIDENCE_SCORE = {
        SENTIMENT_CONFIDENCE: 8,
        SENTIMENT_NEUTRAL: 6,
        SENTIMENT_ATTENTION: 4,
        SENTIMENT_PRIDE: 10,
    }

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="journal_entries", verbose_name="Étudiant",
    )
    title = models.CharField("Titre", max_length=200)
    reflection = models.TextField("Réflexion")
    sentiment = models.CharField(
        "Ressenti", max_length=12, choices=SENTIMENT_CHOICES, default=SENTIMENT_NEUTRAL,
    )
    confidence = models.PositiveSmallIntegerField("Confiance (1-10)", default=6)
    entry_date = models.DateField("Date")
    feedback = models.TextField("Retour du tuteur", blank=True)
    feedback_by = models.ForeignKey(
        ProfessorProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="journal_feedbacks", verbose_name="Tuteur du retour",
    )
    feedback_at = models.DateTimeField("Retour le", null=True, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("-entry_date", "-created_at")
        verbose_name = "Entrée de journal"
        verbose_name_plural = "Entrées de journal"
        constraints = [
            models.UniqueConstraint(
                fields=("student", "entry_date", "title"),
                name="unique_journal_entry_per_day",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=1) & models.Q(confidence__lte=10),
                name="journal_confidence_between_1_10",
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        if not self.entry_date:
            self.entry_date = timezone.localdate()
        super().save(*args, **kwargs)


class TutorNotification(_TenantModel):
    """Message du tuteur référent délivré à l'étudiant dans son espace."""

    KIND_RELANCE = "relance"
    KIND_SUIVI = "suivi"
    KIND_CHOICES = (
        (KIND_RELANCE, "Relance"),
        (KIND_SUIVI, "Suivi"),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="tutor_notifications", verbose_name="Étudiant",
    )
    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tutor_notifications", verbose_name="Tuteur",
    )
    kind = models.CharField(
        "Type", max_length=12, choices=KIND_CHOICES, default=KIND_RELANCE,
    )
    title = models.CharField("Titre", max_length=200)
    message = models.TextField("Message")
    read_at = models.DateTimeField("Lue le", null=True, blank=True)
    reply = models.TextField("Réponse de l'étudiant", null=True, blank=True)
    replied_at = models.DateTimeField("Répondue le", null=True, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Notification tuteur"
        verbose_name_plural = "Notifications tuteur"
        indexes = [
            models.Index(fields=("student", "created_at"), name="coach_notif_student_idx"),
        ]

    def __str__(self):
        return self.title

    @property
    def is_unread(self):
        return self.read_at is None

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        super().save(*args, **kwargs)


class DifficultySheet(_TenantModel):
    """Fiche de difficulté ouverte par un professeur référent."""

    CATEGORY_METHODOLOGY = "methodology"
    CATEGORY_ATTENDANCE = "attendance"
    CATEGORY_WORKLOAD = "workload"
    CATEGORY_ORIENTATION = "orientation"
    CATEGORY_CHOICES = (
        (CATEGORY_METHODOLOGY, "Méthodologie"),
        (CATEGORY_ATTENDANCE, "Assiduité"),
        (CATEGORY_WORKLOAD, "Charge de travail"),
        (CATEGORY_ORIENTATION, "Orientation"),
    )

    SEVERITY_HIGH = "high"
    SEVERITY_MODERATE = "moderate"
    SEVERITY_REGULAR = "regular"
    SEVERITY_CHOICES = (
        (SEVERITY_HIGH, "Vigilance haute"),
        (SEVERITY_MODERATE, "Vigilance modérée"),
        (SEVERITY_REGULAR, "Suivi régulier"),
    )

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = (
        (STATUS_OPEN, "Ouverte"),
        (STATUS_IN_PROGRESS, "En cours"),
        (STATUS_CLOSED, "Clôturée"),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="difficulty_sheets", verbose_name="Étudiant",
    )
    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.CASCADE,
        related_name="difficulty_sheets", verbose_name="Référent",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="difficulty_sheets", verbose_name="Classe",
    )
    category = models.CharField("Type", max_length=15, choices=CATEGORY_CHOICES)
    severity = models.CharField(
        "Gravité", max_length=10, choices=SEVERITY_CHOICES, default=SEVERITY_MODERATE,
    )
    observation = models.TextField("Constat")
    action_plan = models.TextField("Plan d'accompagnement", blank=True)
    average_grade = models.DecimalField(
        "Moyenne", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    attendance_rate = models.PositiveSmallIntegerField("Assiduité (%)", default=0)
    assignments_submitted = models.PositiveSmallIntegerField("Devoirs rendus", default=0)
    assignments_total = models.PositiveSmallIntegerField("Devoirs attendus", default=0)
    status = models.CharField(
        "Statut", max_length=12, choices=STATUS_CHOICES, default=STATUS_OPEN,
    )
    opened_at = models.DateTimeField("Ouverte le", default=timezone.now)
    closed_at = models.DateTimeField("Clôturée le", null=True, blank=True)
    last_contact_at = models.DateTimeField("Dernier contact", null=True, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("-opened_at",)
        verbose_name = "Fiche de difficulté"
        verbose_name_plural = "Fiches de difficulté"
        constraints = [
            models.UniqueConstraint(
                fields=("student", "category"),
                condition=~models.Q(status="closed"),
                name="unique_open_sheet_per_student_category",
            ),
        ]
        indexes = [
            models.Index(fields=("professor", "status"), name="coach_sheet_prof_status_idx"),
        ]

    def __str__(self):
        return "%s — %s" % (self.student, self.get_category_display())

    @property
    def assignments_ratio(self):
        if not self.assignments_total:
            return None
        return "%d/%d" % (self.assignments_submitted, self.assignments_total)

    def clean(self):
        errors = []
        if self.student_id and self.professor_id and self.student.university_id != self.professor.university_id:
            errors.append(ValidationError("L'étudiant et le référent doivent être dans la même université."))
        if self.school_class_id and self.school_class.university_id != self.university_id:
            errors.append(ValidationError("La classe n'appartient pas à cette université."))
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.professor_id:
            self.university_id = self.professor.university_id
        super().save(*args, **kwargs)


class DifficultyNote(models.Model):
    """Observation ajoutée à une fiche de difficulté."""

    sheet = models.ForeignKey(
        DifficultySheet, on_delete=models.CASCADE,
        related_name="notes", verbose_name="Fiche",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="difficulty_notes", verbose_name="Auteur",
    )
    note = models.TextField("Note")
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Note de suivi"
        verbose_name_plural = "Notes de suivi"

    def __str__(self):
        return "Note du %s" % self.created_at


class PerseveranceAlert(_TenantModel):
    """Alerte de persévérance suivie par l'université."""

    TYPE_ATTENDANCE = "attendance"
    TYPE_ENGAGEMENT = "engagement"
    TYPE_GRADE = "grade"
    TYPE_CONFIDENCE = "confidence"
    TYPE_SUBMISSION = "submission"
    TYPE_CHOICES = (
        (TYPE_ATTENDANCE, "Assiduité"),
        (TYPE_ENGAGEMENT, "Engagement"),
        (TYPE_GRADE, "Résultats"),
        (TYPE_CONFIDENCE, "Confiance"),
        (TYPE_SUBMISSION, "Rendus"),
    )

    PRIORITY_HIGH = "high"
    PRIORITY_NORMAL = "normal"
    PRIORITY_LOW = "low"
    PRIORITY_CHOICES = (
        (PRIORITY_HIGH, "Haute"),
        (PRIORITY_NORMAL, "Normale"),
        (PRIORITY_LOW, "Basse"),
    )

    STATUS_OPEN = "open"
    STATUS_TAKEN = "taken"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = (
        (STATUS_OPEN, "Ouverte"),
        (STATUS_TAKEN, "Prise en charge"),
        (STATUS_CLOSED, "Clôturée"),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, null=True, blank=True,
        related_name="perseverance_alerts", verbose_name="Étudiant",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="perseverance_alerts", verbose_name="Classe",
    )
    student_group = models.ForeignKey(
        StudentGroup, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="perseverance_alerts", verbose_name="Groupe",
    )
    alert_type = models.CharField("Type", max_length=15, choices=TYPE_CHOICES)
    title = models.CharField("Titre", max_length=200)
    detail = models.TextField("Détail", blank=True)
    priority = models.CharField(
        "Priorité", max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL,
    )
    status = models.CharField(
        "Statut", max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN,
    )
    detected_at = models.DateTimeField("Détectée le", default=timezone.now)
    reported_by = models.ForeignKey(
        ProfessorProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="perseverance_alerts", verbose_name="Signalée par",
    )
    taken_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Prise en charge par",
    )
    taken_at = models.DateTimeField("Prise en charge le", null=True, blank=True)
    handling_note = models.TextField("Note de prise en charge", null=True, blank=True)
    closed_at = models.DateTimeField("Clôturée le", null=True, blank=True)
    resolution_note = models.TextField("Note de résolution", blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("status", "priority", "-detected_at")
        verbose_name = "Alerte de persévérance"
        verbose_name_plural = "Alertes de persévérance"
        constraints = [
            models.UniqueConstraint(
                fields=("student", "alert_type"),
                condition=models.Q(status="open", student__isnull=False),
                name="unique_open_alert_per_student_type",
            ),
        ]
        indexes = [
            models.Index(fields=("university", "status"), name="coach_alert_uni_status_idx"),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        if self.student_id and self.student.university_id != self.university_id:
            raise ValidationError("L'étudiant n'appartient pas à cette université.")
        if self.school_class_id and self.school_class.university_id != self.university_id:
            raise ValidationError("La classe n'appartient pas à cette université.")

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        elif self.school_class_id:
            self.university_id = self.school_class.university_id
        elif self.student_group_id:
            self.university_id = self.student_group.university_id
        super().save(*args, **kwargs)


class LanguageTestSession(_TenantModel):
    """Passation d'un test de langue orale par un étudiant."""

    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_ABANDONED = "abandoned"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "En cours"),
        (STATUS_COMPLETED, "Terminé"),
        (STATUS_ABANDONED, "Abandonné"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="language_test_sessions", verbose_name="Étudiant",
    )
    exam_type = models.CharField("Examen", max_length=20, choices=EXAM_CHOICES)
    level = models.CharField("Niveau", max_length=2, choices=LEVEL_CHOICES)
    exercise_type = models.CharField(
        "Exercice", max_length=20, choices=EXERCISE_CHOICES,
    )
    language = models.CharField(
        "Langue", max_length=2, choices=LANGUAGE_CHOICES, default=DEFAULT_LANGUAGE,
    )
    duration_seconds = models.PositiveIntegerField(
        "Durée (s)",
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
    )
    transcript = models.JSONField("Transcription", default=list, blank=True)
    status = models.CharField(
        "Statut", max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )
    started_at = models.DateTimeField("Démarré le", auto_now_add=True)
    ended_at = models.DateTimeField("Terminé le", null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)
        verbose_name = "Test de langue orale"
        verbose_name_plural = "Tests de langue orale"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(duration_seconds__gt=0),
                name="language_session_duration_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=("university", "student", "-started_at"),
                name="coach_lang_uni_student_idx",
            ),
            models.Index(
                fields=("university", "status"),
                name="coach_lang_uni_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.student} — {self.get_exam_type_display()} ({self.get_level_display()})"

    def clean(self):
        if self.student_id and self.student.university_id != self.university_id:
            raise ValidationError("L'étudiant n'appartient pas à cette université.")

    def save(self, *args, **kwargs):
        if self.student_id:
            self.university_id = self.student.university_id
        super().save(*args, **kwargs)


class LanguageTestFeedback(_TenantModel):
    """Résultat et bilan d'un test de langue orale."""

    VERDICT_CHOICES = tuple(VERDICT_LABELS.items())

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(
        LanguageTestSession, on_delete=models.CASCADE,
        related_name="feedback", verbose_name="Session",
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="language_test_results", verbose_name="Étudiant",
    )
    overall_level = models.CharField(
        "Niveau global", max_length=2, choices=LEVEL_CHOICES,
    )
    overall_verdict = models.CharField(
        "Verdict", max_length=20, choices=VERDICT_CHOICES,
    )
    fluency_score = models.PositiveSmallIntegerField(
        "Aisance", validators=[MinValueValidator(0), MaxValueValidator(SCORE_MAX)],
    )
    vocabulary_score = models.PositiveSmallIntegerField(
        "Vocabulaire", validators=[MinValueValidator(0), MaxValueValidator(SCORE_MAX)],
    )
    grammar_score = models.PositiveSmallIntegerField(
        "Grammaire", validators=[MinValueValidator(0), MaxValueValidator(SCORE_MAX)],
    )
    task_achievement_score = models.PositiveSmallIntegerField(
        "Réalisation de la tâche",
        validators=[MinValueValidator(0), MaxValueValidator(SCORE_MAX)],
    )
    fluency_notes = models.JSONField("Notes aisance", default=list, blank=True)
    vocabulary_notes = models.JSONField("Notes vocabulaire", default=list, blank=True)
    grammar_notes = models.JSONField("Notes grammaire", default=list, blank=True)
    task_achievement_notes = models.JSONField(
        "Notes réalisation", default=list, blank=True,
    )
    pronunciation_flags = models.JSONField("Prononciation", default=list, blank=True)
    recommendations = models.JSONField("Recommandations", default=list, blank=True)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Résultat de test de langue"
        verbose_name_plural = "Résultats de tests de langue"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fluency_score__gte=0, fluency_score__lte=SCORE_MAX),
                name="language_feedback_fluency_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    vocabulary_score__gte=0, vocabulary_score__lte=SCORE_MAX,
                ),
                name="language_feedback_vocabulary_range",
            ),
            models.CheckConstraint(
                condition=models.Q(grammar_score__gte=0, grammar_score__lte=SCORE_MAX),
                name="language_feedback_grammar_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    task_achievement_score__gte=0,
                    task_achievement_score__lte=SCORE_MAX,
                ),
                name="language_feedback_task_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("university", "student", "-created_at"),
                name="coach_lang_feedback_idx",
            ),
        ]

    def __str__(self):
        return f"Bilan {self.session_id} — {self.overall_level}"

    def clean(self):
        if self.session_id and self.session.university_id != self.university_id:
            raise ValidationError("La session n'appartient pas à cette université.")
        if self.session_id and self.student_id:
            if self.session.student_id != self.student_id:
                raise ValidationError("L'étudiant ne correspond pas à la session.")

    def save(self, *args, **kwargs):
        if self.session_id:
            self.student_id = self.session.student_id
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)


class AttendanceSession(_TenantModel):
    """Séance de cours (CM, TD, TP) servant au relevé des présences."""

    KIND_CM = "cm"
    KIND_TD = "td"
    KIND_TP = "tp"
    KIND_CHOICES = (
        (KIND_CM, "Cours magistral"),
        (KIND_TD, "Travaux dirigés"),
        (KIND_TP, "Travaux pratiques"),
    )

    STATUS_PLANNED = "planned"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PLANNED, "Planifiée"),
        (STATUS_COMPLETED, "Réalisée"),
        (STATUS_CANCELLED, "Annulée"),
    )

    slot = models.ForeignKey(
        "courses.ScheduleSlot", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attendance_sessions", verbose_name="Séance de l'emploi du temps",
    )
    session_date = models.DateField(
        "Date de la séance", null=True, blank=True,
        help_text="Date réelle de l'occurrence pour une séance issue de l'emploi du temps.",
    )
    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.CASCADE,
        related_name="attendance_sessions", verbose_name="Enseignant",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE,
        related_name="attendance_sessions", verbose_name="Classe",
    )
    student_group = models.ForeignKey(
        StudentGroup, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attendance_sessions", verbose_name="Groupe",
    )
    title = models.CharField("Module", max_length=160)
    kind = models.CharField(
        "Type de séance", max_length=10, choices=KIND_CHOICES, default=KIND_TD,
    )
    starts_at = models.DateTimeField("Début")
    duration_minutes = models.PositiveSmallIntegerField("Durée (min)", default=90)
    status = models.CharField(
        "Statut", max_length=12, choices=STATUS_CHOICES, default=STATUS_PLANNED,
    )
    notes = models.TextField("Notes", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Créée par",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("-starts_at",)
        verbose_name = "Séance de cours"
        verbose_name_plural = "Séances de cours"
        constraints = [
            models.UniqueConstraint(
                fields=("professor", "school_class", "starts_at", "title"),
                name="unique_attendance_session_per_slot",
            ),
            models.UniqueConstraint(
                fields=("slot", "session_date"),
                name="unique_attendance_session_per_timetable_date",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gt=0),
                name="attendance_session_duration_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=("university", "starts_at"),
                name="coach_attendance_uni_date_idx",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.title, self.starts_at)

    def clean(self):
        errors = []
        if self.slot_id:
            slot = self.slot
            if self.professor_id and slot.assignment.professor_id != self.professor_id:
                errors.append(ValidationError(
                    "La séance de l'emploi du temps n'est pas enseignée par ce professeur."
                ))
            if self.school_class_id and slot.assignment.school_class_id != self.school_class_id:
                errors.append(ValidationError(
                    "La séance de l'emploi du temps n'appartient pas à cette classe."
                ))
            if slot.group_id != self.student_group_id:
                errors.append(ValidationError(
                    "Le groupe de la séance ne correspond pas à celui de l'emploi du temps."
                ))
            if self.session_date and self.session_date.weekday() != slot.weekday:
                errors.append(ValidationError(
                    "La date choisie ne correspond pas au jour de la séance dans l'emploi du temps."
                ))
        if self.school_class_id and self.professor_id:
            if self.school_class.university_id != self.professor.university_id:
                errors.append(ValidationError(
                    "La classe et l'enseignant n'appartiennent pas à la même université."
                ))
        if self.student_group_id and self.school_class_id:
            if self.student_group.school_class_id != self.school_class_id:
                errors.append(ValidationError(
                    "Le groupe n'appartient pas à cette classe."
                ))
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.slot_id:
            slot = self.slot
            self.professor_id = slot.assignment.professor_id
            self.school_class_id = slot.assignment.school_class_id
            self.student_group_id = slot.group_id
            self.title = slot.assignment.subject.name
            self.kind = slot.session_type
            self.duration_minutes = slot.duration_minutes
            self.university_id = slot.university_id
            if not self.session_date and self.starts_at:
                self.session_date = timezone.localtime(self.starts_at).date()
            if self.session_date:
                self.starts_at = timezone.make_aware(
                    datetime.combine(self.session_date, slot.start_time)
                )
        if self.school_class_id:
            self.university_id = self.school_class.university_id
        super().save(*args, **kwargs)

    @property
    def attended_count(self):
        return self.records.filter(
            status__in=(AttendanceRecord.STATUS_PRESENT, AttendanceRecord.STATUS_LATE),
        ).count()

    @property
    def recorded_count(self):
        return self.records.exclude(status=AttendanceRecord.STATUS_EXCUSED).count()


class AttendanceRecord(_TenantModel):
    """Présence, retard, absence ou absence justifiée d'un étudiant à une séance."""

    STATUS_PRESENT = "present"
    STATUS_LATE = "late"
    STATUS_ABSENT = "absent"
    STATUS_EXCUSED = "excused"
    STATUS_CHOICES = (
        (STATUS_PRESENT, "Présent"),
        (STATUS_LATE, "En retard"),
        (STATUS_ABSENT, "Absent"),
        (STATUS_EXCUSED, "Absence justifiée"),
    )
    ATTENDED_STATUSES = (STATUS_PRESENT, STATUS_LATE)
    COUNTED_STATUSES = (STATUS_PRESENT, STATUS_LATE, STATUS_ABSENT)

    session = models.ForeignKey(
        AttendanceSession, on_delete=models.CASCADE,
        related_name="records", verbose_name="Séance",
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="attendance_records", verbose_name="Étudiant",
    )
    status = models.CharField(
        "Présence", max_length=10, choices=STATUS_CHOICES, default=STATUS_PRESENT,
    )
    note = models.CharField("Commentaire", max_length=200, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Saisi par",
    )
    recorded_at = models.DateTimeField("Saisi le", auto_now=True)

    class Meta:
        ordering = ("session__starts_at", "student__membership__user__last_name")
        verbose_name = "Présence"
        verbose_name_plural = "Présences"
        constraints = [
            models.UniqueConstraint(
                fields=("session", "student"), name="unique_attendance_per_session_student",
            ),
        ]
        indexes = [
            models.Index(
                fields=("student", "status"), name="coach_att_student_status_idx",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.student, self.get_status_display())

    def clean(self):
        if self.session_id and self.student_id:
            if self.session.university_id != self.student.university_id:
                raise ValidationError(
                    "La séance et l'étudiant n'appartiennent pas à la même université."
                )

    def save(self, *args, **kwargs):
        if self.session_id:
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)

