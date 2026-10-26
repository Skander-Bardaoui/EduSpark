from django.urls import path

from . import admin_views, class_views, invitation_views, member_views, portal_views

app_name = "portal"

urlpatterns = [
    # Université courante
    path("universite/changer/", portal_views.university_switch, name="university_switch"),
    # Plateforme : universités
    path("administration/universites/", admin_views.UniversityListView.as_view(), name="admin_universities"),
    path("administration/universites/nouvelle/", admin_views.UniversityCreateView.as_view(),
         name="admin_university_create"),
    path("administration/universites/<int:pk>/", admin_views.UniversityDetailView.as_view(),
         name="admin_university_detail"),
    path("administration/universites/<int:pk>/modifier/", admin_views.UniversityUpdateView.as_view(),
         name="admin_university_update"),
    path("administration/universites/<int:pk>/supprimer/", admin_views.UniversityDeleteView.as_view(),
         name="admin_university_delete"),
    path("administration/universites/<int:pk>/inviter-admin/", admin_views.university_invite_admin,
         name="admin_university_invite_admin"),
    # Université courante (admin université)
    path("administration/universite/", admin_views.AdminUniversityView.as_view(), name="admin_university"),
    # Plateforme : comptes et profil
    path("administration/comptes/", admin_views.AccountListView.as_view(), name="admin_accounts"),
    path("administration/comptes/<int:pk>/modifier/", admin_views.AccountUpdateView.as_view(),
         name="admin_account_update"),
    path("administration/comptes/<int:pk>/supprimer/", admin_views.AccountDeleteView.as_view(),
         name="admin_account_delete"),
    path("administration/profil/", admin_views.AdminProfileView.as_view(), name="admin_profile"),
    # Professeurs
    path("administration/enseignants/", member_views.ProfessorListView.as_view(), name="admin_teachers"),
    path("administration/enseignants/nouveau/", member_views.ProfessorCreateView.as_view(),
         name="admin_teacher_create"),
    path("administration/enseignants/<int:pk>/modifier/", member_views.ProfessorUpdateView.as_view(),
         name="admin_teacher_update"),
    path("administration/enseignants/<int:pk>/supprimer/", member_views.ProfessorDeleteView.as_view(),
         name="admin_teacher_delete"),
    # Étudiants et inscriptions
    path("administration/etudiants/", member_views.StudentListView.as_view(), name="admin_students"),
    path("administration/etudiants/nouveau/", member_views.StudentCreateView.as_view(),
         name="admin_student_create"),
    path("administration/etudiants/<int:pk>/modifier/", member_views.StudentUpdateView.as_view(),
         name="admin_student_update"),
    path("administration/etudiants/<int:pk>/supprimer/", member_views.StudentDeleteView.as_view(),
         name="admin_student_delete"),
    path("administration/etudiants/inscriptions/<int:pk>/decision/", member_views.membership_decide,
         name="admin_membership_decide"),
    # Classes et groupes
    path("administration/classes/", class_views.SchoolClassListView.as_view(), name="admin_classes"),
    path("administration/classes/nouvelle/", class_views.SchoolClassCreateView.as_view(),
         name="admin_class_create"),
    path("administration/classes/<int:pk>/", class_views.SchoolClassDetailView.as_view(),
         name="admin_class_detail"),
    path("administration/classes/<int:pk>/modifier/", class_views.SchoolClassUpdateView.as_view(),
         name="admin_class_update"),
    path("administration/classes/<int:pk>/etudiants/affecter/", class_views.assign_class_student,
         name="admin_class_assign_student"),
    path("administration/classes/<int:pk>/supprimer/", class_views.SchoolClassDeleteView.as_view(),
         name="admin_class_delete"),
    path("administration/classes/<int:pk>/groupes/nouveau/", class_views.StudentGroupCreateView.as_view(),
         name="admin_group_create"),
    path("administration/classes/<int:pk>/groupes/<int:gpk>/modifier/",
         class_views.StudentGroupUpdateView.as_view(), name="admin_group_update"),
    path("administration/classes/<int:pk>/groupes/<int:gpk>/supprimer/",
         class_views.StudentGroupDeleteView.as_view(), name="admin_group_delete"),
    # Invitations
    path("administration/invitations/", invitation_views.InvitationListView.as_view(),
         name="admin_invitations"),
    path("administration/invitations/nouvelle/", invitation_views.InvitationCreateView.as_view(),
         name="admin_invitation_create"),
    path("administration/invitations/<int:pk>/modifier/", invitation_views.InvitationUpdateView.as_view(),
         name="admin_invitation_update"),
    path("administration/invitations/<int:pk>/supprimer/", invitation_views.InvitationDeleteView.as_view(),
         name="admin_invitation_delete"),
    path("administration/invitations/<int:pk>/<str:action>/", invitation_views.invitation_action,
         name="admin_invitation_action"),
    # Paramètres plateforme
    path("administration/parametres/", admin_views.AdminPlatformSettingsView.as_view(),
         name="admin_platform_settings"),
    # Portail étudiant
    path("etudiant/profil/", portal_views.student_profile, name="student_profile"),
    path("etudiant/classe/", portal_views.student_class, name="student_class"),
    # Portail professeur
    path("prof/profil/", portal_views.prof_profile, name="prof_profile"),
    path("prof/universites/", portal_views.prof_universities, name="prof_universities"),
    path("prof/classes/", portal_views.prof_classes, name="prof_classes"),
    path("prof/parametres/", portal_views.prof_settings, name="prof_settings"),
]
