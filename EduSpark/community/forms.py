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
    class Meta:
        model = Announcement
        fields = ("title", "body", "category", "audience", "school_class", "course_ref", "priority", "is_pinned")
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}


class ForumForm(RequestFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Forum
        fields = ("title", "description", "school_class", "course_ref", "is_locked")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class ThreadForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Thread
        fields = ("title", "body")
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}


class ThreadAskForm(ThreadForm):
    """Poser une question depuis le fil : le forum se choisit dans le formulaire."""

    forum = forms.ModelChoiceField(label="Forum", queryset=Forum.objects.none())
    field_order = ("forum", "title", "body")

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        from .access import can_manage_forum, forums_for
        postable = [f.pk for f in forums_for(request) if not f.is_locked or can_manage_forum(request, f)]
        self.fields["forum"].queryset = Forum.objects.filter(pk__in=postable).order_by("title")
        self.fields["forum"].label_from_instance = lambda f: (f.course_ref + " • " if f.course_ref else "") + f.title


class ReplyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Reply
        fields = ("body", "ai_assisted")
        widgets = {"body": forms.Textarea(attrs={"rows": 6}), "ai_assisted": forms.HiddenInput()}


class ReportForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Report
        fields = ("reason", "details")
        widgets = {"details": forms.Textarea(attrs={"rows": 3})}


class MessageForm(StyledFormMixin, forms.ModelForm):
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
