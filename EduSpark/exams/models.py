import re
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import SchoolClass, StudentProfile, University
from courses.storage import ProtectedMediaStorage

DEFAULT_ACADEMIC_YEAR = "2025-2026"


def copy_upload_path(instance, filename):
    """Conservé pour la compatibilité des migrations historiques."""
    return "exams/copies/%s_%s" % (uuid4().hex, filename)


def copy_file_upload_path(instance, filename):
    """Conservé pour la compatibilité des migrations historiques."""
    return "exams/copy-files/%s_%s" % (uuid4().hex, filename)


def subject_upload_path(instance, filename):
    """Conservé pour la compatibilité des migrations historiques."""
    return "exams/subjects/%s_%s" % (uuid4().hex, filename)


def project_upload_path(instance, filename):
    """Chemin aléatoire d'un projet étudiant, hors de MEDIA_ROOT."""
    return "exams/projects/%s/%s.zip" % (instance.session_id, uuid4().hex)

_WEEKDAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def semester_for(school_class):
    """Libellé du semestre courant pour une classe."""
    return "Semestre 1 · %s" % (school_class.academic_year or DEFAULT_ACADEMIC_YEAR)


class ExamSession(models.Model):
    """Session d'évaluation planifiée pour une classe.

    Le type d'épreuve détermine le parcours : QCM en ligne, dépét d'un projet
    ZIP ou tirage d'un sujet d'oral. La fenêtre ``opens_at`` / ``closes_at``
    reste commune aux trois formats.
    """

    TYPE_QCM = "qcm"
    TYPE_PROJECT = "projet"
    TYPE_ORAL = "oral"
    TYPE_CHOICES = (
        (TYPE_QCM, "QCM en ligne"),
        (TYPE_PROJECT, "Projet (dépét ZIP)"),
        (TYPE_ORAL, "Examen oral"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="exam_sessions", verbose_name="Université",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE,
        related_name="exam_sessions", verbose_name="Classe",
    )
    course_subject = models.ForeignKey(
        "courses.Subject", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="exam_sessions", verbose_name="Matière",
    )
    title = models.CharField("Épreuve", max_length=160)
    exam_type = models.CharField(
        "Type d'épreuve", max_length=20, choices=TYPE_CHOICES,
        default=TYPE_QCM, blank=True,
    )
    instructions = models.TextField(
        "Consignes", blank=True,
        help_text="Consignes affichées aux étudiants pour cette épreuve.",
    )
    opens_at = models.DateTimeField("Ouverture")
    closes_at = models.DateTimeField("Fermeture")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_exam_sessions", verbose_name="Créée par",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("opens_at", "school_class__name")
        verbose_name = "Session QCM"
        verbose_name_plural = "Sessions QCM"

    def __str__(self):
        return "%s — %s (%s)" % (self.title, self.school_class, self.date_label)

    def clean(self):
        if (
            self.school_class_id and self.university_id
            and self.school_class.university_id != self.university_id
        ):
            raise ValidationError("La classe et la session doivent appartenir à la même université.")
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise ValidationError({"closes_at": "La fermeture doit être postérieure à l'ouverture."})
        if (
            self.course_subject_id and self.university_id
            and self.course_subject.university_id != self.university_id
        ):
            raise ValidationError({
                "course_subject": "La matière et la session doivent appartenir à la même université.",
            })
        if (
            self.course_subject_id and self.school_class_id
            and self.school_class.study_program_id
            and self.course_subject.program_id != self.school_class.study_program_id
        ):
            raise ValidationError({
                "course_subject": (
                    "La matière « %s » ne correspond pas à la filière de la classe « %s »."
                    % (self.course_subject, self.school_class.name)
                ),
            })

    def save(self, *args, **kwargs):
        if self.school_class_id:
            self.university_id = self.school_class.university_id
        super().save(*args, **kwargs)

    @property
    def code(self):
        if self.course_subject_id:
            return self.course_subject.code
        match = re.search(r"\b([A-Z]{2,6})\s?(\d{2,4})\b", self.title or "")
        return "%s%s" % (match.group(1), match.group(2)) if match else ""

    @property
    def coefficient(self):
        return self.course_subject.coefficient if self.course_subject_id else Decimal("1")

    @property
    def semester(self):
        return semester_for(self.school_class)

    @property
    def is_qcm(self):
        return self.exam_type == self.TYPE_QCM

    @property
    def is_project(self):
        return self.exam_type == self.TYPE_PROJECT

    @property
    def is_oral(self):
        return self.exam_type == self.TYPE_ORAL

    @property
    def type_label(self):
        return self.get_exam_type_display()

    @property
    def date(self):
        return timezone.localtime(self.opens_at).date()

    @property
    def start_time(self):
        return timezone.localtime(self.opens_at).time()

    @property
    def end_time(self):
        return timezone.localtime(self.closes_at).time()

    @property
    def date_label(self):
        day = self.date
        return "%s %d %s" % (
            _WEEKDAYS[day.weekday()], day.day, _MONTHS[day.month - 1],
        )

    @property
    def time_label(self):
        return "%s – %s" % (
            timezone.localtime(self.opens_at).strftime("%H:%M"),
            timezone.localtime(self.closes_at).strftime("%H:%M"),
        )

    def deposit_window(self):
        return self.opens_at, self.closes_at

    @property
    def access_status(self):
        """'before' | 'open' | 'after' — état de la fenêtre QCM."""
        now = timezone.now()
        if now < self.opens_at:
            return "before"
        if now > self.closes_at:
            return "after"
        return "open"

    @property
    def is_open(self):
        return self.access_status == "open"

    @property
    def subject_window_label(self):
        return "%s, %s" % (self.date_label, self.time_label)


class GradeRecord(models.Model):
    """Relevé officiel d'une classe pour un semestre.

    Les compteurs sont recalculés depuis les notes QCM publiées : aucune
    saisie manuelle n'est possible.
    """

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="grade_records", verbose_name="Université",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE,
        related_name="grade_records", verbose_name="Classe",
    )
    semester = models.CharField("Semestre", max_length=40)
    students_count = models.PositiveIntegerField("Étudiants inscrits", default=0)
    admitted_count = models.PositiveIntegerField("Étudiants admis", default=0)
    average = models.DecimalField("Moyenne générale", max_digits=4, decimal_places=2, default=0)
    pv_signed = models.BooleanField("PV signé", default=False)
    pv_signed_at = models.DateTimeField("PV signé le", null=True, blank=True)
    pv_signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="signed_grade_records", verbose_name="PV signé par",
    )
    transcript_published = models.BooleanField("Relevé publié", default=False)
    published_at = models.DateTimeField("Relevé publié le", null=True, blank=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("school_class__name", "semester")
        verbose_name = "Relevé de notes"
        verbose_name_plural = "Relevés de notes"
        constraints = [
            models.UniqueConstraint(
                fields=("school_class", "semester"),
                name="unique_grade_record_per_class_semester",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.school_class, self.semester)

    def clean(self):
        if (
            self.school_class_id and self.university_id
            and self.school_class.university_id != self.university_id
        ):
            raise ValidationError("La classe et le relevé doivent appartenir à la même université.")
        if self.admitted_count > self.students_count:
            raise ValidationError({"admitted_count": "Le nombre d'admis ne peut pas dépasser l'effectif."})
        if self.average < 0 or self.average > 20:
            raise ValidationError({"average": "La moyenne doit être comprise entre 0 et 20."})

    def save(self, *args, **kwargs):
        if self.school_class_id:
            self.university_id = self.school_class.university_id
        super().save(*args, **kwargs)

    @property
    def rate(self):
        if not self.students_count:
            return 0
        return round(self.admitted_count * 100 / self.students_count)

    @property
    def rate_label(self):
        if not self.students_count:
            return "—"
        return "%s %%" % self.rate

    @property
    def average_label(self):
        if not self.students_count:
            return "—"
        return ("%.1f" % self.average).replace(".", ",")

    @property
    def can_publish(self):
        return self.pv_signed and not self.transcript_published


class StudentGrade(models.Model):
    """Note officielle d'un étudiant pour une session QCM."""

    STATUS_DRAFT = "brouillon"
    STATUS_VALIDATED = "validee"
    STATUS_PUBLISHED = "publiee"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Brouillon"),
        (STATUS_VALIDATED, "Validée"),
        (STATUS_PUBLISHED, "Publiée"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="student_grades", verbose_name="Université",
    )
    session = models.ForeignKey(
        ExamSession, on_delete=models.CASCADE,
        related_name="student_grades", verbose_name="Épreuve",
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="grades", verbose_name="Étudiant",
    )
    score = models.DecimalField(
        "Note", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    max_score = models.DecimalField(
        "Barème", max_digits=4, decimal_places=2, default=20,
    )
    is_absent = models.BooleanField("Absent", default=False)
    comment = models.TextField("Commentaire global", blank=True)
    status = models.CharField(
        "Statut", max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT,
    )
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="graded_exams", verbose_name="Corrigée par",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("student__membership__user__last_name", "student__membership__user__first_name")
        verbose_name = "Note d'étudiant"
        verbose_name_plural = "Notes d'étudiants"
        constraints = [
            models.UniqueConstraint(
                fields=("session", "student"), name="unique_grade_per_session_student",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.student, self.session.title)

    def save(self, *args, **kwargs):
        if self.session_id:
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)

    def clean(self):
        if self.student_id and self.university_id and self.student.university_id != self.university_id:
            raise ValidationError("L'étudiant et l'épreuve doivent appartenir à la même université.")

    @property
    def max_total(self):
        return self.max_score

    @property
    def score_label(self):
        if self.score is None:
            return "—"
        return ("%.2f" % self.score).rstrip("0").rstrip(".").replace(".", ",")

    @property
    def is_graded(self):
        return self.score is not None

    @property
    def is_published(self):
        return self.status == self.STATUS_PUBLISHED


class Quiz(models.Model):
    """Questionnaire à choix multiple rattaché à une session.

    La fenêtre d'accès est celle de la session : plus de dates dupliquées.
    """

    STATUS_DRAFT = "brouillon"
    STATUS_PUBLISHED = "publie"
    STATUS_CLOSED = "ferme"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Brouillon"),
        (STATUS_PUBLISHED, "Publié"),
        (STATUS_CLOSED, "Fermé"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="quizzes", verbose_name="Université",
    )
    session = models.OneToOneField(
        ExamSession, on_delete=models.CASCADE,
        related_name="quiz", verbose_name="Épreuve",
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quizzes", verbose_name="Cours source",
    )
    instructions = models.TextField(
        "Consignes", blank=True,
        help_text="Affichées à l'étudiant avant le démarrage du QCM.",
    )
    duration_minutes = models.PositiveSmallIntegerField(
        "Durée (minutes)", default=60,
    )
    question_count = models.PositiveSmallIntegerField(
        "Nombre de questions", default=0,
    )
    pass_score = models.DecimalField(
        "Note de validation", max_digits=4, decimal_places=2, default=10,
        help_text="Seuil de réussite sur 20.",
    )
    shuffle_questions = models.BooleanField(
        "Mélanger les questions", default=True,
    )
    status = models.CharField(
        "Statut", max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT,
    )
    generated_by_ai = models.BooleanField("Généré par IA", default=False)
    ai_model = models.CharField("Modèle IA", max_length=80, blank=True)
    source_chars = models.PositiveIntegerField("Caractères analysés", default=0)
    ai_analysis = models.JSONField("Analyse IA", default=dict, blank=True)
    ai_analysis_at = models.DateTimeField("Analysé le", null=True, blank=True)
    published_at = models.DateTimeField("Publié le", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_quizzes", verbose_name="Créé par",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("session__opens_at",)
        verbose_name = "QCM"
        verbose_name_plural = "QCM"

    def __str__(self):
        return "QCM — %s" % self.session.title

    def clean(self):
        if (
            self.course_id and self.university_id
            and self.course.university_id != self.university_id
        ):
            raise ValidationError("Le cours et le QCM doivent appartenir à la même université.")

    def save(self, *args, **kwargs):
        if self.session_id:
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)

    def window(self):
        return self.session.deposit_window()

    @property
    def starts_at(self):
        return self.window()[0]

    @property
    def ends_at(self):
        return self.window()[1]

    @property
    def access_status(self):
        """'draft' | 'closed' | 'before' | 'open' | 'after'."""
        if self.status == self.STATUS_DRAFT:
            return "draft"
        if self.status == self.STATUS_CLOSED:
            return "closed"
        opens_at, closes_at = self.window()
        now = timezone.now()
        if now < opens_at:
            return "before"
        if now > closes_at:
            return "after"
        return "open"

    @property
    def is_published(self):
        return self.status == self.STATUS_PUBLISHED

    @property
    def is_open(self):
        return self.access_status == "open"

    @property
    def question_total(self):
        return self.questions.count()

    @property
    def total_points(self):
        return self.questions.aggregate(
            total=models.Sum("points"),
        )["total"] or Decimal("0")

    @property
    def status_label(self):
        return {
            "draft": "Brouillon",
            "closed": "Fermé",
            "before": "Ouverture programmée",
            "open": "Ouvert",
            "after": "Terminé",
        }.get(self.access_status, "Brouillon")


class QuizQuestion(models.Model):
    """Question d'un QCM ; une seule bonne réponse parmi les choix."""

    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name="questions", verbose_name="QCM",
    )
    order = models.PositiveIntegerField("Ordre", default=0)
    prompt = models.TextField("Énoncé")
    explanation = models.TextField(
        "Explication", blank=True,
        help_text="Affichée à l'étudiant après la soumission.",
    )
    points = models.DecimalField(
        "Points", max_digits=4, decimal_places=2, default=1,
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("order", "pk")
        verbose_name = "Question de QCM"
        verbose_name_plural = "Questions de QCM"

    def __str__(self):
        return "Q%d — %s" % (self.order, self.prompt[:60])

    @property
    def correct_choices(self):
        return self.choices.filter(is_correct=True)

    def is_correct_choice(self, choice_id):
        return self.choices.filter(pk=choice_id, is_correct=True).exists()


class QuizChoice(models.Model):
    """Proposition de réponse d'une question."""

    question = models.ForeignKey(
        QuizQuestion, on_delete=models.CASCADE,
        related_name="choices", verbose_name="Question",
    )
    order = models.PositiveIntegerField("Ordre", default=0)
    label = models.TextField("Libellé")
    is_correct = models.BooleanField("Bonne réponse", default=False)

    class Meta:
        ordering = ("order", "pk")
        verbose_name = "Choix de QCM"
        verbose_name_plural = "Choix de QCM"

    def __str__(self):
        return self.label[:80]


class QuizAttempt(models.Model):
    """Tentative unique d'un étudiant pour un QCM."""

    STATUS_IN_PROGRESS = "en_cours"
    STATUS_SUBMITTED = "soumise"
    STATUS_EXPIRED = "expiree"
    STATUS_CHOICES = (
        (STATUS_IN_PROGRESS, "En cours"),
        (STATUS_SUBMITTED, "Soumise"),
        (STATUS_EXPIRED, "Expirée"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="quiz_attempts", verbose_name="Université",
    )
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name="attempts", verbose_name="QCM",
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="quiz_attempts", verbose_name="Étudiant",
    )
    started_at = models.DateTimeField("Démarrée le", default=timezone.now)
    deadline_at = models.DateTimeField("Échéance")
    question_order = models.JSONField(
        "Ordre des questions", default=list, blank=True,
        help_text="Ordre figé au démarrage pour cette tentative.",
    )
    submitted_at = models.DateTimeField("Soumise le", null=True, blank=True)
    score = models.DecimalField(
        "Note", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    max_score = models.DecimalField(
        "Barème", max_digits=6, decimal_places=2, default=0,
    )
    status = models.CharField(
        "Statut", max_length=20, choices=STATUS_CHOICES,
        default=STATUS_IN_PROGRESS,
    )
    ai_feedback = models.JSONField("Feedback IA", default=dict, blank=True)
    ai_feedback_at = models.DateTimeField("Feedback généré le", null=True, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("-started_at",)
        verbose_name = "Tentative de QCM"
        verbose_name_plural = "Tentatives de QCM"
        constraints = [
            models.UniqueConstraint(
                fields=("quiz", "student"),
                name="unique_quiz_attempt_per_student",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.student, self.quiz)

    def save(self, *args, **kwargs):
        if self.quiz_id:
            self.university_id = self.quiz.university_id
        super().save(*args, **kwargs)

    @property
    def is_submitted(self):
        return self.submitted_at is not None

    @property
    def is_absent(self):
        return self.status == self.STATUS_EXPIRED

    @property
    def is_expired(self):
        return not self.is_submitted and timezone.now() >= self.deadline_at

    def remaining_seconds(self, now=None):
        now = now or timezone.now()
        return max(0, int((self.deadline_at - now).total_seconds()))

    @property
    def score_20(self):
        if self.score is None or not self.max_score:
            return None
        return (self.score * Decimal("20") / self.max_score).quantize(Decimal("0.01"))

    @property
    def passed(self):
        value = self.score_20
        return value is not None and value >= self.quiz.pass_score


class QuizAnswer(models.Model):
    """Réponse d'un étudiant à une question, dans le cadre d'une tentative."""

    attempt = models.ForeignKey(
        QuizAttempt, on_delete=models.CASCADE,
        related_name="answers", verbose_name="Tentative",
    )
    question = models.ForeignKey(
        QuizQuestion, on_delete=models.CASCADE,
        related_name="answers", verbose_name="Question",
    )
    selected_choice = models.ForeignKey(
        QuizChoice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="answers", verbose_name="Réponse choisie",
    )
    answered_at = models.DateTimeField("Répondue le", auto_now=True)

    class Meta:
        ordering = ("question__order",)
        verbose_name = "Réponse de QCM"
        verbose_name_plural = "Réponses de QCM"
        constraints = [
            models.UniqueConstraint(
                fields=("attempt", "question"),
                name="unique_answer_per_attempt_question",
            ),
        ]

    def __str__(self):
        return "%s — Q%s" % (self.attempt.student, self.question.order)

    @property
    def is_correct(self):
        return bool(
            self.selected_choice_id
            and self.selected_choice
            and self.selected_choice.is_correct
        )

class ProjectCriterion(models.Model):
    """Critère d'évaluation d'un projet, pondéré pour le calcul de la note."""

    session = models.ForeignKey(
        ExamSession, on_delete=models.CASCADE,
        related_name="project_criteria", verbose_name="Session",
    )
    label = models.CharField("Critère", max_length=180)
    description = models.TextField("Attendu", blank=True)
    weight = models.PositiveSmallIntegerField("Poids", default=1)
    order = models.PositiveIntegerField("Ordre", default=0)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ("order", "pk")
        verbose_name = "Critère de projet"
        verbose_name_plural = "Critères de projet"

    def __str__(self):
        return self.label

    def save(self, *args, **kwargs):
        self.label = (self.label or "").strip()
        if self._state.adding and not self.order and self.session_id:
            last = ProjectCriterion.objects.filter(
                session_id=self.session_id,
            ).aggregate(last=models.Max("order"))["last"]
            self.order = (last or 0) + 1
        super().save(*args, **kwargs)

    @classmethod
    def ensure_defaults(cls, session):
        """Crée une grille de départ si le professeur n'a encore rien défini."""
        if session.project_criteria.exists():
            return session.project_criteria.all()
        defaults = (
            ("Respect du cahier des charges", "Fonctionnalités demandées et contraintes respectées.", 3),
            ("Qualité technique", "Code, structure, robustesse et bonnes pratiques.", 3),
            ("Documentation", "README, commentaires et facilité de prise en main.", 2),
            ("Présentation et lisibilité", "Organisation des fichiers et clarté de la livraison.", 2),
        )
        for order, (label, description, weight) in enumerate(defaults, start=1):
            cls.objects.create(
                session=session, label=label, description=description,
                weight=weight, order=order,
            )
        return session.project_criteria.all()


class ProjectSubmission(models.Model):
    """Dépôt ZIP d'un étudiant pour une session de type projet."""

    STATUS_SUBMITTED = "depose"
    STATUS_AI_EVALUATED = "ia"
    STATUS_MANUAL_REQUIRED = "manuel"
    STATUS_GRADED = "note"
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, "Déposé"),
        (STATUS_AI_EVALUATED, "Évalué par IA"),
        (STATUS_MANUAL_REQUIRED, "Notation manuelle requise"),
        (STATUS_GRADED, "Noté"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="project_submissions", verbose_name="Université",
    )
    session = models.ForeignKey(
        ExamSession, on_delete=models.CASCADE,
        related_name="project_submissions", verbose_name="Session",
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="project_submissions", verbose_name="Étudiant",
    )
    file = models.FileField(
        "Archive ZIP", storage=ProtectedMediaStorage(),
        upload_to=project_upload_path, max_length=255,
    )
    original_name = models.CharField("Nom d'origine", max_length=255, blank=True)
    size = models.PositiveBigIntegerField("Taille (octets)", default=0)
    submitted_at = models.DateTimeField("Déposé le", default=timezone.now)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)
    status = models.CharField(
        "Statut", max_length=20, choices=STATUS_CHOICES, default=STATUS_SUBMITTED,
    )
    ai_result = models.JSONField("Évaluation IA", default=dict, blank=True)
    ai_score = models.DecimalField(
        "Note IA /20", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    ai_model = models.CharField("Modèle IA", max_length=80, blank=True)
    ai_evaluated_at = models.DateTimeField("Évalué par IA le", null=True, blank=True)
    final_score = models.DecimalField(
        "Note finale /20", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    feedback = models.TextField("Commentaire du professeur", blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="graded_project_submissions", verbose_name="Noté par",
    )
    graded_at = models.DateTimeField("Noté le", null=True, blank=True)

    class Meta:
        ordering = ("student__membership__user__last_name", "student__membership__user__first_name")
        verbose_name = "Dépôt de projet"
        verbose_name_plural = "Dépôts de projet"
        constraints = [
            models.UniqueConstraint(
                fields=("session", "student"), name="unique_project_submission_per_student",
            ),
        ]

    def __str__(self):
        return "%s - %s" % (self.student, self.session.title)

    def save(self, *args, **kwargs):
        if self.session_id:
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)

    @property
    def is_graded(self):
        return self.final_score is not None

    @property
    def score_label(self):
        value = self.final_score if self.final_score is not None else self.ai_score
        if value is None:
            return "-"
        return ("%.2f" % value).rstrip("0").rstrip(".").replace(".", ",")

    @property
    def status_label(self):
        return self.get_status_display()


class OralTopic(models.Model):
    """Sujet tiré au sort par un étudiant lors d'un examen oral."""

    session = models.ForeignKey(
        ExamSession, on_delete=models.CASCADE,
        related_name="oral_topics", verbose_name="Session",
    )
    title = models.CharField("Sujet", max_length=200)
    instructions = models.TextField("Consignes", blank=True)
    duration_minutes = models.PositiveSmallIntegerField("Préparation (minutes)", default=10)
    order = models.PositiveIntegerField("Ordre", default=0)
    is_active = models.BooleanField("Actif", default=True)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ("order", "pk")
        verbose_name = "Sujet d'oral"
        verbose_name_plural = "Sujets d'oral"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        if self._state.adding and not self.order and self.session_id:
            last = OralTopic.objects.filter(
                session_id=self.session_id,
            ).aggregate(last=models.Max("order"))["last"]
            self.order = (last or 0) + 1
        super().save(*args, **kwargs)

    @classmethod
    def ensure_defaults(cls, session):
        if session.oral_topics.exists():
            return session.oral_topics.all()
        subject = session.course_subject.name if session.course_subject_id else session.title
        for index, letter in enumerate("ABC", start=1):
            cls.objects.create(
                session=session, order=index,
                title="Sujet %s - %s" % (letter, subject),
                instructions=(
                    "Préparez une présentation de 10 minutes sur ce sujet, "
                    "puis répondez aux questions du jury."
                ),
            )
        return session.oral_topics.all()


class OralAttempt(models.Model):
    """Tirage et notation d'un étudiant pour un examen oral."""

    STATUS_DRAWN = "tire"
    STATUS_GRADED = "note"
    STATUS_ABSENT = "absent"
    STATUS_CHOICES = (
        (STATUS_DRAWN, "Sujet tiré"),
        (STATUS_GRADED, "Noté"),
        (STATUS_ABSENT, "Absent"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="oral_attempts", verbose_name="Université",
    )
    session = models.ForeignKey(
        ExamSession, on_delete=models.CASCADE,
        related_name="oral_attempts", verbose_name="Session",
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="oral_attempts", verbose_name="Étudiant",
    )
    topic = models.ForeignKey(
        OralTopic, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attempts", verbose_name="Sujet",
    )
    drawn_at = models.DateTimeField("Tiré le", default=timezone.now)
    preparation_deadline = models.DateTimeField("Fin de préparation", null=True, blank=True)
    notes = models.TextField("Notes du professeur", blank=True)
    score = models.DecimalField(
        "Note /20", max_digits=4, decimal_places=2, null=True, blank=True,
    )
    feedback = models.TextField("Commentaire", blank=True)
    status = models.CharField(
        "Statut", max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAWN,
    )
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="graded_oral_attempts", verbose_name="Noté par",
    )
    graded_at = models.DateTimeField("Noté le", null=True, blank=True)

    class Meta:
        ordering = ("-drawn_at",)
        verbose_name = "Passage oral"
        verbose_name_plural = "Passages oraux"
        constraints = [
            models.UniqueConstraint(
                fields=("session", "student"), name="unique_oral_attempt_per_student",
            ),
        ]

    def __str__(self):
        return "%s - %s" % (self.student, self.session.title)

    def save(self, *args, **kwargs):
        if self.session_id:
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)

    @property
    def is_graded(self):
        return self.score is not None

    @property
    def score_label(self):
        if self.score is None:
            return "-"
        return ("%.2f" % self.score).rstrip("0").rstrip(".").replace(".", ",")

    @property
    def status_label(self):
        return self.get_status_display()
