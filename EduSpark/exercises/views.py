from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil


@role_required(Profil.ROLE_ETUDIANT)
def student_assignments(request):
    return render(request, "exercises/student_assignments.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_practice(request):
    return render(request, "exercises/student_practice.html")


@role_required(Profil.ROLE_PROF)
def prof_exercise_bank(request):
    return render(request, "exercises/prof_exercise_bank.html")


@role_required(Profil.ROLE_PROF)
def prof_assignments(request):
    return render(request, "exercises/prof_assignments.html")


@role_required(Profil.ROLE_PROF)
def prof_rubrics(request):
    return render(request, "exercises/prof_rubrics.html")


@role_required(Profil.ROLE_ADMIN)
def admin_exercise_banks(request):
    return render(request, "exercises/admin_exercise_banks.html")


@role_required(Profil.ROLE_ADMIN)
def admin_categories(request):
    return render(request, "exercises/admin_categories.html")
