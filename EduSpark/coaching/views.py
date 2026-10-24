from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil


@role_required(Profil.ROLE_ETUDIANT)
def student_dashboard(request):
    return render(request, "coaching/student_dashboard.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_progress(request):
    return render(request, "coaching/student_progress.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_tasks(request):
    return render(request, "coaching/student_tasks.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_appointments(request):
    return render(request, "coaching/student_appointments.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_journal(request):
    return render(request, "coaching/student_journal.html")


@role_required(Profil.ROLE_PROF)
def prof_dashboard(request):
    return render(request, "coaching/prof_dashboard.html")


@role_required(Profil.ROLE_PROF)
def prof_followup(request):
    return render(request, "coaching/prof_followup.html")


@role_required(Profil.ROLE_PROF)
def prof_tutoring(request):
    return render(request, "coaching/prof_tutoring.html")


@role_required(Profil.ROLE_PROF)
def prof_followup_cards(request):
    return render(request, "coaching/prof_followup_cards.html")


@role_required(Profil.ROLE_PROF)
def prof_student_journal(request):
    return render(request, "coaching/prof_student_journal.html")


@role_required(Profil.ROLE_ADMIN)
def admin_dashboard(request):
    return render(request, "coaching/admin_dashboard.html")


@role_required(Profil.ROLE_ADMIN)
def admin_perseverance(request):
    return render(request, "coaching/admin_perseverance.html")


@role_required(Profil.ROLE_ADMIN)
def admin_monitoring(request):
    return render(request, "coaching/admin_monitoring.html")
