from django.urls import reverse

from .models import Profil
from .tenancy import Role, tenant_required


def get_user_role(user):
    """Retourne le rôle fonctionnel : admin / prof / etudiant / None."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return Profil.ROLE_ADMIN
    profil = getattr(user, "profil", None)
    if profil is None:
        return None
    if user.is_staff and profil.role != Profil.ROLE_ADMIN:
        return Profil.ROLE_ADMIN
    return profil.role


_PROFIL_TO_MEMBERSHIP_ROLE = {
    Profil.ROLE_ADMIN: Role.UNIVERSITY_ADMIN,
    Profil.ROLE_PROF: Role.PROFESSOR,
    Profil.ROLE_ETUDIANT: Role.STUDENT,
}


def role_required(*allowed_roles):
    """Accès réservé aux rôles exercés dans l'université courante.

    Les vues passent des rôles globaux (``Profil.ROLE_*``) ; ils sont
    traduits en rôles d'appartenance pour que le droit dépende de
    l'université sélectionnée, pas seulement du rôle global du compte.
    """
    tenant_roles = tuple(
        _PROFIL_TO_MEMBERSHIP_ROLE[role]
        for role in allowed_roles
        if role in _PROFIL_TO_MEMBERSHIP_ROLE
    )
    return tenant_required(*tenant_roles)


admin_required = role_required(Profil.ROLE_ADMIN)
prof_required = role_required(Profil.ROLE_ADMIN, Profil.ROLE_PROF)
etudiant_required = role_required(
    Profil.ROLE_ADMIN, Profil.ROLE_PROF, Profil.ROLE_ETUDIANT)


def role_home_url(user):
    """URL d'accueil selon le rôle après connexion / inscription."""
    if user and user.is_authenticated and user.is_superuser:
        return reverse("portal:admin_universities")
    role = get_user_role(user)
    if role == Profil.ROLE_ADMIN:
        return reverse("coaching:admin_dashboard")
    if role == Profil.ROLE_PROF:
        return reverse("coaching:prof_dashboard")
    return reverse("coaching:student_dashboard")
