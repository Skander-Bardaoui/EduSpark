from django.urls import path

from . import views

app_name = "exercises"

urlpatterns = [
    path("etudiant/devoirs/", views.student_assignments, name="student_assignments"),
    path("etudiant/entrainement/", views.student_practice, name="student_practice"),
    path("prof/banque-exercices/", views.prof_exercise_bank, name="prof_exercise_bank"),
    path("prof/devoirs/", views.prof_assignments, name="prof_assignments"),
    path("prof/series-baremes/", views.prof_rubrics, name="prof_rubrics"),
    path("administration/banques-exercices/", views.admin_exercise_banks, name="admin_exercise_banks"),
    path("administration/categories-niveaux/", views.admin_categories, name="admin_categories"),
]
