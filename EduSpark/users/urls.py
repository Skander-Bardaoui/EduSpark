from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

from .views import accounts, auth, classes, core, invitations, members, universities

app_name = "users"

urlpatterns = [
    # --- Authentification ----------------------------------------------------
    path("accounts/connexion/", auth.login_view, name="login"),
    path("accounts/inscription/", auth.signup_view, name="signup"),
    path("accounts/deconnexion/", auth.logout_view, name="logout"),
    # Compatibilité avec l'ancienne route unique.
    path("accounts/auth/", auth.auth_view, name="auth"),
    path("accounts/invitation/<uuid:token>/", auth.invitation_accept, name="invitation_accept"),
    # Mot de passe oublié (vues Django + envoi d'e-mail).
    path("accounts/mot-de-passe-oublie/", auth_views.PasswordResetView.as_view(
        template_name="users/password_reset_form.html",
        email_template_name="users/password_reset_email.txt",
        subject_template_name="users/password_reset_subject.txt",
        success_url=reverse_lazy("users:password_reset_done"),
    ), name="password_reset"),
    path("accounts/mot-de-passe-oublie/envoye/", auth_views.PasswordResetDoneView.as_view(
        template_name="users/password_reset_done.html",
    ), name="password_reset_done"),
    path("accounts/reinitialiser/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="users/password_reset_confirm.html",
        success_url=reverse_lazy("users:password_reset_complete"),
    ), name="password_reset_confirm"),
    path("accounts/reinitialiser/termine/", auth_views.PasswordResetCompleteView.as_view(
        template_name="users/password_reset_complete.html",
    ), name="password_reset_complete"),
    # API JWT (access / refresh).
    path("accounts/api/", include("users.api.urls")),

    # --- Espace connecté -------------------------------------------------------
    path("tableau-de-bord/", core.dashboard, name="dashboard"),
    path("universite/changer/", core.university_switch, name="university_switch"),
    path("profil/", core.profile_edit, name="profile"),

    # --- Universités (admin plateforme) ---------------------------------------
    path("universites/", universities.UniversityListView.as_view(), name="university_list"),
    path("universites/nouvelle/", universities.UniversityCreateView.as_view(), name="university_create"),
    path("universites/<int:pk>/", universities.UniversityDetailView.as_view(), name="university_detail"),
    path("universites/<int:pk>/modifier/", universities.UniversityUpdateView.as_view(), name="university_update"),
    path("universites/<int:pk>/supprimer/", universities.UniversityDeleteView.as_view(), name="university_delete"),
    path("universites/<int:pk>/inviter-admin/", universities.university_invite_admin, name="university_invite_admin"),
    path("appartenances/<int:pk>/retirer/", universities.membership_remove, name="membership_remove"),

    # --- Comptes (admin plateforme) -------------------------------------------
    path("comptes/", accounts.AccountListView.as_view(), name="account_list"),
    path("comptes/<int:pk>/", accounts.AccountDetailView.as_view(), name="account_detail"),
    path("comptes/<int:pk>/modifier/", accounts.AccountUpdateView.as_view(), name="account_update"),
    path("comptes/<int:pk>/supprimer/", accounts.AccountDeleteView.as_view(), name="account_delete"),

    # --- Professeurs / étudiants (admin université) ---------------------------
    path("professeurs/", members.ProfessorListView.as_view(), name="professor_list"),
    path("professeurs/nouveau/", members.ProfessorCreateView.as_view(), name="professor_create"),
    path("professeurs/<int:pk>/", members.ProfessorDetailView.as_view(), name="professor_detail"),
    path("professeurs/<int:pk>/modifier/", members.ProfessorUpdateView.as_view(), name="professor_update"),
    path("professeurs/<int:pk>/supprimer/", members.ProfessorDeleteView.as_view(), name="professor_delete"),
    path("etudiants/", members.StudentListView.as_view(), name="student_list"),
    path("etudiants/nouveau/", members.StudentCreateView.as_view(), name="student_create"),
    path("etudiants/<int:pk>/", members.StudentDetailView.as_view(), name="student_detail"),
    path("etudiants/<int:pk>/modifier/", members.StudentUpdateView.as_view(), name="student_update"),
    path("etudiants/<int:pk>/supprimer/", members.StudentDeleteView.as_view(), name="student_delete"),
    path("inscriptions/<int:pk>/decision/", members.membership_decide, name="membership_decide"),

    # --- Classes et groupes ---------------------------------------------------
    path("classes/", classes.SchoolClassListView.as_view(), name="class_list"),
    path("classes/nouvelle/", classes.SchoolClassCreateView.as_view(), name="class_create"),
    path("classes/<int:pk>/", classes.SchoolClassDetailView.as_view(), name="class_detail"),
    path("classes/<int:pk>/modifier/", classes.SchoolClassUpdateView.as_view(), name="class_update"),
    path("classes/<int:pk>/supprimer/", classes.SchoolClassDeleteView.as_view(), name="class_delete"),
    path("classes/<int:class_pk>/groupes/nouveau/", classes.StudentGroupCreateView.as_view(), name="group_create"),
    path("classes/<int:class_pk>/groupes/<int:pk>/modifier/", classes.StudentGroupUpdateView.as_view(),
         name="group_update"),
    path("classes/<int:class_pk>/groupes/<int:pk>/supprimer/", classes.StudentGroupDeleteView.as_view(),
         name="group_delete"),

    # --- Invitations ----------------------------------------------------------
    path("invitations/", invitations.InvitationListView.as_view(), name="invitation_list"),
    path("invitations/nouvelle/", invitations.InvitationCreateView.as_view(), name="invitation_create"),
    path("invitations/<int:pk>/", invitations.InvitationDetailView.as_view(), name="invitation_detail"),
    path("invitations/<int:pk>/modifier/", invitations.InvitationUpdateView.as_view(), name="invitation_update"),
    path("invitations/<int:pk>/supprimer/", invitations.InvitationDeleteView.as_view(), name="invitation_delete"),
    path("invitations/<int:pk>/<str:action>/", invitations.invitation_action, name="invitation_action"),
]
