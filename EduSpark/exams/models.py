import re
import uuid
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import ProfessorProfile, SchoolClass, StudentProfile, University

DEFAULT_ACADEMIC_YEAR = "2025-2026"

_WEEKDAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def semester_for(school_class):
    """Libellé du semestre courant pour une classe."""
    return "Semestre 1 · %s" % (school_class.academic_year or DEFAULT_ACADEMIC_YEAR)


class ExamSession(models.Model):
    """Épreuve planifiée pour une classe d'une université."""

    TYPE_ECRIT = "ecrit"
    TYPE_ORAL = "oral"
    TYPE_PROJET = "projet"
    TYPE_CHOICES = (
        (TYPE_ECRIT, "Écrit"),
        (TYPE_ORAL, "Oral"),
        (TYPE_PROJET, "Projet"),
    )

    STATUS_PLANNED = "planifiee"
    STATUS_CONVOKED = "convocation"
    STATUS_CHOICES = (
        (STATUS_PLANNED, "Planifiée"),
        (STATUS_CONVOKED, "Convocation envoyée"),
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
    code = models.CharField(
        "Code UE", max_length=20, blank=True, help_text="ex. INF501",
    )
    coefficient = models.DecimalField(
        "Coefficient", max_digits=4, decimal_places=2, default=1,
    )
    semester = models.CharField(
        "Semestre", max_length=40, blank=True,
        help_text="Renseigné automatiquement d'après la classe si vide.",
    )
    exam_type = models.CharField(
        "Type", max_length=20, choices=TYPE_CHOICES, default=TYPE_ECRIT,
    )
    date = models.DateField("Date")
    start_time = models.TimeField("Début")
    end_time = models.TimeField("Fin")
    room = models.CharField("Salle", max_length=80)
    status = models.CharField(
        "Statut", max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED,
    )
    convoked_at = models.DateTimeField("Convoquée le", null=True, blank=True)
    plan_group = models.UUIDField(
        "Groupe de planification", null=True, blank=True, editable=False,
        db_index=True,
        help_text="Identifiant commun aux épreuves planifiées ensemble pour plusieurs classes.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_exam_sessions", verbose_name="Créée par",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("date", "start_time", "school_class__name")
        verbose_name = "Session d'examen"
        verbose_name_plural = "Sessions d'examen"

    def __str__(self):
        return "%s — %s (%s)" % (self.title, self.school_class, self.date)

    def clean(self):
        if (
            self.school_class_id and self.university_id
            and self.school_class.university_id != self.university_id
        ):
            raise ValidationError("La classe et la session doivent appartenir à la même université.")
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "L'heure de fin doit être postérieure à l'heure de début."})
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
        if not self.semester and self.school_class_id:
            self.semester = semester_for(self.school_class)
        if not self.code:
            match = re.search(r"\b([A-Z]{2,6})\s?(\d{2,4})\b", self.title or "")
            if match:
                self.code = "%s%s" % (match.group(1), match.group(2))
        super().save(*args, **kwargs)

    @property
    def date_label(self):
        return "%s %d %s" % (
            _WEEKDAYS[self.date.weekday()], self.date.day, _MONTHS[self.date.month - 1],
        )

    @property
    def time_label(self):
        return "%s – %s" % (
            self.start_time.strftime("%H:%M"), self.end_time.strftime("%H:%M"),
        )

    @property
    def is_convoked(self):
        return self.status == self.STATUS_CONVOKED

    def deposit_window(self):
        """Début et fin de l'épreuve en datetimes aware."""
        return (
            timezone.make_aware(datetime.combine(self.date, self.start_time)),
            timezone.make_aware(datetime.combine(self.date, self.end_time)),
        )

    @property
    def access_status(self):
        """'before' | 'open' | 'after' — accès au sujet et au dépôt.

        L'accès est strictement limité à la durée officielle de l'épreuve :
        ni avant l'heure de début, ni après l'heure de fin.
        """
        start, end = self.deposit_window()
        now = timezone.now()
        if now < start:
            return "before"
        if now > end:
            return "after"
        return "open"

    @property
    def deposit_status(self):
        """Alias d'accès au dépôt de copie (rétro-compatibilité)."""
        return self.access_status

    @property
    def deposit_open(self):
        """Le dépôt de copie est ouvert uniquement pendant la durée de l'épreuve."""
        return self.access_status == "open"

    @property
    def subject_window_label(self):
        return "%s, %s" % (self.date_label, self.time_label)


