"""Pages d'accueil de la classe virtuelle : fil des questions, annonces, gestion des forums.

Chaque rôle garde sa page (accounts/portal_nav.py) : même vue, gabarit propre au rôle.
"""

import os
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Exists, F, Max, Min, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.decorators.http import require_POST

from accounts.decorators import etudiant_required, prof_required
from accounts.models import Membership, StudentGroup
from accounts.tenancy import Role
from accounts.view_mixins import redirect_next

from . import access
from .access import (
    ADMIN, PROF, STUDENT, announcements_for, can_manage_forum, forums_for, is_admin, is_staff_member,
    manageable_forums, replies_for, reports_for, role_kind, section_url_name, threads_for,
)
from .forms import ThreadAskForm
from .models import Announcement, AnnouncementRead, Forum, Reply, Report, Thread, ThreadVote
from .views import _context, _form_page, paginate

STAFF_ROLES = (Role.PROFESSOR, Role.UNIVERSITY_ADMIN)
FEED_PER_PAGE = 10


# ---------------------------------------------------------------------------
# Fil des questions (étudiant et professeur)
# ---------------------------------------------------------------------------

def _staff_reply_exists():
    """Sous-requête : un enseignant / l'administration a répondu (réponse visible)."""
    staff = Membership.objects.filter(
        user=OuterRef("author"), university=OuterRef("university"), role__in=STAFF_ROLES, is_active=True,
    )
    return Exists(Reply.objects.filter(thread=OuterRef("pk"), is_hidden=False).filter(Exists(staff)))


def _feed_base(request):
    return (
        threads_for(request)
        .select_related("author", "forum", "forum__school_class")
        .annotate(
            reply_count=Count("replies", filter=Q(replies__is_hidden=False), distinct=True),
            vote_count=Count("votes", distinct=True),
            has_staff_reply=_staff_reply_exists(),
            has_solution=Exists(Reply.objects.filter(thread=OuterRef("pk"), is_solution=True, is_hidden=False)),
        )
        .prefetch_related(Prefetch(
            "replies", queryset=Reply.objects.filter(is_solution=True, is_hidden=False).select_related("validated_by"),
            to_attr="solutions",
        ))
        .order_by("-is_pinned", "-created_at")
    )


def _average_first_staff_reply(request):
    staff = Membership.objects.filter(
        user=OuterRef("author"), university=OuterRef("university"), role__in=STAFF_ROLES, is_active=True,
    )
    rows = (
        replies_for(request).filter(is_hidden=False).filter(Exists(staff))
        .values("thread_id", "thread__created_at").annotate(first=Min("created_at"))
    )
    deltas = [row["first"] - row["thread__created_at"] for row in rows]
    return sum(deltas, timedelta()) / len(deltas) if deltas else None


