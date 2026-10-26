"""Annonces, forums, questions et réponses.

Les pages sont partagées entre les trois rôles du portail : la navigation
(accounts/portal_nav.py) garde ses noms d'URL par rôle, et chaque nom pointe
vers la vue ci-dessous ; le contenu s'adapte au rôle (access.role_kind).
"""

import os

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import etudiant_required, prof_required

from . import access
from .access import (
    announcements_for, can_edit_announcement, can_manage_forum, can_validate_solution, forums_for,
    is_admin, is_staff_member, replies_for, role_kind, section_url_name, threads_for,
)
from .forms import AnnouncementForm, ForumForm, ReplyForm, ReportForm, ThreadForm
from .models import Announcement, Reply, Report
from .services import ai

PER_PAGE = 12


def paginate(request, queryset, per_page=PER_PAGE):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def _querystring(request):
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def _context(request, **extra):
    return {"kind": role_kind(request), "is_staff_member": is_staff_member(request), **extra}


def _confirm_delete(request, obj, *, title, warning, cancel_url, success_url, success_message):
    if request.method == "POST":
        obj.delete()
        messages.success(request, success_message)
        return redirect(success_url)
    return render(request, "community/confirm_delete.html", _context(
        request, object=obj, delete_title=title, delete_warning=warning, cancel_url=cancel_url,
    ))


def _form_page(request, form, *, title, icon, cancel_url, submit_label="Enregistrer", subtitle=""):
    return render(request, "community/form.html", _context(
        request, form=form, page_title=title, page_icon=icon, cancel_url=cancel_url,
        submit_label=submit_label, page_subtitle=subtitle,
    ))


# ---------------------------------------------------------------------------
# Annonces
# ---------------------------------------------------------------------------

@etudiant_required
def announcement_list(request):
    qs = announcements_for(request).select_related("author", "school_class")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q) | Q(course_ref__icontains=q))
    priority = request.GET.get("priorite", "")
    if priority in dict(Announcement.PRIORITY_CHOICES):
        qs = qs.filter(priority=priority)
    class_id = request.GET.get("classe", "")
    if class_id.isdigit():
        qs = qs.filter(school_class_id=int(class_id))
    mine = request.GET.get("mes") == "1" and is_staff_member(request)
    if mine:
        qs = qs.filter(author=request.user)

    page = paginate(request, qs)
    return render(request, "community/announcement_list.html", _context(
        request, page=page, q=q, priority=priority, class_id=class_id, mine=mine,
        classes=access.visible_classes(request).order_by("name"),
        priorities=Announcement.PRIORITY_CHOICES, querystring=_querystring(request),
        editable_ids={a.pk for a in page if can_edit_announcement(request, a)},
    ))


@etudiant_required
def announcement_detail(request, pk):
    announcement = get_object_or_404(
        announcements_for(request).select_related("author", "school_class"), pk=pk,
    )
    return render(request, "community/announcement_detail.html", _context(
        request, announcement=announcement,
        can_edit=can_edit_announcement(request, announcement),
        back_url=reverse(section_url_name(request, "announcements")),
    ))


@prof_required
def announcement_create(request):
    back = reverse(section_url_name(request, "announcements"))
    form = AnnouncementForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        announcement = form.save(commit=False)
        announcement.university = request.university
        announcement.author = request.user
        announcement.save()
        messages.success(request, "Annonce publiée.")
        return redirect("community:announcement_detail", pk=announcement.pk)
    return _form_page(request, form, title="Nouvelle annonce", icon="campaign", cancel_url=back, submit_label="Publier")


@prof_required
def announcement_edit(request, pk):
    announcement = get_object_or_404(announcements_for(request), pk=pk)
    if not can_edit_announcement(request, announcement):
        raise PermissionDenied("Vous ne pouvez modifier que vos propres annonces.")
    form = AnnouncementForm(request.POST or None, instance=announcement, request=request)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Annonce modifiée.")
        return redirect("community:announcement_detail", pk=pk)
    return _form_page(
        request, form, title="Modifier l'annonce", icon="edit",
        cancel_url=reverse("community:announcement_detail", args=[pk]),
    )


