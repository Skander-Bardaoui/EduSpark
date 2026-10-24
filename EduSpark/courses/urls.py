from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("etudiant/cours/", views.student_catalogue, name="student_catalogue"),
    path("etudiant/emploi-du-temps/", views.student_timetable, name="student_timetable"),
    path("prof/cours/", views.prof_course, name="prof_course"),
    path("prof/emploi-du-temps/", views.prof_timetable, name="prof_timetable"),
    path("prof/matieres/", views.prof_subjects, name="prof_subjects"),
    path("etudiant/supports-de-cours/", views.student_course_materials, name="student_course_materials"),
    path("prof/supports-de-cours/", views.prof_course_materials, name="prof_course_materials"),
    path("administration/emploi-du-temps/", views.admin_timetable, name="admin_timetable"),
    path("administration/offre-de-formation/", views.admin_program_offer, name="admin_program_offer"),
    path("administration/cours/", views.admin_courses, name="admin_courses"),
]
