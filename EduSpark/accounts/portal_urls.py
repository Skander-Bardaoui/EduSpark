from django.urls import path

from . import portal_views, views

app_name = "portal"

urlpatterns = [
    path("etudiant/profil/", views.student_profile, name="student_profile"),
    path("etudiant/classe/", portal_views.student_class, name="student_class"),
    path("prof/profil/", views.prof_profile, name="prof_profile"),
    path("prof/universites/", portal_views.prof_universities, name="prof_universities"),
    path("prof/classes/", portal_views.prof_classes, name="prof_classes"),
    path("prof/parametres/", portal_views.prof_settings, name="prof_settings"),
    path("administration/etudiants/", views.admin_students, name="admin_students"),
    path("administration/enseignants/", portal_views.admin_teachers, name="admin_teachers"),
    path("administration/classes/", portal_views.admin_classes, name="admin_classes"),
    path("administration/invitations/", portal_views.admin_invitations, name="admin_invitations"),
    path("administration/universite/", portal_views.admin_university, name="admin_university"),
    path("administration/parametres/", portal_views.admin_platform_settings, name="admin_platform_settings"),
]