def subject_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() or "pdf"
    return "exam_subjects/%s/%s.%s" % (
        instance.session_id, uuid.uuid4().hex, ext,
    )


class ExamSubject(models.Model):
    """Sujet d'épreuve déposé puis publié par l'enseignant.

    Le sujet n'est visible des étudiants qu'une fois publié, et uniquement
    pendant la durée officielle de l'épreuve.
    """

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="exam_subjects", verbose_name="Université",
    )
    session = models.OneToOneField(
        ExamSession, on_delete=models.CASCADE,
        related_name="subject", verbose_name="Épreuve",
    )
    file = models.FileField("Fichier PDF", upload_to=subject_upload_path)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="uploaded_exam_subjects", verbose_name="Déposé par",
    )
    published_at = models.DateTimeField("Publié le", null=True, blank=True)
    created_at = models.DateTimeField("Déposé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        verbose_name = "Sujet d'épreuve"
        verbose_name_plural = "Sujets d'épreuve"

    def __str__(self):
        return "Sujet — %s" % self.session

    def save(self, *args, **kwargs):
        if self.session_id:
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)

    @property
    def is_published(self):
        return self.published_at is not None

    @property
    def availability_status(self):
        """'draft' | 'before' | 'open' | 'after' — visibilité du sujet."""
        if not self.is_published:
            return "draft"
        return self.session.access_status

    @property
    def is_available(self):
        """Le sujet n'est téléchargeable que pendant la durée de l'épreuve."""
        return self.availability_status == "open"

    @property
    def file_name(self):
        return self.file.name.rsplit("/", 1)[-1] if self.file else ""


