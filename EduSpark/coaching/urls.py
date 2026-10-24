from django.urls import path

from . import views

app_name = "coaching"

urlpatterns = [
    path("etudiant/tableau-de-bord/", views.student_dashboard, name="student_dashboard"),
    path("etudiant/progression/", views.student_progress, name="student_progress"),
    path("etudiant/taches/", views.student_tasks, name="student_tasks"),
    path("etudiant/rendez-vous/", views.student_appointments, name="student_appointments"),
    path("etudiant/journal/", views.student_journal, name="student_journal"),
    path("prof/tableau-de-bord/", views.prof_dashboard, name="prof_dashboard"),
    path("prof/suivi/", views.prof_followup, name="prof_followup"),
    path("prof/tutorat/", views.prof_tutoring, name="prof_tutoring"),
    path("prof/fiches-difficultes/", views.prof_followup_cards, name="prof_followup_cards"),
    path("prof/journal-etudiants/", views.prof_student_journal, name="prof_student_journal"),
    path("administration/tableau-de-bord/", views.admin_dashboard, name="admin_dashboard"),
    path("administration/perseverance/", views.admin_perseverance, name="admin_perseverance"),
    path("administration/suivi/", views.admin_monitoring, name="admin_monitoring"),
]