def _format_duration(delta):
    if delta is None:
        return "—"
    minutes = max(int(delta.total_seconds() // 60), 0)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return "%d j %d h" % (days, hours)
    return "%d h %02d" % (hours, minutes) if hours else "%d min" % minutes


def _top_contributors(request):
    rows = (
        Reply.objects.filter(university=request.university, is_solution=True)
        .exclude(author__isnull=True).values("author_id").annotate(n=Count("pk")).order_by("-n")[:3]
    )
    from django.contrib.auth import get_user_model
    users = get_user_model().objects.in_bulk([row["author_id"] for row in rows])
    return [{"user": users[row["author_id"]], "count": row["n"]} for row in rows if row["author_id"] in users]


@etudiant_required
def forum_feed(request):
    base = _feed_base(request)
    threads = base
    q = request.GET.get("q", "").strip()
    if q:
        threads = threads.filter(
            Q(title__icontains=q) | Q(body__icontains=q) | Q(forum__title__icontains=q)
            | Q(forum__course_ref__icontains=q) | Q(author__first_name__icontains=q) | Q(author__last_name__icontains=q)
        )
    forum_id = request.GET.get("forum", "")
    if forum_id.isdigit():
        threads = threads.filter(forum_id=int(forum_id))
    state = request.GET.get("etat", "")
    day_ago = timezone.now() - timedelta(hours=24)
    filters = {
        "resolue": Q(is_resolved=True),
        "ouverte": Q(is_resolved=False),
        "officielle": Q(has_solution=True),
        "sans_prof": Q(has_staff_reply=False, is_resolved=False),
        "urgent": Q(has_staff_reply=False, is_resolved=False, created_at__lt=day_ago),
        "a_certifier": Q(is_resolved=True, has_solution=False),
    }
    if state in filters:
        threads = threads.filter(filters[state])
    if request.GET.get("mes") == "1":
        threads = threads.filter(author=request.user)

    forums = forums_for(request).select_related("school_class").annotate(
        n=Count("threads", filter=Q(threads__is_hidden=False), distinct=True),
    ).order_by("title")
    kind = role_kind(request)
    page = paginate(request, threads, per_page=FEED_PER_PAGE)
    pending = base.filter(has_staff_reply=False, is_resolved=False)

    context = _context(
        request, page=page, q=q, state=state, forum_id=forum_id, forums=forums,
        total=base.count(), querystring=_querystring_without_page(request),
        priority_announcements=announcements_for(request).filter(
            Q(is_pinned=True) | Q(priority=Announcement.PRIORITY_IMPORTANT)
        ).select_related("author", "school_class")[:2],
        ai_candidates=list(base.filter(is_resolved=False).values("pk", "title")[:20]),
        ai_configured=bool(os.environ.get("GROQ_API_KEY", "").strip()),
        university=request.university,
        voted_ids=set(ThreadVote.objects.filter(user=request.user, thread__in=[t.pk for t in page]).values_list("thread_id", flat=True)),
    )
    if kind == STUDENT:
        context["top_contributors"] = _top_contributors(request)
        return render(request, "community/student_forums.html", context)

    total = context["total"]
    resolved = base.filter(is_resolved=True).count()
    context.update(
        kpi_pending=pending.count(),
        kpi_overdue=pending.filter(created_at__lt=day_ago).count(),
        kpi_delay=_format_duration(_average_first_staff_reply(request)),
        kpi_announcements=announcements_for(request).count(),
        kpi_resolution=round(100 * resolved / total) if total else 0,
        kpi_resolved=resolved,
        count_sans_prof=pending.count(),
        count_urgent=pending.filter(created_at__lt=day_ago).count(),
        count_a_certifier=base.filter(is_resolved=True, has_solution=False).count(),
    )
    return render(request, "community/prof_forums.html", context)


def _querystring_without_page(request):
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


@etudiant_required
def thread_new(request):
    """« Poser une question » depuis le fil : le forum se choisit dans le formulaire."""
    initial = {}
    if request.GET.get("forum", "").isdigit():
        initial["forum"] = int(request.GET["forum"])
    form = ThreadAskForm(request.POST or None, request=request, initial=initial)
    back = reverse(section_url_name(request, "forums"))
    if request.method == "POST" and form.is_valid():
        thread = form.save(commit=False)
        thread.forum = form.cleaned_data["forum"]
        thread.author = request.user
        thread.save()
        messages.success(request, "Votre question est publiée.")
        return redirect("community:thread_detail", pk=thread.pk)
    return _form_page(
        request, form, title="Poser une question", icon="add_comment", cancel_url=back,
        submit_label="Publier la question", subtitle="Choisissez le forum du cours concerné.",
    )


@etudiant_required
@require_POST
def thread_toggle_vote(request, pk):
    thread = get_object_or_404(threads_for(request), pk=pk)
    vote, created = ThreadVote.objects.get_or_create(thread=thread, user=request.user)
    if not created:
        vote.delete()
    return redirect_next(request, reverse("community:thread_detail", args=[pk]))


# ---------------------------------------------------------------------------
# Annonces
# ---------------------------------------------------------------------------

def _announcement_stats(request, announcements):
    read_ids = set(AnnouncementRead.objects.filter(user=request.user).values_list("announcement_id", flat=True))
    latest = max((a.published_at for a in announcements), default=None)
    return read_ids, latest


def _read_rate(request):
    """Part des membres de l'université ayant lu au moins une annonce."""
    members = Membership.objects.filter(university=request.university, is_active=True).count()
    readers = AnnouncementRead.objects.filter(announcement__university=request.university).values("user").distinct().count()
    return round(100 * readers / members) if members else 0


@etudiant_required
def announcement_list(request):
    kind = role_kind(request)
    qs = announcements_for(request).select_related("author", "school_class")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q) | Q(course_ref__icontains=q))
    if request.GET.get("mes") == "1" and is_staff_member(request):
        qs = qs.filter(author=request.user)
    announcements = list(qs[:60])
    read_ids, latest = _announcement_stats(request, announcements)
    editable = {a.pk for a in announcements if access.can_edit_announcement(request, a)}
    pinned = next((a for a in announcements if a.is_pinned), None)
    feed = [a for a in announcements if a is not pinned] if kind == STUDENT else announcements

    from .forms import AnnouncementForm
    context = _context(
        request, announcements=feed, pinned=pinned, read_ids=read_ids, editable_ids=editable, q=q,
        unread_count=sum(1 for a in announcements if a.pk not in read_ids),
        pinned_count=sum(1 for a in announcements if a.is_pinned),
        category_count=len({a.category for a in announcements}),
        latest=latest, total=len(announcements),
        latest_label=timesince(latest).split(",")[0].replace(" ", " ") if latest else "—",
        total_label="%d annonce%s" % (len(announcements), "s" if len(announcements) > 1 else ""),
        categories=[(v, l) for v, l in Announcement.CATEGORY_CHOICES if any(a.category == v for a in announcements)],
        form=AnnouncementForm(request=request),
        university=request.university,
        important_count=sum(1 for a in announcements if a.priority == Announcement.PRIORITY_IMPORTANT),
        read_rate=_read_rate(request),
    )
    template = {
        STUDENT: "community/student_announcements.html",
        PROF: "community/prof_announcements.html",
        ADMIN: "community/admin_communication.html",
    }[kind]
    return render(request, template, context)