class GradeRecord(models.Model):
    """Relevé officiel d'une classe pour un semestre.

    Les valeurs du PV (effectif, admis, moyenne) alimentent les statistiques
    de l'établissement et sont modifiables depuis la fiche du relevé.
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


DEFAULT_CRITERIA = (
    {"label": "Architecture & Rétropropagation", "weight": 5},
    {"label": "Calcul du Gradient & Optimisation", "weight": 5},
    {"label": "Régularisation & Prévention Surapprentissage", "weight": 5},
    {"label": "Rigueur scientifique & Rédaction", "weight": 5},
)


class StudentGrade(models.Model):
    """Note individuelle d'un étudiant pour une épreuve.

    ``criteria`` conserve le détail critère par critère (libellé, barème,
    points, appréciation) tel que saisi par le correcteur. La note globale
    (``score``) est calculée à la validation.
    """

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
    criteria = models.JSONField("Critères", default=list, blank=True)
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
    def criteria_total(self):
        return sum(
            (item.get("points") or 0)
            for item in (self.criteria or [])
        )

    @property
    def max_total(self):
        return sum(
            (item.get("weight") or 0)
            for item in (self.criteria or [])
        ) or self.max_score

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


def copy_file_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() or "pdf"
    return "exam_copies/%s/%s.%s" % (
        instance.session_id, uuid.uuid4().hex, ext,
    )


class ExamCopy(models.Model):
    """Copie déposée par un étudiant pour une épreuve (PDF ou archive ZIP)."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="exam_copies", verbose_name="Université",
    )
    session = models.ForeignKey(
        ExamSession, on_delete=models.CASCADE,
        related_name="copies", verbose_name="Épreuve",
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="exam_copies", verbose_name="Étudiant",
    )
    file = models.FileField(
        "Copie (PDF/ZIP)", upload_to=copy_file_upload_path, blank=True,
    )
    original_name = models.CharField("Nom d'origine", max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField("Taille (octets)", default=0)
    submitted_at = models.DateTimeField("Soumise le", null=True, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("student__membership__user__last_name", "student__membership__user__first_name")
        verbose_name = "Copie d'examen"
        verbose_name_plural = "Copies d'examen"
        constraints = [
            models.UniqueConstraint(
                fields=("session", "student"), name="unique_copy_per_session_student",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.student, self.session.title)

    def save(self, *args, **kwargs):
        if self.session_id:
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)

    @property
    def is_submitted(self):
        return self.submitted_at is not None

    @property
    def page_count(self):
        return self.pages.count()

    @property
    def has_file(self):
        return bool(self.file)

    @property
    def has_content(self):
        """Une copie contient soit un fichier PDF/ZIP, soit des pages scannées."""
        return self.has_file or self.page_count > 0

    @property
    def file_extension(self):
        name = (self.original_name or self.file.name or "").lower()
        return name.rsplit(".", 1)[-1] if "." in name else ""

    @property
    def is_pdf(self):
        return self.file_extension == "pdf"

    @property
    def is_zip(self):
        return self.file_extension == "zip"


def copy_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() or "png"
    return "exam_copies/%s/%s.%s" % (
        instance.copy_id, uuid.uuid4().hex, ext,
    )


class ExamCopyPage(models.Model):
    """Page numérisée d'une copie d'examen."""

    copy = models.ForeignKey(
        ExamCopy, on_delete=models.CASCADE, related_name="pages", verbose_name="Copie",
    )
    file = models.ImageField("Fichier", upload_to=copy_upload_path)
    uploaded_at = models.DateTimeField("Téléversée le", auto_now_add=True)

    class Meta:
        ordering = ("pk",)
        verbose_name = "Page de copie"
        verbose_name_plural = "Pages de copie"

    def __str__(self):
        return "Page de %s" % self.copy


class JuryMember(models.Model):
    """Membre du jury d'un relevé de notes d'une classe."""

    ROLE_PRESIDENT = "president"
    ROLE_EXAMINER = "examinateur"
    ROLE_CHOICES = (
        (ROLE_PRESIDENT, "Présidence du jury"),
        (ROLE_EXAMINER, "Examinateur"),
    )

    STATUS_INVITED = "invite"
    STATUS_CONFIRMED = "confirme"
    STATUS_CHOICES = (
        (STATUS_INVITED, "Invité"),
        (STATUS_CONFIRMED, "Confirmé"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="jury_members", verbose_name="Université",
    )
    grade_record = models.ForeignKey(
        GradeRecord, on_delete=models.CASCADE,
        related_name="jury_members", verbose_name="Relevé",
    )
    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.CASCADE,
        related_name="jury_memberships", verbose_name="Enseignant",
    )
    role_label = models.CharField(
        "Rôle au jury", max_length=20, choices=ROLE_CHOICES, default=ROLE_EXAMINER,
    )
    status = models.CharField(
        "Statut", max_length=20, choices=STATUS_CHOICES, default=STATUS_INVITED,
    )
    invited_at = models.DateTimeField("Invité le", auto_now_add=True)
    confirmed_at = models.DateTimeField("Confirmé le", null=True, blank=True)

    class Meta:
        ordering = ("role_label", "professor__membership__user__last_name")
        verbose_name = "Membre de jury"
        verbose_name_plural = "Membres de jury"
        constraints = [
            models.UniqueConstraint(
                fields=("grade_record", "professor"),
                name="unique_jury_member_per_record_professor",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.professor, self.grade_record.school_class)

    def save(self, *args, **kwargs):
        if self.grade_record_id:
            self.university_id = self.grade_record.university_id
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# QCM générés par IA
# ---------------------------------------------------------------------------

class Quiz(models.Model):
    """Questionnaire à choix multiple rattaché à une épreuve.

    Le QCM est généré depuis le contenu du cours puis relu par l'enseignant.
    Il n'est accessible aux étudiants que lorsqu'il est publié et que la
    fenêtre d'ouverture est active.
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
        "Nombre de questions", default=30,
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
    opens_at = models.DateTimeField(
        "Ouverture", null=True, blank=True,
        help_text="Laisser vide pour utiliser l'horaire de l'épreuve.",
    )
    closes_at = models.DateTimeField(
        "Fermeture", null=True, blank=True,
        help_text="Laisser vide pour utiliser l'horaire de l'épreuve.",
    )
    generated_by_ai = models.BooleanField("Généré par IA", default=False)
    ai_model = models.CharField("Modèle IA", max_length=80, blank=True)
    source_chars = models.PositiveIntegerField(
        "Caractères analysés", default=0,
    )
    published_at = models.DateTimeField("Publié le", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_quizzes", verbose_name="Créé par",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("session__date", "session__start_time")
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
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise ValidationError({
                "closes_at": "La fermeture doit être postérieure à l'ouverture.",
            })

    def save(self, *args, **kwargs):
        if self.session_id:
            self.university_id = self.session.university_id
        super().save(*args, **kwargs)

    def window(self):
        """Bornes d'ouverture du QCM, avec repli sur l'horaire de l'épreuve."""
        start, end = self.session.deposit_window()
        return (self.opens_at or start, self.closes_at or end)

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
