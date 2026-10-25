from django import forms

from .models import ExamSession, GradeRecord

_INPUT_CLASS = (
    "w-full rounded-md border border-outline-variant/70 bg-surface px-3.5 py-2.5 "
    "text-sm text-on-surface outline-none transition-colors focus:border-primary"
)
_SELECT_CLASS = _INPUT_CLASS + " cursor-pointer"


class ExamSessionForm(forms.ModelForm):
    class Meta:
        model = ExamSession
        fields = ("school_class", "title", "exam_type", "date", "start_time", "end_time", "room")
        widgets = {
            "school_class": forms.Select(attrs={"class": _SELECT_CLASS}),
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

    def __init__(self, *args, university=None, class_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        classes = self.fields["school_class"].queryset
        if class_queryset is not None:
            classes = class_queryset
        elif university is not None:
            classes = classes.filter(university=university)
        self.fields["school_class"].queryset = classes.order_by("name")
        self.fields["school_class"].empty_label = "— Choisir une classe —"

    def clean(self):
        cleaned = super().clean()
        school_class = cleaned.get("school_class")
        date = cleaned.get("date")
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        room = (cleaned.get("room") or "").strip()

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

        if school_class:
            class_clash = existing.filter(
                school_class=school_class,
                start_time__lt=end,
                end_time__gt=start,
            ).first()
            if class_clash:
                self.add_error(
                    "end_time",
                    "Cette classe a déjà une épreuve sur ce créneau (%s)." % class_clash.title,
                )
        return cleaned


class GradeRecordForm(forms.ModelForm):
    class Meta:
        model = GradeRecord
        fields = ("students_count", "admitted_count", "average")
        widgets = {
            "students_count": forms.NumberInput(attrs={"class": _INPUT_CLASS, "min": 0}),
            "admitted_count": forms.NumberInput(attrs={"class": _INPUT_CLASS, "min": 0}),
            "average": forms.NumberInput(attrs={
                "class": _INPUT_CLASS, "min": 0, "max": 20, "step": "0.1",
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
