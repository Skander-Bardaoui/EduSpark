"""File de modération : signalements des questions et réponses."""

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import prof_required

from .access import ADMIN, can_manage_forum, is_admin, reports_for, role_kind, section_url_name
from .models import Reply, Report, Thread
from .views import _context

ACTION_HIDE = "masquer"
ACTION_DISMISS = "ignorer"
HIGH_PRIORITY_REASONS = (Report.REASON_DISRESPECT, Report.REASON_CHEATING)
MAX_REPORTS = 100


def _average_delay(handled):
    deltas = [r.handled_at - r.created_at for r in handled if r.handled_at]
    if not deltas:
        return "—"
    minutes = int((sum(deltas, timedelta()) / len(deltas)).total_seconds() // 60)
    return "%d h %02d" % divmod(minutes, 60) if minutes >= 60 else "%d min" % minutes


@prof_required
def moderation_list(request):
    base = reports_for(request).select_related(
        "reporter", "thread__forum", "thread__author", "reply__thread__forum", "reply__author",
    )
    reports = list(base.order_by("status", "-created_at")[:MAX_REPORTS])
    for report in reports:
        report.forum_obj = report.forum
        report.is_high = report.reason in HIGH_PRIORITY_REASONS
        report.kind_tag = "reponse" if report.reply_id else "question"
        report.excerpt = (report.reply.body if report.reply_id else report.thread.body)
        report.author_obj = report.reply.author if report.reply_id else report.thread.author

    open_reports = [r for r in reports if r.status == Report.STATUS_OPEN]
    handled = [r for r in reports if r.status != Report.STATUS_OPEN]
    week_ago = timezone.now() - timedelta(days=7)
    forum_ids = {r.forum_obj.pk for r in reports}
    forums_hidden = (
        Thread.objects.filter(forum_id__in=forum_ids, is_hidden=True).count()
        + Reply.objects.filter(thread__forum_id__in=forum_ids, is_hidden=True).count()
    )
    template = "community/admin_reports.html" if role_kind(request) == ADMIN else "community/prof_moderation.html"
    return render(request, template, _context(
        request, reports=reports, open_count=len(open_reports),
        high_count=sum(1 for r in open_reports if r.is_high),
        treated_week=sum(1 for r in handled if r.handled_at and r.handled_at >= week_ago),
        treated_total=len(handled), kept_count=sum(1 for r in handled if r.status == Report.STATUS_DISMISSED),
        hidden_count=sum(1 for r in handled if r.status == Report.STATUS_ACTIONED),
        average_delay=_average_delay(handled), forums_hidden=forums_hidden,
        concerned_forums=sorted({r.forum_obj.title for r in open_reports}),
        university=request.university,
    ))


@prof_required
@require_POST
def report_resolve(request, pk):
    report = get_object_or_404(reports_for(request).select_related("thread__forum", "reply__thread__forum"), pk=pk)
    if not (is_admin(request) or can_manage_forum(request, report.forum)):
        raise PermissionDenied("Réservé à la modération de ce forum.")
    action = request.POST.get("action")
    if action == ACTION_HIDE:
        target = report.target
        target.is_hidden = True
        target.save(update_fields=["is_hidden", "updated_at"])
        report.status = Report.STATUS_ACTIONED
        messages.success(request, "Contenu masqué aux étudiants.")
    elif action == ACTION_DISMISS:
        report.status = Report.STATUS_DISMISSED
        messages.success(request, "Contenu conservé : signalement classé sans suite.")
    else:
        messages.error(request, "Action inconnue.")
        return redirect(reverse(section_url_name(request, "moderation")))
    report.handled_by = request.user
    report.handled_at = timezone.now()
    report.save(update_fields=["status", "handled_by", "handled_at"])
    return redirect(reverse(section_url_name(request, "moderation")))
