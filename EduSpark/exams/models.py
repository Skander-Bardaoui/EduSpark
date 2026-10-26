import re
import uuid
from datetime import datetime

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
    def deposit_status(self):
        """'convocation' | 'before' | 'open' | 'after' — état du dépôt de copie."""
        if not self.is_convoked:
            return "convocation"
        start, end = self.deposit_window()
        now = timezone.now()
        if now < start:
            return "before"
        if now > end:
            return "after"
        return "open"

    @property
    def deposit_open(self):
        """Le dépôt de copie est ouvert uniquement pendant la durée de l'épreuve."""
        return self.deposit_status == "open"


def subject_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() or "pdf"
    return "exam_subjects/%s/%s.%s" % (
        instance.session_id, uuid.uuid4().hex, ext,
    )


class ExamSubject(models.Model):
    """Sujet d'épreuve déposé puis publié par l'enseignant.

    Le sujet n'est visible des étudiants qu'une fois publié, et reste
    remplaçable tant que la session n'est pas convoquée.
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


class ExamCopy(models.Model):
    """Copie numérisée déposée par un étudiant pour une épreuve."""

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
