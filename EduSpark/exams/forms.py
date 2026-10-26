from datetime import timedelta
from pathlib import Path
import zipfile

from django import forms
from django.conf import settings
from django.utils import timezone

from accounts.models import SchoolClass
from courses.models import Course, Subject

from .models import (
    ExamSession, OralTopic, ProjectCriterion, ProjectSubmission, Quiz,
)

_INPUT_CLASS = (
    "w-full rounded-md border border-outline-variant/70 bg-surface px-3.5 py-2.5 "
    "text-sm text-on-surface outline-none transition-colors focus:border-primary"
)
_SELECT_CLASS = _INPUT_CLASS + " cursor-pointer"
_DATETIME_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M")


class SchoolClassCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    """Cases à cocher des classes, avec filière, niveau et section."""

    def __init__(self, *args, **kwargs):
        self.program_map = kwargs.pop("program_map", {})
        self.level_map = kwargs.pop("level_map", {})
        self.section_map = kwargs.pop("section_map", {})
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index,
                      subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs,
        )
        if value:
            option["attrs"]["data-program"] = self.program_map.get(str(value), "")
            option["attrs"]["data-level"] = self.level_map.get(str(value), "")
            option["attrs"]["data-section"] = self.section_map.get(str(value), "")
        return option


class SubjectSelect(forms.Select):
    """Liste des matières, avec la filière en attribut data."""

    def __init__(self, *args, **kwargs):
        self.program_map = kwargs.pop("program_map", {})
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index,
                      subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs,
        )
        if value:
            option["attrs"]["data-program"] = self.program_map.get(str(value), "")
        return option


class SchoolClassMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return _class_label(obj)


def _class_label(school_class):
    parts = [school_class.name]
    if school_class.level:
        parts.append(school_class.level)
    if school_class.section:
        parts.append("Section %s" % school_class.section)
    if school_class.program:
        parts.append(school_class.program)
    return " · ".join(parts)


def _subject_label(subject):
    return "%s · %s" % (subject.code, subject.name)


