from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil


@role_required(Profil.ROLE_ETUDIANT)
def student_forums(request):
    return render(request, "community/student_forums.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_announcements(request):
    return render(request, "community/student_announcements.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_messages(request):
    return render(request, "community/student_messages.html")


@role_required(Profil.ROLE_PROF)
def prof_forums(request):
    return render(request, "community/prof_forums.html")


@role_required(Profil.ROLE_PROF)
def prof_announcements(request):
    return render(request, "community/prof_announcements.html")


@role_required(Profil.ROLE_PROF)
def prof_messages(request):
    return render(request, "community/prof_messages.html")


@role_required(Profil.ROLE_PROF)
def prof_moderation(request):
    return render(request, "community/prof_moderation.html")


@role_required(Profil.ROLE_ADMIN)
def admin_communication(request):
    return render(request, "community/admin_communication.html")


@role_required(Profil.ROLE_ADMIN)
def admin_forum_supervision(request):
    return render(request, "community/admin_forum_supervision.html")


@role_required(Profil.ROLE_ADMIN)
def admin_reports(request):
    return render(request, "community/admin_reports.html")
