from django import forms
from django.contrib.auth import get_user_model

from accounts.forms import StyledFormMixin
from accounts.models import Membership

from .access import visible_classes
from .models import Announcement, Forum, Message, Reply, Report, Thread

User = get_user_model()


class RequestFormMixin:
    """Restreint les listes déroulantes à l'université courante."""

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        if "school_class" in self.fields and request is not None:
            self.fields["school_class"].queryset = visible_classes(request).order_by("name")
            self.fields["school_class"].empty_label = "— Aucune —"


class AnnouncementForm(RequestFormMixin, StyledFormMixin, forms.ModelForm):
    placeholders = {
        "title": "ex. Rentrée universitaire 2026",
        "course_ref": "ex. INF501",
        "body": "ex. Les inscriptions ouvrent le…",
    }

    class Meta:
        model = Announcement
        fields = ("title", "body", "audience", "school_class", "course_ref", "priority", "is_pinned")
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}


class ForumForm(RequestFormMixin, StyledFormMixin, forms.ModelForm):
    placeholders = {
        "title": "ex. Forum d'entraide",
        "course_ref": "ex. INF501",
        "description": "ex. Posez vos questions sur le module…",
    }

    class Meta:
        model = Forum
        fields = ("title", "description", "school_class", "course_ref", "is_locked")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class ThreadForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        "title": "ex. Question sur le TD 3",
        "body": "ex. Je ne comprends pas la question 2…",
    }

    class Meta:
        model = Thread
        fields = ("title", "body")
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}


class ReplyForm(StyledFormMixin, forms.ModelForm):
    placeholders = {"body": "ex. Voici une piste pour répondre…"}

    class Meta:
        model = Reply
        fields = ("body", "ai_assisted")
        widgets = {"body": forms.Textarea(attrs={"rows": 6}), "ai_assisted": forms.HiddenInput()}


class ReportForm(StyledFormMixin, forms.ModelForm):
    placeholders = {"details": "ex. Décrivez le contenu signalé…"}

    class Meta:
        model = Report
        fields = ("reason", "details")
        widgets = {"details": forms.Textarea(attrs={"rows": 3})}


class MessageForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        "subject": "ex. Question sur le cours",
        "body": "ex. Bonjour, …",
    }

    recipient = forms.ModelChoiceField(label="Destinataire", queryset=User.objects.none())

    class Meta:
        model = Message
        fields = ("recipient", "subject", "body")
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        member_ids = (
            Membership.objects.filter(university=request.university, is_active=True)
            .exclude(user=request.user).values_list("user_id", flat=True)
        )
        self.fields["recipient"].queryset = User.objects.filter(pk__in=member_ids).order_by("last_name", "first_name", "email")
        self.fields["recipient"].label_from_instance = lambda user: user.get_full_name().strip() or user.email
