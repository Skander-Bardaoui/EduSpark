from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil


@role_required(Profil.ROLE_ETUDIANT)
def student_exams(request):
    return render(request, "exams/student_exams.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_transcript(request):
    return render(request, "exams/student_transcript.html")


@role_required(Profil.ROLE_PROF)
def prof_corrections(request):
    return render(request, "exams/prof_corrections.html")


@role_required(Profil.ROLE_PROF)
def prof_exam_sessions(request):
    return render(request, "exams/prof_exam_sessions.html")


@role_required(Profil.ROLE_PROF)
def prof_grade_sheets(request):
    return render(request, "exams/prof_grade_sheets.html")


@role_required(Profil.ROLE_ADMIN)
def admin_exam_sessions(request):
    return render(request, "exams/admin_exam_sessions.html")


@role_required(Profil.ROLE_ADMIN)
def admin_statistics(request):
    return render(request, "exams/admin_statistics.html")


@role_required(Profil.ROLE_ADMIN)
def admin_official_records(request):
    return render(request, "exams/admin_official_records.html")