@prof_required
def announcement_delete(request, pk):
    announcement = get_object_or_404(announcements_for(request), pk=pk)
    if not can_edit_announcement(request, announcement):
        raise PermissionDenied("Vous ne pouvez supprimer que vos propres annonces.")
    return _confirm_delete(
        request, announcement, title="Supprimer l'annonce",
        warning="L'annonce disparaîtra du portail de tous ses destinataires.",
        cancel_url=reverse("community:announcement_detail", args=[pk]),
        success_url=reverse(section_url_name(request, "announcements")),
        success_message="Annonce supprimée.",
    )


# ---------------------------------------------------------------------------
# Forums
# ---------------------------------------------------------------------------

@etudiant_required
def forum_list(request):
    visible_threads = Q(threads__is_hidden=False)
    qs = (
        forums_for(request).select_related("school_class")
        .annotate(
            thread_count=Count("threads", filter=visible_threads, distinct=True),
            last_activity=Max("threads__created_at", filter=visible_threads),
        )
        .order_by("-last_activity", "title")
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(course_ref__icontains=q))
    class_id = request.GET.get("classe", "")
    if class_id == "general":
        qs = qs.filter(school_class__isnull=True)
    elif class_id.isdigit():
        qs = qs.filter(school_class_id=int(class_id))

    return render(request, "community/forum_list.html", _context(
        request, page=paginate(request, qs), q=q, class_id=class_id, querystring=_querystring(request),
        classes=access.visible_classes(request).order_by("name"),
    ))


