from django.urls import path

from . import views

app_name = "exercises"

urlpatterns = [
    # -----------------------------------------------------------------------
    # Étudiant — Devoirs
    # -----------------------------------------------------------------------
    path("etudiant/devoirs/", views.student_assignments, name="student_assignments"),
    path("etudiant/devoirs/<int:pk>/", views.student_assignment_detail, name="student_assignment_detail"),

    # Étudiant — Entraînement
    path("etudiant/entrainement/", views.student_practice, name="student_practice"),
    path("etudiant/entrainement/<int:pk>/session/", views.student_practice_session, name="student_practice_session"),

    # -----------------------------------------------------------------------
    # Professeur — Banque d'exercices
    # -----------------------------------------------------------------------
    path("prof/banque-exercices/", views.prof_exercise_bank, name="prof_exercise_bank"),
    path("prof/banque-exercices/nouveau/", views.prof_exercise_create, name="prof_exercise_create"),
    path("prof/banque-exercices/<int:pk>/modifier/", views.prof_exercise_edit, name="prof_exercise_edit"),
    path("prof/banque-exercices/<int:pk>/supprimer/", views.prof_exercise_delete, name="prof_exercise_delete"),

    # Professeur — Devoirs
    path("prof/devoirs/", views.prof_assignments, name="prof_assignments"),
    path("prof/devoirs/nouveau/", views.prof_assignment_create, name="prof_assignment_create"),
    path("prof/devoirs/<int:pk>/modifier/", views.prof_assignment_edit, name="prof_assignment_edit"),
    path("prof/devoirs/<int:pk>/supprimer/", views.prof_assignment_delete, name="prof_assignment_delete"),
    path("prof/devoirs/<int:pk>/statut/", views.prof_assignment_status, name="prof_assignment_status"),

    # Professeur — Séries & Barèmes
    path("prof/series-baremes/", views.prof_rubrics, name="prof_rubrics"),
    path("prof/series-baremes/bareme/<int:pk>/modifier/", views.prof_rubric_edit, name="prof_rubric_edit"),

    # -----------------------------------------------------------------------
    # Administration
    # -----------------------------------------------------------------------
    path("administration/banques-exercices/", views.admin_exercise_banks, name="admin_exercise_banks"),
    path("administration/categories-niveaux/", views.admin_categories, name="admin_categories"),

    # -----------------------------------------------------------------------
    # API IA
    # -----------------------------------------------------------------------
    path("exercises/api/generer/", views.api_ai_generate, name="api_ai_generate"),
    path("exercises/api/generer-etudiant/", views.api_ai_generate_student, name="api_ai_generate_student"),
    path("exercises/api/sauvegarder-ia/", views.api_exercise_save_ai, name="api_exercise_save_ai"),

    # -----------------------------------------------------------------------
    # PDF
    # -----------------------------------------------------------------------
    path("etudiant/devoirs/<int:pk>/pdf/", views.student_assignment_pdf, name="student_assignment_pdf"),
    path("prof/devoirs/<int:pk>/pdf/", views.prof_assignment_pdf, name="prof_assignment_pdf"),
]
