from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil


@role_required(Profil.ROLE_ETUDIANT)
def student_catalogue(request):
    return render(request, "courses/student_catalogue.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_timetable(request):
    return render(request, "courses/student_timetable.html")


@role_required(Profil.ROLE_PROF)
def prof_course(request):
    return render(request, "courses/prof_course.html")


@role_required(Profil.ROLE_PROF)
def prof_timetable(request):
    return render(request, "courses/prof_timetable.html")


@role_required(Profil.ROLE_PROF)
def prof_subjects(request):
    return render(request, "courses/prof_subjects.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_course_materials(request):
    return render(request, "courses/student_course_materials.html")


@role_required(Profil.ROLE_PROF)
def prof_course_materials(request):
    return render(request, "courses/prof_course_materials.html")


@role_required(Profil.ROLE_ADMIN)
def admin_timetable(request):
    return render(request, "courses/admin_timetable.html")


@role_required(Profil.ROLE_ADMIN)
def admin_program_offer(request):
    return render(request, "courses/admin_program_offer.html")


@role_required(Profil.ROLE_ADMIN)
def admin_courses(request):
    return render(request, "courses/admin_courses.html")
