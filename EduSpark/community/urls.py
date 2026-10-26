from django.urls import path

from . import message_views, moderation_views, views

app_name = "community"

urlpatterns = [
    # Pages de la navigation du portail (un nom par rôle, même vue : le contenu s'adapte au rôle).
    path("etudiant/forums/", views.forum_list, name="student_forums"),
    path("etudiant/annonces/", views.announcement_list, name="student_announcements"),
    path("etudiant/messagerie/", message_views.message_inbox, name="student_messages"),
    path("prof/forums/", views.forum_list, name="prof_forums"),
    path("prof/annonces/", views.announcement_list, name="prof_announcements"),
    path("prof/messagerie/", message_views.message_inbox, name="prof_messages"),
    path("prof/moderation/", moderation_views.moderation_list, name="prof_moderation"),
    path("administration/communication/", views.announcement_list, name="admin_communication"),
    path("administration/forums/", views.forum_list, name="admin_forum_supervision"),
    path("administration/signalements/", moderation_views.moderation_list, name="admin_reports"),

    # Annonces
    path("annonces/nouvelle/", views.announcement_create, name="announcement_create"),
    path("annonces/<int:pk>/", views.announcement_detail, name="announcement_detail"),
    path("annonces/<int:pk>/modifier/", views.announcement_edit, name="announcement_edit"),
    path("annonces/<int:pk>/supprimer/", views.announcement_delete, name="announcement_delete"),

    # Forums
    path("forums/nouveau/", views.forum_create, name="forum_create"),
    path("forums/<int:pk>/", views.forum_detail, name="forum_detail"),
    path("forums/<int:pk>/modifier/", views.forum_edit, name="forum_edit"),
    path("forums/<int:pk>/supprimer/", views.forum_delete, name="forum_delete"),
    path("forums/<int:forum_pk>/question/", views.thread_create, name="thread_create"),

    # Questions
    path("questions/<int:pk>/", views.thread_detail, name="thread_detail"),
    path("questions/<int:pk>/modifier/", views.thread_edit, name="thread_edit"),
    path("questions/<int:pk>/supprimer/", views.thread_delete, name="thread_delete"),
    path("questions/<int:pk>/resolue/", views.thread_toggle_resolved, name="thread_toggle_resolved"),
    path("questions/<int:pk>/epingler/", views.thread_toggle_pin, name="thread_toggle_pin"),
    path("questions/<int:pk>/masquer/", views.thread_toggle_hidden, name="thread_toggle_hidden"),
    path("questions/<int:pk>/suggestion/", views.thread_ai_suggestion, name="thread_ai_suggestion"),
    path("questions/<int:thread_pk>/repondre/", views.reply_create, name="reply_create"),

    # Réponses
    path("reponses/<int:pk>/modifier/", views.reply_edit, name="reply_edit"),
    path("reponses/<int:pk>/supprimer/", views.reply_delete, name="reply_delete"),
    path("reponses/<int:pk>/solution/", views.reply_mark_solution, name="reply_mark_solution"),
    path("reponses/<int:pk>/masquer/", views.reply_toggle_hidden, name="reply_toggle_hidden"),

    # Signalements
    path("signaler/<str:target>/<int:pk>/", views.report_create, name="report_create"),
    path("signalements/<int:pk>/traiter/", moderation_views.report_resolve, name="report_resolve"),

    # Messagerie
    path("messagerie/nouveau/", message_views.message_create, name="message_create"),
    path("messagerie/<int:pk>/", message_views.message_detail, name="message_detail"),
    path("messagerie/<int:pk>/supprimer/", message_views.message_delete, name="message_delete"),
]