@etudiant_required
@require_POST
def announcement_mark_all_read(request):
    unread = announcements_for(request).exclude(reads__user=request.user)
    AnnouncementRead.objects.bulk_create(
        [AnnouncementRead(announcement=a, user=request.user) for a in unread], ignore_conflicts=True,
    )
    messages.success(request, "Toutes les annonces sont marquées comme lues.")
    return redirect(reverse(section_url_name(request, "announcements")))


# ---------------------------------------------------------------------------
# Gestion des forums (administration, professeurs)
# ---------------------------------------------------------------------------

@prof_required
def forum_manage(request):
    week_ago = timezone.now() - timedelta(days=7)
    forums = list(
        manageable_forums(request).select_related("school_class")
        .annotate(
            thread_count=Count("threads", distinct=True),
            last_activity=Max("threads__created_at"),
            open_reports=Count(
                "threads__reports", filter=Q(threads__reports__status=Report.STATUS_OPEN), distinct=True,
            ),
        )
        .order_by("title")
    )
    university_members = Membership.objects.filter(university=request.university, is_active=True).count()
    rows = []
    for forum in forums:
        if forum.school_class_id:
            members = StudentGroup.objects.filter(school_class_id=forum.school_class_id).aggregate(
                n=Count("students", distinct=True))["n"]
        else:
            members = university_members
        reply_count = Reply.objects.filter(thread__forum=forum).count()
        rows.append({
            "forum": forum, "members": members, "messages": forum.thread_count + reply_count,
            "status": "locked" if forum.is_locked else ("watch" if forum.open_reports else "active"),
        })
    forum_ids = [f.pk for f in forums]
    recent = (
        Thread.objects.filter(forum_id__in=forum_ids, created_at__gte=week_ago).count()
        + Reply.objects.filter(thread__forum_id__in=forum_ids, created_at__gte=week_ago).count()
    )
    from .forms import ForumForm
    return render(request, "community/admin_forum_supervision.html", _context(
        request, rows=rows, forum_count=len(rows), recent_messages=recent,
        open_reports=reports_for(request).filter(status=Report.STATUS_OPEN).count(),
        moderator_count=Membership.objects.filter(
            university=request.university, is_active=True, role=Role.PROFESSOR).count(),
        form=ForumForm(request=request), university=request.university,
    ))


@prof_required
@require_POST
def forum_toggle_lock(request, pk):
    forum = get_object_or_404(forums_for(request), pk=pk)
    if not can_manage_forum(request, forum):
        raise PermissionDenied("Vous ne gérez pas ce forum.")
    forum.is_locked = not forum.is_locked
    forum.save(update_fields=["is_locked"])
    messages.success(
        request, "Forum verrouillé : plus de nouvelles questions." if forum.is_locked else "Forum rouvert.",
    )
    return redirect("community:forum_manage")
