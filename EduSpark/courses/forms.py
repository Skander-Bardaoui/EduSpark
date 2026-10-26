"""Formulaires du catalogue, des affectations, de l'emploi du temps et des cours.

Chaque formulaire est borné à l'université courante : les listes déroulantes
ne proposent jamais d'objet d'une autre université, et les unicités qui
dépendent de l'université (que Django ne vérifie pas puisque ce champ n'est
pas dans le formulaire) sont contrôlées ici avec des messages explicites.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from accounts.forms import StyledFormMixin
from accounts.models import ProfessorProfile, SchoolClass, StudentGroup

from . import files
from .models import (
    Chapter, Course, CourseMaterial, Department, Program, ScheduleSlot, Subject,
    TeachingAssignment, display_name,
)

def university_professors(university):
    """Professeurs actifs de l'université, classés par nom."""
    return ProfessorProfile.objects.filter(
        university=university, membership__is_active=True,
    ).select_related("membership__user").order_by(
        "membership__user__last_name", "membership__user__first_name",
    )


def professor_label(profile):
    label = display_name(profile.user)
    return "%s — %s" % (label, profile.department) if profile.department else label


def subject_label(subject):
    return "%s · %s — %s (%s)" % (
        subject.code, subject.name, subject.program.name, subject.semester_label,
    )


class _UniversityForm(StyledFormMixin, forms.ModelForm):
    """Base : l'université courante est fournie par la vue."""

    def __init__(self, *args, university, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)

    def _professor_field(self, name, empty_label="— Aucun —"):
        field = self.fields[name]
        field.queryset = university_professors(self.university)
        field.label_from_instance = professor_label
        field.empty_label = empty_label
        return field

    def _unique(self, model, lookup, value, message):
        clash = model.objects.filter(university=self.university, **{lookup: value})
        if clash.exclude(pk=self.instance.pk).exists():
            raise ValidationError(message)
        return value


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

class DepartmentForm(_UniversityForm):
    class Meta:
        model = Department
        fields = ("name", "code", "head", "description")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._professor_field("head")

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        return self._unique(Department, "name__iexact", name, "Un département porte déjà ce nom.")

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if not code:
            return code
        return self._unique(Department, "code", code, "Un département utilise déjà ce code.")


class ProgramForm(_UniversityForm):
    class Meta:
        model = Program
        fields = ("name", "code", "department", "degree", "duration_years", "coordinator", "description")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(university=self.university)
        self.fields["department"].empty_label = "— Choisir un département —"
        self._professor_field("coordinator")

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        return self._unique(Program, "name__iexact", name, "Une filière porte déjà ce nom.")

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if not code:
            return code
        return self._unique(Program, "code", code, "Une filière utilise déjà ce code.")