class ExamSessionForm(forms.ModelForm):
    """Planifie une épreuve pour une ou plusieurs classes.

    La fenêtre ``opens_at`` / ``closes_at`` est commune aux classes créées.
    """

    school_classes = SchoolClassMultipleChoiceField(
        label="Classes concernées",
        queryset=SchoolClass.objects.none(),
        widget=SchoolClassCheckboxSelectMultiple(),
        required=False,
        help_text="Filtrez par niveau ou section, puis sélectionnez les classes.",
    )

    class Meta:
        model = ExamSession
        fields = (
            "school_class", "school_classes", "course_subject", "title",
            "exam_type", "instructions", "opens_at", "closes_at",
        )
        widgets = {
            "school_class": forms.Select(attrs={"class": _SELECT_CLASS}),
            "course_subject": SubjectSelect(attrs={"class": _SELECT_CLASS}),
            "exam_type": forms.Select(attrs={"class": _SELECT_CLASS}),
            "title": forms.TextInput(attrs={
                "class": _INPUT_CLASS,
                "placeholder": "Ex. INF501 · Algorithmique avancée",
            }),
            "instructions": forms.Textarea(attrs={
                "class": _INPUT_CLASS, "rows": 3,
                "placeholder": "Consignes communes aux étudiants (facultatif).",
            }),
            "opens_at": forms.DateTimeInput(
                attrs={"class": _INPUT_CLASS, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "closes_at": forms.DateTimeInput(
                attrs={"class": _INPUT_CLASS, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, university=None, class_queryset=None, multi=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        self.is_multi = multi and not self.instance.pk

        classes = SchoolClass.objects.all()
        if class_queryset is not None:
            classes = class_queryset
        elif university is not None:
            classes = classes.filter(university=university)
        classes = classes.order_by("-academic_year", "name")

        self.fields["school_class"].queryset = classes
        self.fields["school_class"].empty_label = "- Choisir une classe -"
        self.fields["school_classes"].queryset = classes
        program_map = {}
        level_map = {}
        section_map = {}
        level_counts = {}
        section_counts = {}
        for item in classes:
            key = str(item.pk)
            program_map[key] = str(item.study_program_id or "")
            level_map[key] = item.level or ""
            section_map[key] = item.section or ""
            if item.level:
                level_counts[item.level] = level_counts.get(item.level, 0) + 1
            if item.section:
                section_counts[item.section] = section_counts.get(item.section, 0) + 1
        self.fields["school_classes"].widget.program_map = program_map
        self.fields["school_classes"].widget.level_map = level_map
        self.fields["school_classes"].widget.section_map = section_map
        self.class_levels = sorted(level_counts)
        self.class_sections = sorted(section_counts)
        self.class_level_options = [
            {"value": level, "count": level_counts[level]}
            for level in self.class_levels
        ]
        self.class_section_options = [
            {"value": section, "count": section_counts[section]}
            for section in self.class_sections
        ]

        subjects = Subject.objects.none()
        if university is not None:
            subjects = (
                Subject.objects.filter(university=university, is_active=True)
                .select_related("program")
            )
        if self.instance.pk and self.instance.school_class_id:
            program_id = self.instance.school_class.study_program_id
            if program_id:
                subjects = subjects.filter(program_id=program_id)
        self.fields["course_subject"].queryset = subjects
        self.fields["course_subject"].empty_label = "- Choisir une matière -"
        self.fields["course_subject"].label_from_instance = _subject_label
        self.fields["course_subject"].widget.program_map = {
            str(subject.pk): str(subject.program_id or "") for subject in subjects
        }
        self.fields["course_subject"].help_text = (
            "La matière rattache la session à la filière de la classe."
        )
        self.fields["title"].required = False
        self.fields["title"].help_text = (
            "Laissez vide pour reprendre le code et l'intitulé de la matière."
        )
        self.fields["exam_type"].required = False
        self.fields["exam_type"].initial = ExamSession.TYPE_QCM
        self.fields["exam_type"].help_text = (
            "QCM : questionnaire en ligne. Projet : dépôt ZIP et grille de critères. "
            "Oral : tirage d'un sujet et notation par le professeur."
        )
        self.fields["instructions"].help_text = (
            "Facultatif. Affichées sur la page de l'épreuve."
        )
        self.fields["opens_at"].input_formats = _DATETIME_FORMATS
        self.fields["closes_at"].input_formats = _DATETIME_FORMATS
        self.fields["opens_at"].help_text = "Début de la fenêtre d'épreuve."
        self.fields["closes_at"].help_text = "Fin de la fenêtre d'épreuve."

        if not self.is_bound and not self.instance.pk:
            start = timezone.localtime().replace(
                minute=0, second=0, microsecond=0,
            ) + timedelta(days=1, hours=1)
            self.initial.setdefault("opens_at", start)
            self.initial.setdefault("closes_at", start + timedelta(hours=2))

        if self.is_multi:
            self.fields.pop("school_class")
            self.fields["school_classes"].required = True
        else:
            self.fields.pop("school_classes")

    def _selected_classes(self, cleaned):
        if self.is_multi:
            return list(cleaned.get("school_classes") or [])
        school_class = cleaned.get("school_class")
        return [school_class] if school_class else []

    def clean(self):
        cleaned = super().clean()
        classes = self._selected_classes(cleaned)
        subject = cleaned.get("course_subject")
        title = (cleaned.get("title") or "").strip()
        if not cleaned.get("exam_type"):
            cleaned["exam_type"] = ExamSession.TYPE_QCM
        if not title:
            if subject:
                cleaned["title"] = "%s · %s" % (subject.code, subject.name)
            else:
                self.add_error(
                    "title",
                    "Renseignez l'intitulé de la session ou choisissez une matière.",
                )

        if subject:
            if self.university and subject.university_id != self.university.pk:
                self.add_error(
                    "course_subject",
                    "Cette matière n'appartient pas à l'université de la session.",
                )
            mismatched = [
                school_class.name
                for school_class in classes
                if school_class.study_program_id
                and school_class.study_program_id != subject.program_id
            ]
            if mismatched:
                self.add_error(
                    "course_subject",
                    "La matière %s ne correspond pas à la filière de : %s."
                    % (subject, ", ".join(mismatched)),
                )

        opens_at = cleaned.get("opens_at")
        closes_at = cleaned.get("closes_at")
        if opens_at and closes_at and closes_at <= opens_at:
            self.add_error(
                "closes_at",
                "La fermeture doit être postérieure à l'ouverture.",
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        subject = self.cleaned_data.get("course_subject")
        if subject:
            instance.course_subject = subject
        if commit:
            instance.save()
        return instance

    def save_sessions(self, university, user):
        """Crée une session par classe sélectionnée, avec la même fenêtre."""
        classes = list(self.cleaned_data["school_classes"])
        subject = self.cleaned_data.get("course_subject")
        sessions = []
        for school_class in classes:
            session = ExamSession(
                university=university,
                school_class=school_class,
                course_subject=subject,
                title=self.cleaned_data["title"],
                exam_type=self.cleaned_data.get("exam_type") or ExamSession.TYPE_QCM,
                instructions=self.cleaned_data.get("instructions") or "",
                opens_at=self.cleaned_data["opens_at"],
                closes_at=self.cleaned_data["closes_at"],
                created_by=user,
            )
            session.save()
            sessions.append(session)
        return sessions


class QuizGenerateForm(forms.ModelForm):
    """Paramètres du QCM lors de la génération par IA."""

    DIFFICULTY_CHOICES = (
        ("facile", "Facile"),
        ("moyen", "Moyen"),
        ("difficile", "Difficile"),
    )

    difficulty = forms.ChoiceField(
        label="Difficulté", choices=DIFFICULTY_CHOICES, initial="moyen",
        widget=forms.Select(attrs={"class": _SELECT_CLASS}),
    )

    class Meta:
        model = Quiz
        fields = (
            "course", "question_count", "duration_minutes", "pass_score",
            "shuffle_questions", "instructions",
        )
        widgets = {
            "course": forms.Select(attrs={"class": _SELECT_CLASS}),
            "question_count": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 1, "max": 100, "step": 1,
            }),
            "duration_minutes": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 5, "max": 480, "step": 5,
            }),
            "pass_score": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 0, "max": 20, "step": "0.5",
            }),
            "shuffle_questions": forms.CheckboxInput(attrs={
                "class": "h-4 w-4 rounded border-outline-variant text-primary",
            }),
            "instructions": forms.Textarea(attrs={
                "class": _INPUT_CLASS, "rows": 3,
                "placeholder": "Consignes affichées avant le démarrage du QCM…",
            }),
        }

    def __init__(self, *args, course_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = course_queryset or Course.objects.none()
        self.fields["course"].empty_label = "- Choisir un cours -"
        self.fields["course"].required = True
        self.fields["question_count"].initial = 30
        self.fields["duration_minutes"].initial = 60
        self.fields["pass_score"].initial = 10
        self.fields["question_count"].help_text = "Entre 1 et 100 questions."
        self.fields["duration_minutes"].help_text = (
            "Temps accordé à l'étudiant à partir du démarrage."
        )


class ManualQuizForm(forms.ModelForm):
    """Création manuelle d'un QCM rattaché à un cours enseigné dans la classe."""

    class Meta:
        model = Quiz
        fields = ("course", "duration_minutes", "pass_score", "instructions")
        widgets = {
            "course": forms.Select(attrs={"class": _SELECT_CLASS}),
            "duration_minutes": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 5, "max": 480, "step": 5,
            }),
            "pass_score": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 0, "max": 20, "step": "0.5",
            }),
            "instructions": forms.Textarea(attrs={
                "class": _INPUT_CLASS, "rows": 4,
                "placeholder": "Consignes affichées avant le démarrage du QCM…",
            }),
        }
        labels = {
            "course": "Cours source",
            "duration_minutes": "Durée (minutes)",
            "pass_score": "Note de validation /20",
        }

    def __init__(self, *args, course_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = course_queryset or Course.objects.none()
        self.fields["course"].empty_label = "- Choisir le cours enseigné -"
        self.fields["course"].required = True
        self.fields["duration_minutes"].help_text = (
            "Temps accordé à l'étudiant à partir du démarrage du QCM."
        )
        self.fields["pass_score"].help_text = "Seuil de réussite sur 20."
        self.fields["instructions"].help_text = (
            "Facultatif. Ces consignes s'affichent avant le démarrage."
        )


class ProjectSubmissionForm(forms.ModelForm):
    """Dépôt d'une archive ZIP par un étudiant."""

    class Meta:
        model = ProjectSubmission
        fields = ("file",)
        widgets = {
            "file": forms.ClearableFileInput(attrs={
                "class": _INPUT_CLASS, "accept": ".zip,application/zip",
            }),
        }
        labels = {"file": "Archive du projet (.zip)"}

    def __init__(self, *args, require_file=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].required = require_file
        self.fields["file"].help_text = (
            "Un seul fichier ZIP. Taille maximale : %s Mo."
            % (self._max_bytes() // (1024 * 1024))
        )

    @staticmethod
    def _max_bytes():
        return int(getattr(settings, "EXAM_PROJECT_MAX_ZIP_BYTES", 50 * 1024 * 1024))

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if upload is None:
            return upload
        if Path(upload.name or "").suffix.lower() != ".zip":
            raise forms.ValidationError("Le projet doit être une archive au format .zip.")
        if upload.size > self._max_bytes():
            raise forms.ValidationError(
                "L'archive dépasse la taille maximale autorisée (%s Mo)."
                % (self._max_bytes() // (1024 * 1024))
            )
        try:
            upload.seek(0)
            with zipfile.ZipFile(upload) as archive:
                if any(info.flag_bits & 0x1 for info in archive.infolist()):
                    raise forms.ValidationError(
                        "Les archives ZIP protégées par mot de passe ne sont pas acceptées."
                    )
        except zipfile.BadZipFile:
            raise forms.ValidationError("Le fichier n'est pas une archive ZIP valide.")
        finally:
            try:
                upload.seek(0)
            except (AttributeError, ValueError):
                pass
        return upload


class ProjectCriterionForm(forms.ModelForm):
    class Meta:
        model = ProjectCriterion
        fields = ("label", "description", "weight")
        widgets = {
            "label": forms.TextInput(attrs={"class": _INPUT_CLASS}),
            "description": forms.Textarea(attrs={"class": _INPUT_CLASS, "rows": 2}),
            "weight": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 1, "max": 20, "step": 1,
            }),
        }
        labels = {
            "label": "Critère",
            "description": "Attendu",
            "weight": "Poids",
        }

    def clean_weight(self):
        weight = self.cleaned_data["weight"]
        if weight < 1:
            raise forms.ValidationError("Le poids doit être au moins égal à 1.")
        if weight > 20:
            raise forms.ValidationError("Le poids ne peut pas dépasser 20.")
        return weight


class OralTopicForm(forms.ModelForm):
    class Meta:
        model = OralTopic
        fields = ("title", "instructions", "duration_minutes", "is_active")
        widgets = {
            "title": forms.TextInput(attrs={"class": _INPUT_CLASS}),
            "instructions": forms.Textarea(attrs={"class": _INPUT_CLASS, "rows": 3}),
            "duration_minutes": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 1, "max": 120, "step": 1,
            }),
        }
        labels = {
            "title": "Sujet",
            "instructions": "Consignes",
            "duration_minutes": "Préparation (minutes)",
            "is_active": "Sujet actif",
        }


class ProjectGradeForm(forms.Form):
    score = forms.DecimalField(
        label="Note /20", min_value=0, max_value=20, decimal_places=2,
        widget=forms.NumberInput(attrs={
            "class": _INPUT_CLASS, "min": 0, "max": 20, "step": "0.25",
        }),
    )
    feedback = forms.CharField(
        label="Commentaire", required=False,
        widget=forms.Textarea(attrs={"class": _INPUT_CLASS, "rows": 4}),
    )


class OralGradeForm(forms.Form):
    score = forms.DecimalField(
        label="Note /20", min_value=0, max_value=20, decimal_places=2,
        widget=forms.NumberInput(attrs={
            "class": _INPUT_CLASS, "min": 0, "max": 20, "step": "0.25",
        }),
    )
    feedback = forms.CharField(
        label="Commentaire", required=False,
        widget=forms.Textarea(attrs={"class": _INPUT_CLASS, "rows": 4}),
    )