@etudiant_required
def forum_detail(request, pk):
    forum = get_object_or_404(forums_for(request).select_related("school_class"), pk=pk)
    qs = (
        threads_for(request).filter(forum=forum).select_related("author")
        .annotate(
            reply_count=Count("replies", filter=Q(replies__is_hidden=False), distinct=True),
            last_reply=Max("replies__created_at", filter=Q(replies__is_hidden=False)),
        )
        .order_by("-is_pinned", "-created_at")  # un annotate avec agrégat ignore Meta.ordering
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
    state = request.GET.get("etat", "")
    if state == "sans_reponse":
        qs = qs.filter(reply_count=0)
    elif state == "resolue":
        qs = qs.filter(is_resolved=True)
    elif state == "ouverte":
        qs = qs.filter(is_resolved=False)
    mine = request.GET.get("mes") == "1"
    if mine:
        qs = qs.filter(author=request.user)

    return render(request, "community/forum_detail.html", _context(
        request, forum=forum, page=paginate(request, qs), q=q, state=state, mine=mine,
        can_manage=can_manage_forum(request, forum), querystring=_querystring(request),
        can_post=not forum.is_locked or can_manage_forum(request, forum),
        back_url=reverse(section_url_name(request, "forums")),
    ))


@prof_required
def forum_create(request):
    form = ForumForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        forum = form.save(commit=False)
        forum.university = request.university
        forum.created_by = request.user
        forum.save()
        messages.success(request, "Forum créé.")
        return redirect("community:forum_detail", pk=forum.pk)
    return _form_page(
        request, form, title="Nouveau forum", icon="forum",
        cancel_url=reverse(section_url_name(request, "forums")), submit_label="Créer le forum",
        subtitle="Rattachez-le à une classe pour que seuls ses membres le voient.",
    )


@prof_required
def forum_edit(request, pk):
    forum = get_object_or_404(forums_for(request), pk=pk)
    if not can_manage_forum(request, forum):
        raise PermissionDenied("Vous ne gérez pas ce forum.")
    form = ForumForm(request.POST or None, instance=forum, request=request)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Forum modifié.")
        return redirect("community:forum_detail", pk=pk)
    return _form_page(
        request, form, title="Modifier le forum", icon="edit",
        cancel_url=reverse("community:forum_detail", args=[pk]),
    )


@prof_required
def forum_delete(request, pk):
    forum = get_object_or_404(forums_for(request), pk=pk)
    if not can_manage_forum(request, forum):
        raise PermissionDenied("Vous ne gérez pas ce forum.")
    return _confirm_delete(
        request, forum, title="Supprimer le forum",
        warning="Toutes les questions et réponses de ce forum seront supprimées définitivement.",
        cancel_url=reverse("community:forum_detail", args=[pk]),
        success_url=reverse(section_url_name(request, "forums")),
        success_message="Forum supprimé.",
    )


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

def _can_post(request, forum):
    return not forum.is_locked or can_manage_forum(request, forum)


def _is_author(request, obj):
    return obj.author_id == request.user.pk


@etudiant_required
def thread_create(request, forum_pk):
    forum = get_object_or_404(forums_for(request), pk=forum_pk)
    back = reverse("community:forum_detail", args=[forum.pk])
    if not _can_post(request, forum):
        messages.error(request, "Ce forum est verrouillé : on ne peut plus poser de question.")
        return redirect(back)
    form = ThreadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        thread = form.save(commit=False)
        thread.forum = forum
        thread.author = request.user
        thread.save()
        messages.success(request, "Votre question est publiée.")
        return redirect("community:thread_detail", pk=thread.pk)
    return _form_page(
        request, form, title="Poser une question", icon="add_comment", cancel_url=back,
        submit_label="Publier la question", subtitle="Forum : %s" % forum.title,
    )


@etudiant_required
def thread_detail(request, pk):
    thread = get_object_or_404(threads_for(request).select_related("forum", "author", "forum__school_class"), pk=pk)
    replies = replies_for(request).filter(thread=thread).select_related("author")
    if not is_staff_member(request):
        replies = replies.filter(is_hidden=False)
    forum = thread.forum
    can_manage = can_manage_forum(request, forum)
    return render(request, "community/thread_detail.html", _context(
        request, thread=thread, forum=forum, replies=replies, can_manage=can_manage,
        can_validate=can_validate_solution(request, forum),
        has_solution=any(r.is_solution for r in replies),
        can_post=_can_post(request, forum), is_author=_is_author(request, thread),
        reply_form=ReplyForm(),
        back_url=reverse("community:forum_detail", args=[forum.pk]),
        ai_configured=bool(os.environ.get("GROQ_API_KEY", "").strip()),
    ))


@etudiant_required
def thread_edit(request, pk):
    thread = get_object_or_404(threads_for(request).select_related("forum"), pk=pk)
    if not _is_author(request, thread):
        raise PermissionDenied("Seul l'auteur peut modifier sa question.")
    form = ThreadForm(request.POST or None, instance=thread)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Question modifiée.")
        return redirect("community:thread_detail", pk=pk)
    return _form_page(
        request, form, title="Modifier la question", icon="edit",
        cancel_url=reverse("community:thread_detail", args=[pk]),
    )


@etudiant_required
def thread_delete(request, pk):
    thread = get_object_or_404(threads_for(request).select_related("forum"), pk=pk)
    if not (_is_author(request, thread) or can_manage_forum(request, thread.forum)):
        raise PermissionDenied("Vous ne pouvez pas supprimer cette question.")
    return _confirm_delete(
        request, thread, title="Supprimer la question",
        warning="La question et toutes ses réponses seront supprimées définitivement.",
        cancel_url=reverse("community:thread_detail", args=[pk]),
        success_url=reverse("community:forum_detail", args=[thread.forum_id]),
        success_message="Question supprimée.",
    )


def _thread_for_moderation(request, pk):
    thread = get_object_or_404(threads_for(request).select_related("forum"), pk=pk)
    if not can_manage_forum(request, thread.forum):
        raise PermissionDenied("Réservé à la modération de ce forum.")
    return thread


@etudiant_required
@require_POST
def thread_toggle_resolved(request, pk):
    thread = get_object_or_404(threads_for(request).select_related("forum"), pk=pk)
    if not (_is_author(request, thread) or can_manage_forum(request, thread.forum)):
        raise PermissionDenied("Seul l'auteur ou la modération peut changer ce statut.")
    has_validated_solution = thread.replies.filter(is_solution=True).exists()
    if thread.is_resolved and has_validated_solution and not can_validate_solution(request, thread.forum):
        messages.error(request, "Une solution a été validée par un professeur : seul un professeur peut rouvrir cette question.")
        return redirect("community:thread_detail", pk=pk)
    thread.is_resolved = not thread.is_resolved
    thread.save(update_fields=["is_resolved", "updated_at"])
    if not thread.is_resolved:
        thread.replies.filter(is_solution=True).update(is_solution=False, validated_by=None, validated_at=None)
    messages.success(request, "Question marquée comme résolue." if thread.is_resolved else "Question rouverte.")
    return redirect("community:thread_detail", pk=pk)


@prof_required
@require_POST
def thread_toggle_pin(request, pk):
    thread = _thread_for_moderation(request, pk)
    thread.is_pinned = not thread.is_pinned
    thread.save(update_fields=["is_pinned", "updated_at"])
    messages.success(request, "Question épinglée." if thread.is_pinned else "Question désépinglée.")
    return redirect("community:thread_detail", pk=pk)


@prof_required
@require_POST
def thread_toggle_hidden(request, pk):
    thread = _thread_for_moderation(request, pk)
    thread.is_hidden = not thread.is_hidden
    thread.save(update_fields=["is_hidden", "updated_at"])
    messages.success(request, "Question masquée aux étudiants." if thread.is_hidden else "Question de nouveau visible.")
    return redirect("community:thread_detail", pk=pk)


# ---------------------------------------------------------------------------
# Réponses
# ---------------------------------------------------------------------------

@etudiant_required
@require_POST
def reply_create(request, thread_pk):
    thread = get_object_or_404(threads_for(request).select_related("forum"), pk=thread_pk)
    if not _can_post(request, thread.forum):
        messages.error(request, "Ce forum est verrouillé : on ne peut plus répondre.")
        return redirect("community:thread_detail", pk=thread.pk)
    form = ReplyForm(request.POST)
    if form.is_valid():
        reply = form.save(commit=False)
        reply.thread = thread
        reply.author = request.user
        reply.save()
        messages.success(request, "Votre réponse est publiée.")
    else:
        messages.error(request, "La réponse ne peut pas être vide.")
    return redirect("community:thread_detail", pk=thread.pk)


@etudiant_required
def reply_edit(request, pk):
    reply = get_object_or_404(replies_for(request).select_related("thread"), pk=pk)
    if not _is_author(request, reply):
        raise PermissionDenied("Seul l'auteur peut modifier sa réponse.")
    form = ReplyForm(request.POST or None, instance=reply)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Réponse modifiée.")
        return redirect("community:thread_detail", pk=reply.thread_id)
    return _form_page(
        request, form, title="Modifier la réponse", icon="edit",
        cancel_url=reverse("community:thread_detail", args=[reply.thread_id]),
    )


@etudiant_required
def reply_delete(request, pk):
    reply = get_object_or_404(replies_for(request).select_related("thread__forum"), pk=pk)
    if not (_is_author(request, reply) or can_manage_forum(request, reply.thread.forum)):
        raise PermissionDenied("Vous ne pouvez pas supprimer cette réponse.")
    return _confirm_delete(
        request, reply, title="Supprimer la réponse", warning="La réponse sera supprimée définitivement.",
        cancel_url=reverse("community:thread_detail", args=[reply.thread_id]),
        success_url=reverse("community:thread_detail", args=[reply.thread_id]),
        success_message="Réponse supprimée.",
    )


@prof_required
@require_POST
def reply_mark_solution(request, pk):
    """Un professeur du forum valide (ou retire) la solution ; son nom est conservé."""
    reply = get_object_or_404(replies_for(request).select_related("thread__forum"), pk=pk)
    thread = reply.thread
    if not can_validate_solution(request, thread.forum):
        raise PermissionDenied("Seul un professeur de ce cours peut valider une solution.")
    if reply.is_solution:
        reply.is_solution, reply.validated_by, reply.validated_at = False, None, None
        reply.save(update_fields=["is_solution", "validated_by", "validated_at", "updated_at"])
        messages.success(request, "Validation retirée.")
    else:
        thread.replies.filter(is_solution=True).update(is_solution=False, validated_by=None, validated_at=None)
        reply.is_solution, reply.validated_by, reply.validated_at = True, request.user, timezone.now()
        reply.save(update_fields=["is_solution", "validated_by", "validated_at", "updated_at"])
        thread.is_resolved = True
        thread.save(update_fields=["is_resolved", "updated_at"])
        messages.success(request, "Solution validée : votre nom sera affiché à côté.")
    return redirect("community:thread_detail", pk=thread.pk)


@prof_required
@require_POST
def reply_toggle_hidden(request, pk):
    reply = get_object_or_404(replies_for(request).select_related("thread__forum"), pk=pk)
    if not can_manage_forum(request, reply.thread.forum):
        raise PermissionDenied("Réservé à la modération de ce forum.")
    reply.is_hidden = not reply.is_hidden
    reply.save(update_fields=["is_hidden", "updated_at"])
    messages.success(request, "Réponse masquée aux étudiants." if reply.is_hidden else "Réponse de nouveau visible.")
    return redirect("community:thread_detail", pk=reply.thread_id)


# ---------------------------------------------------------------------------
# Assistant IA : « Suggérer une réponse »
# ---------------------------------------------------------------------------

@etudiant_required
@require_POST
def thread_ai_suggestion(request, pk):
    """Renvoie un brouillon de réponse en JSON ; rien n'est enregistré ici."""
    thread = get_object_or_404(threads_for(request).select_related("forum"), pk=pk)
    if not _can_post(request, thread.forum):
        return JsonResponse({"ok": False, "error": "Ce forum est verrouillé."}, status=403)
    replies = list(replies_for(request).filter(thread=thread, is_hidden=False).order_by("created_at")[:20])
    try:
        text = ai.suggest_reply(thread, replies)
    except ai.AIUnavailable:
        return JsonResponse({
            "ok": False,
            "error": "L'assistant IA est indisponible pour le moment. Vous pouvez répondre vous-même ci-dessous.",
        }, status=503)
    return JsonResponse({"ok": True, "text": text})


# ---------------------------------------------------------------------------
# Signalements
# ---------------------------------------------------------------------------

@etudiant_required
def report_create(request, target, pk):
    if target == "question":
        obj = get_object_or_404(threads_for(request).select_related("forum"), pk=pk)
        thread = obj
    elif target == "reponse":
        obj = get_object_or_404(replies_for(request).select_related("thread__forum"), pk=pk, is_hidden=False)
        thread = obj.thread
    else:
        raise PermissionDenied
    back = reverse("community:thread_detail", args=[thread.pk])
    if obj.author_id == request.user.pk:
        messages.error(request, "Vous ne pouvez pas signaler votre propre message.")
        return redirect(back)
    existing = Report.objects.filter(reporter=request.user, status=Report.STATUS_OPEN, **{
        "thread" if target == "question" else "reply": obj
    })
    if existing.exists():
        messages.info(request, "Vous avez déjà signalé ce message ; la modération va le traiter.")
        return redirect(back)

    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        if target == "question":
            report.thread = obj
        else:
            report.reply = obj
        report.save()
        messages.success(request, "Merci : le signalement a été transmis à la modération.")
        return redirect(back)
    return _form_page(
        request, form, title="Signaler un message", icon="flag", cancel_url=back, submit_label="Envoyer le signalement",
        subtitle="La modération examinera ce message ; votre nom ne sera pas montré à son auteur.",
    )