class SubjectForm(_UniversityForm):
    semester = forms.TypedChoiceField(
        label="Semestre", coerce=int,
        choices=[(number, "Semestre %d (S%d)" % (number, number)) for number in range(1, 11)],
        help_text="Numéro du semestre dans la filière.",
    )

    class Meta:
        model = Subject
        fields = (
            "program", "name", "code", "semester", "coefficient", "credits",
            "hours_cm", "hours_td", "hours_tp", "description", "is_active",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["program"].queryset = Program.objects.filter(
            university=self.university,
        ).select_related("department")
        self.fields["program"].empty_label = "— Choisir une filière —"

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        return self._unique(Subject, "code", code, "Une matière utilise déjà ce code.")

    def clean(self):
        cleaned = super().clean()
        program, name = cleaned.get("program"), cleaned.get("name")
        if program and name:
            clash = Subject.objects.filter(program=program, name__iexact=name.strip())
            if clash.exclude(pk=self.instance.pk).exists():
                self.add_error("name", "Cette filière a déjà une matière portant cet intitulé.")
        return cleaned


# ---------------------------------------------------------------------------
# Affectations et emploi du temps
# ---------------------------------------------------------------------------

class TeachingAssignmentForm(_UniversityForm):
    class Meta:
        model = TeachingAssignment
        fields = ("school_class", "subject", "professor")

    def __init__(self, *args, school_class=None, **kwargs):
        super().__init__(*args, **kwargs)
        classes = SchoolClass.objects.filter(university=self.university).order_by("-academic_year", "name")
        subjects = Subject.objects.filter(university=self.university).select_related("program")
        self.fields["school_class"].queryset = classes
        self.fields["school_class"].empty_label = "— Choisir une classe —"
        self._professor_field("professor", empty_label="— Choisir un professeur —")
        self.fields["professor"].required = True
        self.fields["subject"].empty_label = "— Choisir une matière —"
        if self.instance.pk:
            # Modification : seule l'enseignant change. La classe et la matière
            # définissent l'affectation ; pour en changer, on en crée une autre.
            self.fields["school_class"].disabled = True
            self.fields["subject"].disabled = True
            self.fields["subject"].queryset = subjects
            self.fields["subject"].help_text = "La classe et la matière ne sont pas modifiables."
        else:
            subjects = subjects.filter(is_active=True)
            if school_class is not None:
                self.fields["school_class"].initial = school_class.pk
                if school_class.study_program_id:
                    subjects = subjects.filter(program_id=school_class.study_program_id)
            self.fields["subject"].queryset = subjects
        self.fields["subject"].label_from_instance = subject_label


class ScheduleSlotForm(_UniversityForm):
    class Meta:
        model = ScheduleSlot
        fields = ("assignment", "session_type", "group", "weekday", "start_time", "end_time", "room")
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def __init__(self, *args, school_class=None, **kwargs):
        super().__init__(*args, **kwargs)
        assignments = TeachingAssignment.objects.filter(
            university=self.university,
        ).select_related("school_class", "subject", "professor__membership__user")
        groups = StudentGroup.objects.filter(university=self.university).select_related("school_class")
        if school_class is not None:
            assignments = assignments.filter(school_class=school_class)
            groups = groups.filter(school_class=school_class)
        assignment = self.fields["assignment"]
        assignment.queryset = assignments
        assignment.empty_label = "— Choisir une affectation —"
        assignment.label_from_instance = lambda item: "%s — %s · %s (%s)" % (
            item.school_class.name, item.subject.code, item.subject.name, item.professor_name,
        )
        assignment.help_text = (
            "Une séance ne se planifie que pour une matière affectée à un professeur : "
            "créez d'abord l'affectation si elle manque."
        )
        group = self.fields["group"]
        group.queryset = groups
        group.empty_label = "Toute la classe"
        group.label_from_instance = lambda item: "%s — %s" % (item.school_class.name, item.name)


# ---------------------------------------------------------------------------
# Cours, chapitres, supports (professeur)
# ---------------------------------------------------------------------------

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Champ fichier acceptant plusieurs fichiers ; ``clean`` renvoie une liste."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return [] if not self.required else super().clean(data, initial)
        uploads = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(upload, initial) for upload in uploads]


# Le champ fichier est masqué : la zone de dépôt (bouton + glisser-déposer) le pilote.
FILE_INPUT_ATTRS = {"class": "sr-only", "accept": files.ACCEPT_ATTRIBUTE}


