import uuid

from django import forms

from accounts.models import SchoolClass
from courses.models import Course, Subject

from .models import ExamSession, GradeRecord, Quiz

_INPUT_CLASS = (
    "w-full rounded-md border border-outline-variant/70 bg-surface px-3.5 py-2.5 "
    "text-sm text-on-surface outline-none transition-colors focus:border-primary"
)
_SELECT_CLASS = _INPUT_CLASS + " cursor-pointer"


class SchoolClassCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    """Cases à cocher des classes, avec filière, niveau et section en attributs data."""

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
            key = str(value)
            option["attrs"]["data-program"] = self.program_map.get(key, "")
            option["attrs"]["data-level"] = self.level_map.get(key, "")
            option["attrs"]["data-section"] = self.section_map.get(key, "")
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


class SchoolClassChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return _class_label(obj)


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
    label = "%s · %s" % (subject.code, subject.name)
    if subject.program_id:
        label += " · %s" % subject.program.name
    return label


class ExamSessionForm(forms.ModelForm):
    """Formulaire de session.

    En mode création (``multi=True``), l'administration choisit une ou
    plusieurs classes : une session est alors créée pour chacune d'elles,
    avec un même groupe de planification.
    """

    school_classes = SchoolClassMultipleChoiceField(
        label="Classes concernées",
        queryset=SchoolClass.objects.none(),
        widget=SchoolClassCheckboxSelectMultiple(),
        required=False,
        help_text=(
            "Cochez une ou plusieurs classes. "
            "Utile pour planifier la même épreuve à plusieurs niveaux ou filières."
        ),
    )

    class Meta:
        model = ExamSession
        fields = (
            "school_class", "school_classes", "course_subject", "title",
            "exam_type", "date", "start_time", "end_time", "room",
        )
        widgets = {
            "school_class": forms.Select(attrs={"class": _SELECT_CLASS}),
            "course_subject": SubjectSelect(attrs={"class": _SELECT_CLASS}),
            "title": forms.TextInput(attrs={
                "class": _INPUT_CLASS,
                "placeholder": "Ex. INF501 · Algorithmique avancée",
            }),
            "exam_type": forms.Select(attrs={"class": _SELECT_CLASS}),
            "date": forms.DateInput(attrs={"class": _INPUT_CLASS, "type": "date"}, format="%Y-%m-%d"),
            "start_time": forms.TimeInput(attrs={"class": _INPUT_CLASS, "type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"class": _INPUT_CLASS, "type": "time"}, format="%H:%M"),
            "room": forms.TextInput(attrs={"class": _INPUT_CLASS, "placeholder": "Ex. Amphi A"}),
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
        classes = classes.order_by("level", "program", "name")

        self.fields["school_class"].queryset = classes
        self.fields["school_class"].empty_label = "— Choisir une classe —"
        self.fields["school_classes"].queryset = classes
        self.fields["school_classes"].widget.program_map = {
            str(school_class.pk): str(school_class.study_program_id or "")
            for school_class in classes
        }
        self.fields["school_classes"].widget.level_map = {
            str(school_class.pk): school_class.level or ""
            for school_class in classes
        }
        self.fields["school_classes"].widget.section_map = {
            str(school_class.pk): school_class.section or ""
            for school_class in classes
        }
        self.class_levels = sorted({sc.level for sc in classes if sc.level})
        self.class_sections = sorted({sc.section for sc in classes if sc.section})

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
        self.fields["course_subject"].empty_label = "— Choisir une matière —"
        self.fields["course_subject"].label_from_instance = _subject_label
        self.fields["course_subject"].widget.program_map = {
            str(subject.pk): str(subject.program_id or "")
            for subject in subjects
        }
        self.fields["course_subject"].help_text = (
            "La matière rattache l'épreuve à la filière de la classe. "
            "Le code, le semestre et le coefficient sont repris automatiquement."
        )
        self.fields["title"].required = False
        self.fields["title"].help_text = (
            "Laissez vide pour reprendre le code et l'intitulé de la matière."
        )

        if self.is_multi:
            self.fields.pop("school_class")
            self.fields.pop("room")
            self.fields["school_classes"].required = True
            self.fields["school_classes"].help_text = (
                "Cochez une ou plusieurs classes. Chaque classe aura sa propre salle."
            )
        else:
            self.fields.pop("school_classes")

    def _selected_classes(self, cleaned):
        if self.is_multi:
            return list(cleaned.get("school_classes") or [])
        school_class = cleaned.get("school_class")
        return [school_class] if school_class else []

    def _class_rooms(self, classes):
        if not self.is_multi:
            return {}
        fallback = (self.data.get(self.add_prefix("room")) or "").strip()
        rooms = {}
        for school_class in classes:
            name = self.add_prefix("room_%s" % school_class.pk)
            rooms[school_class.pk] = (self.data.get(name) or "").strip() or fallback
        return rooms

    def _bound_values(self, name):
        if hasattr(self.data, "getlist"):
            return self.data.getlist(name)
        value = self.data.get(name) or []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    def room_fields(self):
        """Liste les salles à saisir pour chaque classe (planification multiple)."""
        if not self.is_multi:
            return []
        if self.is_bound:
            selected = {
                str(value)
                for value in self._bound_values(self.add_prefix("school_classes"))
            }
        else:
            selected = {
                str(value.pk)
                for value in (self.initial.get("school_classes") or [])
            }
        items = []
        for school_class in self.fields["school_classes"].queryset:
            name = self.add_prefix("room_%s" % school_class.pk)
            value = (self.data.get(name) or "").strip() if self.is_bound else ""
            items.append({
                "school_class": school_class,
                "label": _class_label(school_class),
                "name": name,
                "value": value,
                "selected": str(school_class.pk) in selected,
            })
        return items

    def clean(self):
        cleaned = super().clean()
        classes = self._selected_classes(cleaned)
        subject = cleaned.get("course_subject")
        title = (cleaned.get("title") or "").strip()
        if not title:
            if subject:
                cleaned["title"] = "%s · %s" % (subject.code, subject.name)
            else:
                self.add_error(
                    "title",
                    "Renseignez l'intitulé de l'épreuve ou choisissez une matière.",
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
        date = cleaned.get("date")
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")

        if start and end and end <= start:
            self.add_error(
                "end_time", "L'heure de fin doit être postérieure à l'heure de début.",
            )
            return cleaned
        if not self.university or not date or not start or not end:
            return cleaned

        existing = ExamSession.objects.filter(university=self.university, date=date)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if self.instance.pk and self.instance.plan_group:
            # Les sessions d'une même planification ne sont pas en conflit entre elles.
            existing = existing.exclude(plan_group=self.instance.plan_group)

        if self.is_multi:
            rooms = self._class_rooms(classes)
            for school_class in classes:
                room = rooms.get(school_class.pk, "")
                if not room:
                    continue
                room_clash = (
                    existing.filter(
                        room__iexact=room,
                        start_time__lt=end,
                        end_time__gt=start,
                    )
                    .select_related("school_class")
                    .first()
                )
                if room_clash:
                    self.add_error(
                        "school_classes",
                        "Salle %s déjà occupée pour %s par %s (%s)."
                        % (
                            room,
                            school_class.name,
                            room_clash.title,
                            room_clash.school_class.name,
                        ),
                    )
        else:
            room = (cleaned.get("room") or "").strip()
            if room:
                room_clash = existing.filter(
                    room__iexact=room,
                    start_time__lt=end,
                    end_time__gt=start,
                ).select_related("school_class").first()
                if room_clash:
                    self.add_error(
                        "room",
                        "La salle %s est déjà occupée par %s (%s)."
                        % (room, room_clash.title, room_clash.school_class.name),
                    )

        for school_class in classes:
            class_clash = existing.filter(
                school_class=school_class,
                start_time__lt=end,
                end_time__gt=start,
            ).first()
            if class_clash:
                field = "school_classes" if self.is_multi else "end_time"
                self.add_error(
                    field,
                    "%s a déjà une épreuve sur ce créneau (%s)."
                    % (school_class.name, class_clash.title),
                )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        subject = self.cleaned_data.get("course_subject")
        if subject:
            instance.course_subject = subject
            instance.code = subject.code
            instance.semester = "S%s" % subject.semester
            instance.coefficient = subject.coefficient
        if commit:
            instance.save()
        return instance

    def save_sessions(self, university, user):
        """Crée une session par classe sélectionnée, dans un même groupe."""
        classes = list(self.cleaned_data["school_classes"])
        rooms = self._class_rooms(classes)
        subject = self.cleaned_data.get("course_subject")
        group = uuid.uuid4()
        sessions = []
        for school_class in classes:
            session = ExamSession(
                university=university,
                school_class=school_class,
                course_subject=subject,
                title=self.cleaned_data["title"],
                code=subject.code if subject else "",
                coefficient=subject.coefficient if subject else 1,
                semester=("S%s" % subject.semester) if subject else "",
                exam_type=self.cleaned_data["exam_type"],
                date=self.cleaned_data["date"],
                start_time=self.cleaned_data["start_time"],
                end_time=self.cleaned_data["end_time"],
                room=rooms.get(school_class.pk, ""),
                plan_group=group,
                created_by=user,
            )
            session.save()
            sessions.append(session)
        return sessions


class GradeRecordForm(forms.ModelForm):
    class Meta:
        model = GradeRecord
        fields = ("students_count", "admitted_count", "average")
        widgets = {
            "students_count": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 0, "placeholder": "ex. 30",
            }),
            "admitted_count": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 0, "placeholder": "ex. 24",
            }),
            "average": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 0, "max": 20, "step": "0.1",
                "placeholder": "ex. 12.5",
            }),
        }

    def clean(self):
        cleaned = super().clean()
        students = cleaned.get("students_count")
        admitted = cleaned.get("admitted_count")
        average = cleaned.get("average")
        if students is not None and admitted is not None and admitted > students:
            self.add_error("admitted_count", "Le nombre d'admis ne peut pas dépasser l'effectif.")
        if average is not None and (average < 0 or average > 20):
            self.add_error("average", "La moyenne doit être comprise entre 0 et 20.")
        return cleaned


