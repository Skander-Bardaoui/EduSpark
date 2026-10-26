"""Messagerie privée entre membres d'une même université."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import etudiant_required
from accounts.models import Membership

from .access import messages_for, role_kind, section_url_name
from .forms import MessageForm
from .models import Message
from .views import _context, _form_page, paginate

User = get_user_model()


def _own_messages(request):
    """Messages de l'utilisateur, hors ceux qu'il a supprimés de sa boîte."""
    return messages_for(request).filter(
        Q(recipient=request.user, recipient_deleted=False) | Q(sender=request.user, sender_deleted=False)
    ).select_related("sender", "recipient")


@etudiant_required
def message_inbox(request):
    folder = "envoyes" if request.GET.get("dossier") == "envoyes" else "recus"
    qs = _own_messages(request)
    qs = qs.filter(sender=request.user) if folder == "envoyes" else qs.filter(recipient=request.user)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(subject__icontains=q) | Q(body__icontains=q))
    if folder == "recus" and request.GET.get("etat") == "non_lus":
        qs = qs.filter(read_at__isnull=True)
    unread = messages_for(request).filter(recipient=request.user, recipient_deleted=False, read_at__isnull=True).count()
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "community/message_list.html", _context(
        request, page=paginate(request, qs), folder=folder, q=q, unread=unread,
        only_unread=request.GET.get("etat") == "non_lus", querystring=params.urlencode(),
    ))


@etudiant_required
def message_detail(request, pk):
    message = get_object_or_404(_own_messages(request), pk=pk)
    if message.recipient_id == request.user.pk and message.read_at is None:
        message.read_at = timezone.now()
        message.save(update_fields=["read_at"])
    other = message.sender if message.recipient_id == request.user.pk else message.recipient
    return render(request, "community/message_detail.html", _context(
        request, message=message, other=other, is_recipient=message.recipient_id == request.user.pk,
        back_url=reverse(section_url_name(request, "messages")),
    ))


@etudiant_required
def message_create(request):
    back = reverse(section_url_name(request, "messages"))
    initial = {}
    recipient_id = request.GET.get("a", "")
    if recipient_id.isdigit():
        initial["recipient"] = int(recipient_id)
    subject = request.GET.get("sujet", "")[:200]
    if subject:
        initial["subject"] = subject
    form = MessageForm(request.POST or None, request=request, initial=initial)
    if request.method == "POST" and form.is_valid():
        message = form.save(commit=False)
        message.university = request.university
        message.sender = request.user
        message.save()
        messages.success(request, "Message envoyé.")
        return redirect(back + "?dossier=envoyes")
    return _form_page(
        request, form, title="Nouveau message", icon="send", cancel_url=back, submit_label="Envoyer",
        subtitle="Vous pouvez écrire à tous les membres de %s." % request.university.name,
    )


@etudiant_required
@require_POST
def message_delete(request, pk):
    message = get_object_or_404(_own_messages(request), pk=pk)
    if message.sender_id == request.user.pk:
        message.sender_deleted = True
    if message.recipient_id == request.user.pk:
        message.recipient_deleted = True
    if message.sender_deleted and message.recipient_deleted:
        message.delete()
    else:
        message.save(update_fields=["sender_deleted", "recipient_deleted"])
    messages.success(request, "Message supprimé de votre boîte.")
    return redirect(reverse(section_url_name(request, "messages")))
