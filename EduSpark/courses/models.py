"""Catalogue pédagogique, affectations, emploi du temps et contenus de cours.

Chaîne fonctionnelle :

* l'admin de l'université crée les départements, filières et matières, affecte
  un professeur à chaque matière d'une classe (``TeachingAssignment``) et
  planifie l'emploi du temps de la classe (``ScheduleSlot``) ;
* le professeur crée ses cours (``Course``), leurs chapitres et supports, puis
  publie chaque cours pour chacune de ses classes (``CoursePublication``) ;
* l'étudiant voit l'emploi du temps de sa classe et les cours publiés pour elle.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Max
from django.db.models.functions import Lower

from accounts.models import ProfessorProfile, SchoolClass, StudentGroup, University

from . import files
from .storage import ProtectedMediaStorage


def display_name(user):
    """Nom complet d'un compte, à défaut son e-mail."""
    return (user.get_full_name() or "").strip() or user.email or user.username


def _same_university(errors, field, related, university_id, message):
    """Ajoute une erreur si ``related`` n'appartient pas à l'université attendue."""
    if related is not None and university_id and related.university_id != university_id:
        errors[field] = message


# ---------------------------------------------------------------------------
# Catalogue : départements, filières, matières
# ---------------------------------------------------------------------------

class Department(models.Model):
    """Département d'une université : regroupe des filières."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="departments", verbose_name="Université",
    )
    name = models.CharField("Nom", max_length=150)
    code = models.CharField("Code", max_length=20, blank=True, help_text="ex. INFO")
    description = models.TextField("Description", blank=True)
    head = models.ForeignKey(
        ProfessorProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="headed_departments", verbose_name="Chef de département",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Département"
        verbose_name_plural = "Départements"
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "university", name="unique_department_name_per_university",
                violation_error_message="Un département porte déjà ce nom dans l'université.",
            ),
            models.UniqueConstraint(
                fields=("university", "code"), condition=~models.Q(code=""),
                name="unique_department_code_per_university",
                violation_error_message="Un département utilise déjà ce code dans l'université.",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        _same_university(
            errors, "head", self.head if self.head_id else None, self.university_id,
            "Le chef de département doit appartenir à la même université.",
        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)


class Program(models.Model):
    """Filière (licence, master, cycle ingénieur…) d'un département."""

    DEGREE_CHOICES = (
        ("licence", "Licence"),
        ("master", "Master"),
        ("ingenieur", "Cycle ingénieur"),
        ("doctorat", "Doctorat"),
        ("autre", "Autre"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="programs", verbose_name="Université",
    )
    department = models.ForeignKey(
        Department, on_delete=models.RESTRICT,
        related_name="programs", verbose_name="Département",
    )
    name = models.CharField("Nom", max_length=150)
    code = models.CharField("Code", max_length=20, blank=True, help_text="ex. LIC-INFO")
    degree = models.CharField("Diplôme", max_length=20, choices=DEGREE_CHOICES, default="licence")
    duration_years = models.PositiveSmallIntegerField(
        "Durée (années)", default=3,
        validators=[MinValueValidator(1), MaxValueValidator(8)],
        help_text="Une année compte deux semestres.",
    )
    description = models.TextField("Description", blank=True)
    coordinator = models.ForeignKey(
        ProfessorProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="coordinated_programs", verbose_name="Responsable de filière",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("department__name", "name")
        verbose_name = "Filière"
        verbose_name_plural = "Filières"
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "university", name="unique_program_name_per_university",
                violation_error_message="Une filière porte déjà ce nom dans l'université.",
            ),
            models.UniqueConstraint(
                fields=("university", "code"), condition=~models.Q(code=""),
                name="unique_program_code_per_university",
                violation_error_message="Une filière utilise déjà ce code dans l'université.",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def semester_count(self):
        return self.duration_years * 2

    def clean(self):
        errors = {}
        university_id = self.department.university_id if self.department_id else self.university_id
        _same_university(
            errors, "coordinator", self.coordinator if self.coordinator_id else None,
            university_id, "Le responsable doit appartenir à la même université.",
        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.department_id:
            self.university_id = self.department.university_id
        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)
        # Le libellé texte de la filière, conservé sur les classes, suit le nom.
        self.school_classes.exclude(program=self.name).update(program=self.name)


class Subject(models.Model):
    """Matière (unité d'enseignement) d'une filière."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="subjects", verbose_name="Université",
    )
    program = models.ForeignKey(
        Program, on_delete=models.RESTRICT,
        related_name="subjects", verbose_name="Filière",
    )
    name = models.CharField("Intitulé", max_length=150)
    code = models.CharField("Code", max_length=20, help_text="ex. INF501")
    semester = models.PositiveSmallIntegerField(
        "Semestre", default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Numéro du semestre dans la filière (S1 à S10).",
    )
    coefficient = models.DecimalField(
        "Coefficient", max_digits=4, decimal_places=2, default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    credits = models.PositiveSmallIntegerField(
        "Crédits ECTS", default=3, validators=[MaxValueValidator(60)],
    )
    hours_cm = models.PositiveSmallIntegerField(
        "Heures de CM", default=0, validators=[MaxValueValidator(500)],
    )
    hours_td = models.PositiveSmallIntegerField(
        "Heures de TD", default=0, validators=[MaxValueValidator(500)],
    )
    hours_tp = models.PositiveSmallIntegerField(
        "Heures de TP", default=0, validators=[MaxValueValidator(500)],
    )
    description = models.TextField("Description", blank=True)
    is_active = models.BooleanField(
        "Active", default=True,
        help_text="Une matière archivée n'est plus proposée pour de nouvelles affectations.",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("program__name", "semester", "name")
        verbose_name = "Matière"
        verbose_name_plural = "Matières"
        constraints = [
            models.UniqueConstraint(
                fields=("university", "code"), name="unique_subject_code_per_university",
                violation_error_message="Une matière utilise déjà ce code dans l'université.",
            ),
            models.UniqueConstraint(
                Lower("name"), "program", name="unique_subject_name_per_program",
                violation_error_message="Cette filière a déjà une matière portant cet intitulé.",
            ),
        ]

    def __str__(self):
        return "%s · %s" % (self.code, self.name)

    @property
    def total_hours(self):
        return self.hours_cm + self.hours_td + self.hours_tp

    @property
    def semester_label(self):
        return "S%d" % self.semester

    def clean(self):
        errors = {}
        if self.program_id:
            if self.university_id and self.program.university_id != self.university_id:
                errors["program"] = "La filière doit appartenir à la même université."
            elif self.semester and self.semester > self.program.semester_count:
                errors["semester"] = (
                    "La filière « %s » compte %d semestres (S1 à S%d)."
                    % (self.program.name, self.program.semester_count, self.program.semester_count)
                )
            elif self.pk and self.teaching_assignments.exclude(
                school_class__study_program__isnull=True,
            ).exclude(school_class__study_program_id=self.program_id).exists():
                # Une affectation relie une classe et une matière de la même filière.
                errors["program"] = (
                    "Cette matière est affectée à des classes d'une autre filière : "
                    "retirez d'abord ces affectations avant de la changer de filière."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.program_id:
            self.university_id = self.program.university_id
        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Affectations et emploi du temps
# ---------------------------------------------------------------------------

class TeachingAssignment(models.Model):
    """Un professeur enseigne une matière à une classe.

    C'est le lien qui rend l'emploi du temps cohérent : une séance ne peut
    être planifiée que pour une affectation existante, et un professeur ne
    publie un cours que pour les classes auxquelles il enseigne la matière.
    """

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="teaching_assignments", verbose_name="Université",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE,
        related_name="teaching_assignments", verbose_name="Classe",
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.RESTRICT,
        related_name="teaching_assignments", verbose_name="Matière",
    )
    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.CASCADE,
        related_name="teaching_assignments", verbose_name="Professeur",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("school_class__name", "subject__semester", "subject__name")
        verbose_name = "Affectation d'enseignement"
        verbose_name_plural = "Affectations d'enseignement"
        constraints = [
            models.UniqueConstraint(
                fields=("school_class", "subject", "professor"),
                name="unique_assignment_per_class_subject_professor",
                violation_error_message="Ce professeur est déjà affecté à cette matière pour cette classe.",
            ),
        ]

    def __str__(self):
        return "%s — %s — %s" % (self.school_class.name, self.subject, self.professor_name)

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._original_key = (instance.school_class_id, instance.subject_id, instance.professor_id)
        return instance

    @property
    def professor_name(self):
        return display_name(self.professor.user)

    def clean(self):
        errors = {}
        if self.school_class_id and self.subject_id:
            university_id = self.school_class.university_id
            _same_university(
                errors, "subject", self.subject, university_id,
                "La matière doit appartenir à la même université que la classe.",
            )
            program_id = self.school_class.study_program_id
            if "subject" not in errors and program_id and self.subject.program_id != program_id:
                errors["subject"] = (
                    "Cette matière appartient à la filière « %s » alors que la classe suit « %s »."
                    % (self.subject.program.name, self.school_class.study_program.name)
                )
            if self.professor_id:
                _same_university(
                    errors, "professor", self.professor, university_id,
                    "Le professeur doit appartenir à la même université que la classe.",
                )
        if not errors:
            busy = self._professor_conflict()
            if busy:
                errors["professor"] = busy
        if errors:
            raise ValidationError(errors)

    def _professor_conflict(self):
        """Message si le nouveau professeur est déjà pris sur une séance de cette affectation.

        Les séances déjà planifiées sont transférées avec l'affectation : le professeur
        remplaçant doit être libre sur ces créneaux.
        """
        original = getattr(self, "_original_key", None)
        if self.pk is None or original is None or original[2] == self.professor_id:
            return ""
        for slot in self.slots.select_related(
            "assignment__school_class", "assignment__subject", "group",
        ):
            slot.assignment = self  # évalue la séance avec le professeur en cours de saisie
            for reasons, other in slot.find_conflicts():
                if CONFLICT_PROFESSOR in reasons:
                    return "Ce professeur est déjà occupé sur un créneau de cette matière (%s) : %s." % (
                        slot.describe(), other.describe(),
                    )
        return ""

    def save(self, *args, **kwargs):
        if self.school_class_id:
            self.university_id = self.school_class.university_id
        with transaction.atomic():
            super().save(*args, **kwargs)
            # Le professeur rejoint l'encadrement de la classe (ajout seulement).
            self.school_class.professors.add(self.professor)
            original = getattr(self, "_original_key", None)
            current = (self.school_class_id, self.subject_id, self.professor_id)
            if original is not None and original != current:
                purge_publications(*original)
            self._original_key = current


def purge_publications(school_class_id, subject_id, professor_id):
    """Retire les publications de cours qui reposaient sur une affectation disparue."""
    CoursePublication.objects.filter(
        school_class_id=school_class_id,
        course__subject_id=subject_id,
        course__professor_id=professor_id,
    ).delete()


CONFLICT_CLASS = "classe"
CONFLICT_PROFESSOR = "professeur"
CONFLICT_ROOM = "salle"

CONFLICT_MESSAGES = {
    CONFLICT_CLASS: "La classe a déjà une séance sur ce créneau",
    CONFLICT_PROFESSOR: "Le professeur est déjà occupé sur ce créneau",
    CONFLICT_ROOM: "La salle est déjà occupée sur ce créneau",
}


class ScheduleSlot(models.Model):
    """Séance hebdomadaire récurrente de l'emploi du temps d'une classe."""

    SESSION_CM = "cm"
    SESSION_TD = "td"
    SESSION_TP = "tp"
    SESSION_CHOICES = (
        (SESSION_CM, "Cours magistral (CM)"),
        (SESSION_TD, "Travaux dirigés (TD)"),
        (SESSION_TP, "Travaux pratiques (TP)"),
    )
    SESSION_LABELS = {SESSION_CM: "CM", SESSION_TD: "TD", SESSION_TP: "TP"}

    WEEKDAY_CHOICES = (
        (0, "Lundi"), (1, "Mardi"), (2, "Mercredi"),
        (3, "Jeudi"), (4, "Vendredi"), (5, "Samedi"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="schedule_slots", verbose_name="Université",
    )
    assignment = models.ForeignKey(
        TeachingAssignment, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Affectation",
    )
    group = models.ForeignKey(
        StudentGroup, on_delete=models.CASCADE, null=True, blank=True,
        related_name="schedule_slots", verbose_name="Groupe",
        help_text="Laissez vide pour une séance suivie par toute la classe.",
    )
    session_type = models.CharField(
        "Type de séance", max_length=2, choices=SESSION_CHOICES, default=SESSION_CM,
    )
    weekday = models.PositiveSmallIntegerField("Jour", choices=WEEKDAY_CHOICES)
    start_time = models.TimeField("Début")
    end_time = models.TimeField("Fin")
    room = models.CharField("Salle", max_length=80, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("weekday", "start_time", "pk")
        verbose_name = "Séance"
        verbose_name_plural = "Séances"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="schedule_slot_end_after_start",
                violation_error_message="L'heure de fin doit être postérieure à l'heure de début.",
            ),
        ]

    def __str__(self):
        return "%s · %s · %s" % (self.describe(), self.assignment.school_class.name, self.assignment.professor_name)

    # -- raccourcis ---------------------------------------------------------
    @property
    def school_class(self):
        return self.assignment.school_class

    @property
    def subject(self):
        return self.assignment.subject

    @property
    def professor(self):
        return self.assignment.professor

    @property
    def type_label(self):
        return self.SESSION_LABELS.get(self.session_type, self.session_type.upper())

    @property
    def time_label(self):
        return "%s – %s" % (self.start_time.strftime("%H:%M"), self.end_time.strftime("%H:%M"))

    @property
    def duration_minutes(self):
        return (
            (self.end_time.hour * 60 + self.end_time.minute)
            - (self.start_time.hour * 60 + self.start_time.minute)
        )

    def describe(self):
        """Résumé court pour les messages (jour, horaire, matière)."""
        return "%s %s · %s" % (self.get_weekday_display(), self.time_label, self.assignment.subject.code)

    # -- validation ---------------------------------------------------------
    def _same_audience(self, other):
        """Deux séances de la même classe se gênent-elles pour au moins un étudiant ?"""
        if not self.group_id or not other.group_id:
            return True  # au moins l'une concerne toute la classe
        if self.group_id == other.group_id:
            return True
        return self.group.students.filter(pk__in=other.group.students.values("pk")).exists()

    def find_conflicts(self):
        """Séances qui chevauchent celle-ci, sous la forme ``[(motifs, séance)]``.

        Motifs : la classe (ou un groupe partageant des étudiants), le
        professeur ou la salle sont déjà pris sur le créneau. Deux séances
        qui s'enchaînent sans se chevaucher ne sont pas en conflit.
        """
        if not (
            self.assignment_id and self.weekday is not None
            and self.start_time and self.end_time and self.end_time > self.start_time
        ):
            return []
        assignment = self.assignment
        candidates = (
            ScheduleSlot.objects.filter(
                university_id=assignment.university_id,
                weekday=self.weekday,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            )
            .exclude(pk=self.pk)
            .select_related(
                "assignment__school_class", "assignment__subject",
                "assignment__professor__membership__user", "group",
            )
        )
        room = (self.room or "").strip().lower()
        conflicts = []
        for other in candidates:
            reasons = []
            if other.assignment.school_class_id == assignment.school_class_id and self._same_audience(other):
                reasons.append(CONFLICT_CLASS)
            if other.assignment.professor_id == assignment.professor_id:
                reasons.append(CONFLICT_PROFESSOR)
            if room and room == (other.room or "").strip().lower():
                reasons.append(CONFLICT_ROOM)
            if reasons:
                conflicts.append((reasons, other))
        return conflicts

    def clean(self):
        # L'ordre des horaires est contrôlé par la contrainte schedule_slot_end_after_start
        # (validée par full_clean) : on évite ici un second message identique.
        if not self.assignment_id:
            return
        if self.group_id and self.group.school_class_id != self.assignment.school_class_id:
            raise ValidationError({"group": "Ce groupe n'appartient pas à la classe de l'affectation."})
        messages = []
        for reasons, other in self.find_conflicts():
            detail = "%s · %s · %s" % (
                other.describe(), other.assignment.school_class.name, other.assignment.professor_name,
            )
            if other.room:
                detail += " · " + other.room
            for reason in reasons:
                messages.append(ValidationError("%s : %s." % (CONFLICT_MESSAGES[reason], detail)))
        if messages:
            raise ValidationError(messages)

    def save(self, *args, **kwargs):
        if self.assignment_id:
            self.university_id = self.assignment.university_id
        self.room = (self.room or "").strip()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Cours, publication, chapitres et supports
# ---------------------------------------------------------------------------

class Course(models.Model):
    """Cours d'un professeur pour une matière, réutilisable dans plusieurs classes."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="courses", verbose_name="Université",
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.RESTRICT,
        related_name="courses", verbose_name="Matière",
    )
    professor = models.ForeignKey(
        ProfessorProfile, on_delete=models.CASCADE,
        related_name="courses", verbose_name="Professeur",
    )
    title = models.CharField("Titre", max_length=200)
    description = models.TextField(
        "Présentation", blank=True,
        help_text="Objectifs, prérequis, organisation et modalités d'évaluation.",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("subject__name", "title")
        verbose_name = "Cours"
        verbose_name_plural = "Cours"
        constraints = [
            models.UniqueConstraint(
                Lower("title"), "professor", "subject", name="unique_course_title_per_professor_subject",
                violation_error_message="Vous avez déjà un cours portant ce titre pour cette matière.",
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        errors = {}
        if self.subject_id and self.professor_id:
            _same_university(
                errors, "subject", self.subject, self.professor.university_id,
                "La matière doit appartenir à la même université que le professeur.",
            )
            if not errors and not TeachingAssignment.objects.filter(
                subject_id=self.subject_id, professor_id=self.professor_id,
            ).exists():
                errors["subject"] = "Ce professeur n'est affecté à aucune classe pour cette matière."
        if errors:
            raise ValidationError(errors)

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._original_subject_id = instance.subject_id
        return instance

    def save(self, *args, **kwargs):
        if self.subject_id:
            self.university_id = self.subject.university_id
        self.title = (self.title or "").strip()
        with transaction.atomic():
            super().save(*args, **kwargs)
            original = getattr(self, "_original_subject_id", None)
            if original is not None and original != self.subject_id:
                # Le cours change de matière : il ne reste publié que dans les classes
                # où son auteur enseigne la nouvelle matière.
                taught = TeachingAssignment.objects.filter(
                    professor_id=self.professor_id, subject_id=self.subject_id,
                ).values("school_class_id")
                self.publications.exclude(school_class_id__in=taught).delete()
            self._original_subject_id = self.subject_id


class CoursePublication(models.Model):
    """Publication d'un cours pour une classe : c'est elle qui le rend visible aux étudiants."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="course_publications", verbose_name="Université",
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name="publications", verbose_name="Cours",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE,
        related_name="course_publications", verbose_name="Classe",
    )
    is_published = models.BooleanField("Publié", default=False)
    published_at = models.DateTimeField("Publié le", null=True, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("school_class__name",)
        verbose_name = "Publication de cours"
        verbose_name_plural = "Publications de cours"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "school_class"), name="unique_publication_per_course_class",
            ),
        ]

    def __str__(self):
        return "%s → %s (%s)" % (
            self.course, self.school_class.name, "publié" if self.is_published else "non publié",
        )

    def clean(self):
        if self.course_id and self.school_class_id:
            if self.course.university_id != self.school_class.university_id:
                raise ValidationError("Le cours et la classe doivent appartenir à la même université.")
            if not TeachingAssignment.objects.filter(
                school_class_id=self.school_class_id,
                subject_id=self.course.subject_id,
                professor_id=self.course.professor_id,
            ).exists():
                raise ValidationError(
                    "Le professeur n'enseigne pas cette matière à cette classe : "
                    "le cours ne peut pas y être publié."
                )

    def save(self, *args, **kwargs):
        if self.course_id:
            self.university_id = self.course.university_id
        super().save(*args, **kwargs)


class Chapter(models.Model):
    """Chapitre d'un cours ; l'ordre d'affichage est porté par ``order``."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name="chapters", verbose_name="Cours",
    )
    title = models.CharField("Titre", max_length=200)
    summary = models.TextField("Résumé", blank=True)
    objectives = models.TextField(
        "Objectifs d'apprentissage", blank=True, help_text="Un objectif par ligne.",
    )
    duration_hours = models.PositiveSmallIntegerField(
        "Durée (heures)", null=True, blank=True, validators=[MinValueValidator(1)],
    )
    order = models.PositiveIntegerField("Ordre", default=0)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("order", "pk")
        verbose_name = "Chapitre"
        verbose_name_plural = "Chapitres"

    def __str__(self):
        return "%d. %s" % (self.order, self.title)

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        if self._state.adding and not self.order and self.course_id:
            last = Chapter.objects.filter(course_id=self.course_id).aggregate(last=Max("order"))["last"]
            self.order = (last or 0) + 1
        super().save(*args, **kwargs)


def material_upload_path(instance, filename):
    """Nom aléatoire : le fichier n'est ni devinable ni lié au nom d'origine."""
    return "courses/%s/%s/%s%s" % (
        instance.course.university_id, instance.course_id,
        uuid.uuid4().hex, files.extension_of(filename),
    )


class CourseMaterial(models.Model):
    """Support de cours (PDF, présentation, vidéo ou audio), rattaché à un chapitre ou au cours."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name="materials", verbose_name="Cours",
    )
    chapter = models.ForeignKey(
        Chapter, on_delete=models.CASCADE, null=True, blank=True,
        related_name="materials", verbose_name="Chapitre",
        help_text="Laissez vide pour un support général du cours.",
    )
    title = models.CharField("Titre", max_length=200)
    description = models.TextField("Description", blank=True)
    file = models.FileField(
        "Fichier", storage=ProtectedMediaStorage(),
        upload_to=material_upload_path, max_length=255,
    )
    material_type = models.CharField("Type", max_length=20, choices=files.TYPE_CHOICES)
    original_name = models.CharField("Nom d'origine", max_length=255, blank=True)
    size = models.PositiveBigIntegerField("Taille (octets)", default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="uploaded_course_materials", verbose_name="Déposé par",
    )
    created_at = models.DateTimeField("Déposé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("created_at", "pk")
        verbose_name = "Support de cours"
        verbose_name_plural = "Supports de cours"

    def __str__(self):
        return self.title

    # -- présentation -------------------------------------------------------
    @property
    def icon(self):
        return files.TYPE_RULES[self.material_type]["icon"]

    @property
    def tone_class(self):
        return files.TYPE_RULES[self.material_type]["tone"]

    @property
    def can_preview(self):
        return self.material_type in files.INLINE_TYPES

    @property
    def size_label(self):
        return files.format_size(self.size)

    @property
    def extension_label(self):
        return files.extension_of(self.original_name or self.file.name).lstrip(".").upper()

    def clean(self):
        if self.chapter_id and self.course_id and self.chapter.course_id != self.course_id:
            raise ValidationError({"chapter": "Ce chapitre n'appartient pas au cours choisi."})

    def save(self, *args, **kwargs):
        upload = self.file
        if upload and not getattr(upload, "_committed", True):
            detected = files.detect_type(upload.name)
            if detected is None:
                raise ValidationError(
                    "Format non pris en charge. Formats acceptés : %s." % files.ACCEPTED_LABEL
                )
            self.material_type = detected
            self.original_name = files.safe_original_name(upload.name)
            self.size = upload.size
            if not self.title:
                self.title = self.original_name.rsplit(".", 1)[0][:200]
        super().save(*args, **kwargs)
