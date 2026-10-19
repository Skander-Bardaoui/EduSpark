from django.apps import AppConfig


class UsersConfig(AppConfig):
    """Module 0 — utilisateurs, universités (tenants), rôles, profils,
    classes / groupes et invitations. Commun à tous les autres modules."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
    verbose_name = "Utilisateurs et universités"
