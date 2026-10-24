from django.urls import path

from . import views

app_name = "community"

urlpatterns = [
    path("etudiant/forums/", views.student_forums, name="student_forums"),
    path("etudiant/annonces/", views.student_announcements, name="student_announcements"),
    path("etudiant/messagerie/", views.student_messages, name="student_messages"),
    path("prof/forums/", views.prof_forums, name="prof_forums"),
    path("prof/annonces/", views.prof_announcements, name="prof_announcements"),
    path("prof/messagerie/", views.prof_messages, name="prof_messages"),
    path("prof/moderation/", views.prof_moderation, name="prof_moderation"),
    path("administration/communication/", views.admin_communication, name="admin_communication"),
    path("administration/forums/", views.admin_forum_supervision, name="admin_forum_supervision"),
    path("administration/signalements/", views.admin_reports, name="admin_reports"),
]
