from django.shortcuts import render

from .decorators import role_required
from .models import Profil


@role_required(Profil.ROLE_ETUDIANT)
def student_class(request):
    return render(request, "accounts/student_class.html")


@role_required(Profil.ROLE_PROF)
def prof_universities(request):
    return render(request, "accounts/prof_universities.html")


@role_required(Profil.ROLE_PROF)
def prof_classes(request):
    return render(request, "accounts/prof_classes.html")


@role_required(Profil.ROLE_PROF)
def prof_settings(request):
    return render(request, "accounts/prof_settings.html")


@role_required(Profil.ROLE_ADMIN)
def admin_teachers(request):
    return render(request, "accounts/admin_teachers.html")


@role_required(Profil.ROLE_ADMIN)
def admin_classes(request):
    return render(request, "accounts/admin_classes.html")


@role_required(Profil.ROLE_ADMIN)
def admin_invitations(request):
    return render(request, "accounts/admin_invitations.html")


@role_required(Profil.ROLE_ADMIN)
def admin_university(request):
    return render(request, "accounts/admin_university.html")


@role_required(Profil.ROLE_ADMIN)
def admin_platform_settings(request):
    return render(request, "accounts/admin_platform_settings.html")
