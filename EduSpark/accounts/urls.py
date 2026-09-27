from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

from . import views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.login_view, name="login"),
    path("inscription/", views.signup_view, name="signup"),
    path("deconnexion/", views.logout_view, name="logout"),
    # Compatibilité avec l'ancienne route unique.
    path("auth/", views.auth_view, name="auth"),
    # Mot de passe oublié (vues Django + envoi d'e-mail).
    path("mot-de-passe-oublie/", auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset_form.html",
        email_template_name="accounts/password_reset_email.txt",
        subject_template_name="accounts/password_reset_subject.txt",
        success_url=reverse_lazy("accounts:password_reset_done"),
    ), name="password_reset"),
    path("mot-de-passe-oublie/envoye/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html",
    ), name="password_reset_done"),
    path("reinitialiser/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="accounts/password_reset_confirm.html",
        success_url=reverse_lazy("accounts:password_reset_complete"),
    ), name="password_reset_confirm"),
    path("reinitialiser/termine/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html",
    ), name="password_reset_complete"),
    # API JWT (access / refresh).
    path("api/", include("accounts.api.urls")),
]
