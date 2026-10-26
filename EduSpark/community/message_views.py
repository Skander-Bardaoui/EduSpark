"""Messagerie privée entre membres d'une même université, présentée en conversations."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import formats, timezone
from django.views.decorators.http import require_POST

from accounts.decorators import etudiant_required
from accounts.models import Membership
from accounts.tenancy import Role

from .access import messages_for, section_url_name
from .forms import MessageForm
from .models import Message
from .templatetags.community_extras import display_name, initials, tone
from .views import _context, _form_page

User = get_user_model()
MAX_CONVERSATIONS = 50
MAX_MESSAGES = 100

ROLE_LABELS = {
    Role.PROFESSOR: "Enseignant",
    Role.STUDENT: "Étudiant",
    Role.UNIVERSITY_ADMIN: "Administration",
}


def _own_messages(request):
    """Messages de l'utilisateur, hors ceux qu'il a supprimés de sa boîte."""
    return messages_for(request).filter(
        Q(recipient=request.user, recipient_deleted=False) | Q(sender=request.user, sender_deleted=False)
    ).select_related("sender", "recipient")


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _payload(request, message, roles=None):
    """Un message sous forme JSON, vu par l'utilisateur courant (pour l'affichage en direct)."""
    mine = message.sender_id == request.user.pk
    other = message.recipient if mine else message.sender
    if roles is None:
        roles = dict(Membership.objects.filter(
            university=request.university, user=other, is_active=True,
        ).values_list("user_id", "role"))
    local = timezone.localtime(message.created_at)
    return {
        "id": message.pk, "mine": mine, "other_id": other.pk, "other_name": display_name(other),
        "other_initials": initials(other), "other_tone": tone(other),
        "role_label": ROLE_LABELS.get(roles.get(other.pk), "Membre"),
        "subject": message.subject, "body": message.body, "read": message.read_at is not None,
        "time": formats.date_format(local, "d/m · H:i"), "short_time": formats.date_format(local, "d/m H:i"),
    }


def _conversation_with(request, user_id):
    return _own_messages(request).filter(
        Q(sender_id=user_id, recipient=request.user) | Q(recipient_id=user_id, sender=request.user)
    )


@etudiant_required
def message_inbox(request):
    me = request.user
    conversations = {}
    last_id = 0
    for message in _own_messages(request).order_by("created_at"):
        last_id = max(last_id, message.pk)
        other = message.recipient if message.sender_id == me.pk else message.sender
        conv = conversations.setdefault(other.pk, {"user": other, "messages": [], "unread": 0})
        conv["messages"].append(message)
        if message.recipient_id == me.pk and message.read_at is None:
            conv["unread"] += 1
    ordered = sorted(conversations.values(), key=lambda c: c["messages"][-1].created_at, reverse=True)[:MAX_CONVERSATIONS]

    roles = dict(Membership.objects.filter(
        university=request.university, user_id__in=[c["user"].pk for c in ordered], is_active=True,
    ).values_list("user_id", "role"))
    for conv in ordered:
        conv["last"] = conv["messages"][-1]
        conv["messages"] = conv["messages"][-MAX_MESSAGES:]
        conv["role_label"] = ROLE_LABELS.get(roles.get(conv["user"].pk), "Membre")

    active = request.GET.get("avec", "")
    active_id = int(active) if active.isdigit() and int(active) in conversations else (ordered[0]["user"].pk if ordered else None)
    return render(request, "community/message_list.html", _context(
        request, conversations=ordered, active_id=active_id, last_id=last_id,
        unread_total=sum(c["unread"] for c in ordered),
        form=MessageForm(request=request, initial={"recipient": request.GET.get("a") or None}),
        open_modal=bool(request.GET.get("a")), university=request.university,
    ))


@etudiant_required
def message_create(request):
    """Nouveau message (fenêtre de la messagerie) ou réponse rapide dans une conversation."""
    back = reverse(section_url_name(request, "messages"))
    form = MessageForm(request.POST or None, request=request, initial={
        "recipient": request.GET.get("a") or None, "subject": request.GET.get("sujet", "")[:200],
    })
    if request.method == "POST" and form.is_valid():
        message = form.save(commit=False)
        message.university = request.university
        message.sender = request.user
        message.save()
        if _is_ajax(request):
            return JsonResponse({"ok": True, "message": _payload(request, message)})
        messages.success(request, "Message envoyé.")
        return redirect("%s?avec=%d" % (back, message.recipient_id))
    if request.method == "POST" and _is_ajax(request):
        return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)
    return _form_page(
        request, form, title="Nouveau message", icon="send", cancel_url=back, submit_label="Envoyer",
        subtitle="Vous pouvez écrire à tous les membres de %s." % request.university.name,
    )


@etudiant_required
@require_POST
def conversation_mark_read(request, user_id):
    updated = _conversation_with(request, user_id).filter(recipient=request.user, read_at__isnull=True).update(
        read_at=timezone.now(),
    )
    return JsonResponse({"ok": True, "updated": updated})


@etudiant_required
@require_POST
def conversation_delete(request, user_id):
    """Retire la conversation de la boîte de l'utilisateur ; supprime ce que les deux côtés ont retiré."""
    conversation = _conversation_with(request, user_id)
    if not conversation.exists():
        raise Http404("Conversation introuvable.")
    conversation.filter(sender=request.user).update(sender_deleted=True)
    conversation.filter(recipient=request.user).update(recipient_deleted=True)
    Message.objects.filter(university=request.university, sender_deleted=True, recipient_deleted=True).delete()
    messages.success(request, "Conversation supprimée de votre boîte.")
    return redirect(reverse(section_url_name(request, "messages")))


@etudiant_required
def message_poll(request):
    """Mises à jour en direct : nouveaux messages, accusés de lecture, total de non lus.

    Le navigateur interroge cette URL toutes les quelques secondes avec le dernier
    identifiant reçu (« apres ») et les messages envoyés dont il attend la lecture (« suivis »).
    """
    after = request.GET.get("apres", "")
    after = int(after) if after.isdigit() else 0
    followed = [int(x) for x in request.GET.get("suivis", "").split(",") if x.isdigit()][:100]

    fresh = list(_own_messages(request).filter(pk__gt=after).order_by("pk")[:50])
    other_ids = {(m.recipient_id if m.sender_id == request.user.pk else m.sender_id) for m in fresh}
    roles = dict(Membership.objects.filter(
        university=request.university, user_id__in=other_ids, is_active=True,
    ).values_list("user_id", "role"))
    read_ids = list(Message.objects.filter(
        pk__in=followed, sender=request.user, read_at__isnull=False,
    ).values_list("pk", flat=True))
    unread_total = messages_for(request).filter(
        recipient=request.user, recipient_deleted=False, read_at__isnull=True,
    ).count()
    response = JsonResponse({
        "messages": [_payload(request, m, roles) for m in fresh],
        "read_ids": read_ids, "unread_total": unread_total,
    })
    response["Cache-Control"] = "no-store"
    return response