_DATETIME_INPUT_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M")


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
            "opens_at", "closes_at", "shuffle_questions", "instructions",
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
            "opens_at": forms.DateTimeInput(
                attrs={"class": _INPUT_CLASS, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "closes_at": forms.DateTimeInput(
                attrs={"class": _INPUT_CLASS, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
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
        self.fields["course"].empty_label = "— Choisir un cours —"
        self.fields["course"].required = True
        self.fields["opens_at"].input_formats = _DATETIME_INPUT_FORMATS
        self.fields["closes_at"].input_formats = _DATETIME_INPUT_FORMATS
        self.fields["opens_at"].required = False
        self.fields["closes_at"].required = False
        self.fields["question_count"].initial = 30
        self.fields["duration_minutes"].initial = 60
        self.fields["pass_score"].initial = 10
        self.fields["question_count"].help_text = "Entre 1 et 100 questions."
        self.fields["duration_minutes"].help_text = (
            "Temps accordé à l'étudiant à partir du démarrage."
        )
        self.fields["opens_at"].help_text = (
            "Vide : début officiel de l'épreuve."
        )
        self.fields["closes_at"].help_text = (
            "Vide : fin officielle de l'épreuve."
        )

    def clean(self):
        cleaned = super().clean()
        opens_at = cleaned.get("opens_at")
        closes_at = cleaned.get("closes_at")
        if opens_at and closes_at and closes_at <= opens_at:
            self.add_error("closes_at", "La fermeture doit être postérieure à l'ouverture.")
        return cleaned
