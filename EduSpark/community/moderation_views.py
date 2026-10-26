"""File de modération : signalements des questions et réponses."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import prof_required

from .access import can_manage_forum, is_admin, reports_for, section_url_name
from .models import Report
from .views import _context, paginate

ACTION_HIDE = "masquer"
ACTION_DISMISS = "ignorer"


@prof_required
def moderation_list(request):
    base = reports_for(request).select_related("reporter", "thread__forum", "reply__thread__forum", "reply__author", "thread__author")
    status = request.GET.get("statut", Report.STATUS_OPEN)
    if status not in dict(Report.STATUS_CHOICES):
        status = Report.STATUS_OPEN
    qs = base.filter(status=status)
    reason = request.GET.get("motif", "")
    if reason in dict(Report.REASON_CHOICES):
        qs = qs.filter(reason=reason)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(details__icontains=q) | Q(thread__title__icontains=q) | Q(reply__body__icontains=q))
    counts = dict(base.values_list("status").annotate(n=Count("pk")))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "community/moderation_list.html", _context(
        request, page=paginate(request, qs), status=status, reason=reason, q=q,
        statuses=[(value, label, counts.get(value, 0)) for value, label in Report.STATUS_CHOICES],
        reasons=Report.REASON_CHOICES, querystring=params.urlencode(),
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
        messages.success(request, "Signalement classé sans suite.")
    else:
        messages.error(request, "Action inconnue.")
        return redirect(reverse(section_url_name(request, "moderation")))
    report.handled_by = request.user
    report.handled_at = timezone.now()
    report.save(update_fields=["status", "handled_by", "handled_at"])
    return redirect(reverse(section_url_name(request, "moderation")))
