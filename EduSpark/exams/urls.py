from django.urls import path

from . import views

app_name = "exams"

urlpatterns = [
    path("etudiant/examens/", views.student_exams, name="student_exams"),
    path("etudiant/releves-de-notes/", views.student_transcript, name="student_transcript"),
    path("prof/copies/", views.prof_corrections, name="prof_corrections"),
    path("prof/sessions-examen/", views.prof_exam_sessions, name="prof_exam_sessions"),
    path("prof/releves-jurys/", views.prof_grade_sheets, name="prof_grade_sheets"),
    path("administration/sessions-examen/", views.admin_exam_sessions, name="admin_exam_sessions"),
    path("administration/statistiques/", views.admin_statistics, name="admin_statistics"),
    path("administration/releves-officiels/", views.admin_official_records, name="admin_official_records"),
]
