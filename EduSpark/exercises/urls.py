from django.urls import path
from . import views

app_name = "exercises"

urlpatterns = [
    # ── Étudiant ──────────────────────────────────────────────────────────
    path("etudiant/devoirs/", views.student_assignments, name="student_assignments"),
    path("etudiant/devoirs/<int:pk>/", views.student_assignment_detail, name="student_assignment_detail"),
    path("etudiant/devoirs/<int:pk>/pdf/", views.student_assignment_pdf, name="student_assignment_pdf"),
    path("etudiant/devoirs/generer-ia/", views.student_assignment_generate_ia, name="student_assignment_generate_ia"),
    path("etudiant/entrainement/", views.student_practice, name="student_practice"),

    # ── Enseignant — Exercices ────────────────────────────────────────────
    path("prof/banque-exercices/", views.prof_exercise_bank, name="prof_exercise_bank"),
    path("prof/exercices/creer/", views.prof_exercise_create, name="prof_exercise_create"),
    path("prof/exercices/<int:pk>/modifier/", views.prof_exercise_update, name="prof_exercise_update"),
    path("prof/exercices/<int:pk>/supprimer/", views.prof_exercise_delete, name="prof_exercise_delete"),
    path("prof/exercices/generer-ia/", views.prof_exercise_ai_generate, name="prof_exercise_ai_generate"),

    # ── Enseignant — Devoirs ─────────────────────────────────────────────
    path("prof/devoirs/", views.prof_assignments, name="prof_assignments"),
    path("prof/devoirs/creer/", views.prof_assignment_create, name="prof_assignment_create"),
    path("prof/devoirs/<int:pk>/modifier/", views.prof_assignment_update, name="prof_assignment_update"),
    path("prof/devoirs/<int:pk>/supprimer/", views.prof_assignment_delete, name="prof_assignment_delete"),

    # ── Enseignant — Barèmes & Séries ────────────────────────────────────
    path("prof/series-baremes/", views.prof_rubrics, name="prof_rubrics"),
    path("prof/baremes/creer/", views.prof_rubric_create, name="prof_rubric_create"),
    path("prof/baremes/<int:pk>/modifier/", views.prof_rubric_update, name="prof_rubric_update"),
    path("prof/baremes/<int:pk>/supprimer/", views.prof_rubric_delete, name="prof_rubric_delete"),

    # ── Admin université ──────────────────────────────────────────────────
    path("administration/banques-exercices/", views.admin_exercise_banks, name="admin_exercise_banks"),
    path("administration/categories-niveaux/", views.admin_categories, name="admin_categories"),
    path("administration/categories/creer/", views.admin_category_create, name="admin_category_create"),
    path("administration/categories/<int:pk>/modifier/", views.admin_category_update, name="admin_category_update"),
    path("administration/categories/<int:pk>/supprimer/", views.admin_category_delete, name="admin_category_delete"),
]