class CourseForm(StyledFormMixin, forms.ModelForm):
    files = MultipleFileField(
        label="Fichiers du cours", required=False,
        widget=MultipleFileInput(attrs=dict(FILE_INPUT_ATTRS)),
        help_text=(
            "PDF, PowerPoint, Word, vidéos ou audios ; plusieurs fichiers possibles. "
            "Ils sont ajoutés aux supports du cours."
        ),
    )

    class Meta:
        model = Course
        fields = ("subject", "title", "files", "description")

    def __init__(self, *args, professor, **kwargs):
        self.professor = professor
        super().__init__(*args, **kwargs)
        # Fixés avant la validation : Course.clean() vérifie que le professeur enseigne la matière.
        self.instance.professor = professor
        self.instance.university_id = professor.university_id
        subject = self.fields["subject"]
        subject.queryset = Subject.objects.filter(
            teaching_assignments__professor=professor,
        ).select_related("program").distinct()
        subject.empty_label = "— Choisir une matière —"
        subject.label_from_instance = subject_label
        subject.help_text = "Seules les matières qui vous sont affectées sont proposées."

    def clean(self):
        cleaned = super().clean()
        subject, title = cleaned.get("subject"), (cleaned.get("title") or "").strip()
        if subject and title:
            clash = Course.objects.filter(
                professor=self.professor, subject=subject, title__iexact=title,
            ).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("title", "Vous avez déjà un cours portant ce titre pour cette matière.")
        return cleaned

    def clean_files(self):
        uploads = self.cleaned_data.get("files") or []
        errors = []
        for upload in uploads:
            try:
                files.validate_upload(upload)
            except ValidationError as error:
                errors.append("%s : %s" % (upload.name, error.messages[0]))
        if errors:
            raise ValidationError(errors)
        return uploads

    def save_materials(self, course, user):
        """Crée un support général du cours pour chaque fichier déposé ; renvoie leur nombre."""
        uploads = self.cleaned_data.get("files") or []
        for upload in uploads:
            CourseMaterial.objects.create(course=course, file=upload, uploaded_by=user)
        return len(uploads)


class ChapterForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Chapter
        fields = ("title", "summary")
        labels = {"summary": "Résumé du chapitre"}

    def __init__(self, *args, course, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)
        self.instance.course = course
        self.fields["summary"].widget.attrs["rows"] = 4


class MaterialForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CourseMaterial
        fields = ("course", "chapter", "title", "description", "file")
        widgets = {"file": forms.FileInput(attrs=dict(FILE_INPUT_ATTRS))}

    def __init__(self, *args, professor, course=None, **kwargs):
        self.professor = professor
        super().__init__(*args, **kwargs)
        courses = Course.objects.filter(professor=professor).select_related("subject")
        chapters = Chapter.objects.filter(course__professor=professor).select_related("course")
        self._previous_name = self.instance.file.name if self.instance.pk and self.instance.file else None
        if self.instance.pk:
            # Le support reste dans son cours ; on peut seulement le changer de chapitre.
            self.fields["course"].disabled = True
            chapters = chapters.filter(course=self.instance.course)
        elif course is not None:
            self.fields["course"].initial = course.pk
            chapters = chapters.filter(course=course)
        course_field = self.fields["course"]
        course_field.queryset = courses
        course_field.empty_label = "— Choisir un cours —"
        course_field.label_from_instance = lambda item: "%s — %s" % (item.subject.code, item.title)
        chapter_field = self.fields["chapter"]
        chapter_field.queryset = chapters
        chapter_field.empty_label = "Support général du cours"
        chapter_field.label_from_instance = lambda item: "%s — %s" % (item.course.title, item.title)
        self.fields["title"].required = False
        
        file_field = self.fields["file"]
        file_field.required = not self.instance.pk
        if self.instance.pk:
            file_field.help_text = "Fichier actuel : %s (%s). Laissez vide pour le conserver." % (
                self.instance.original_name, self.instance.size_label,
            )
        else:
            file_field.help_text = "Formats acceptés : %s." % files.ACCEPTED_LABEL

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if isinstance(upload, UploadedFile):
            files.validate_upload(upload)
        return upload

    def save(self, commit=True):
        material = super().save(commit=commit)
        if commit and self._previous_name and self._previous_name != material.file.name:
            # Le fichier a été remplacé : l'ancien ne doit pas rester sur le disque.
            material.file.storage.delete(self._previous_name)
        return material
