from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import Profil


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


def role_required(*allowed_roles):
    """Décorateur : accès réservé aux rôles donnés (superuser = admin)."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if get_user_role(request.user) not in allowed_roles:
                raise PermissionDenied("Accès réservé : rôle requis.")
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


admin_required = role_required(Profil.ROLE_ADMIN)
prof_required = role_required(Profil.ROLE_ADMIN, Profil.ROLE_PROF)
etudiant_required = role_required(
    Profil.ROLE_ADMIN, Profil.ROLE_PROF, Profil.ROLE_ETUDIANT)


def role_home_url(user):
    """URL d'accueil selon le rôle après connexion / inscription."""
    role = get_user_role(user)
    if role == Profil.ROLE_ADMIN:
        return "/admin/"
    return "/"
