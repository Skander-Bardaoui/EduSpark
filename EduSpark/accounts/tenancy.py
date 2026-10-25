"""Socle multi-universités : rôles par appartenance et université courante.

Le rôle global du portail reste porté par ``accounts.Profil`` ; le rôle
métier est porté par ``accounts.Membership``, donc défini *par université*.
L'administrateur plateforme est le superutilisateur Django : il gère les
établissements au niveau plateforme et n'est jamais rattaché à une
université courante.
"""

from functools import wraps

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

SESSION_KEY = "current_university_id"
HEADER_NAME = "HTTP_X_UNIVERSITY"


class Role:
    PLATFORM_ADMIN = "admin_plateforme"
    UNIVERSITY_ADMIN = "admin_universite"
    PROFESSOR = "professeur"
    STUDENT = "etudiant"

    LABELS = {
        PLATFORM_ADMIN: "Admin plateforme",
        UNIVERSITY_ADMIN: "Admin université",
        PROFESSOR: "Professeur",
        STUDENT: "Étudiant",
    }


MEMBERSHIP_ROLES = (
    (Role.UNIVERSITY_ADMIN, "Admin université"),
    (Role.PROFESSOR, "Professeur"),
    (Role.STUDENT, "Étudiant"),
)


def is_platform_admin(user):
    return bool(user and user.is_authenticated and user.is_superuser)


def is_university_admin(user, university=None):
    if not user or not user.is_authenticated:
        return False
    qs = user.memberships.filter(role=Role.UNIVERSITY_ADMIN, is_active=True, university__is_active=True)
    if university is not None:
        qs = qs.filter(university=university)
    return qs.exists()


def _match_membership(memberships, requested):
    requested = str(requested).strip()
    if not requested:
        return None
    if requested.isdigit():
        return memberships.filter(university__pk=int(requested)).first()
    return memberships.filter(university__slug=requested).first()


def resolve_tenant(request):
    """Place l'université et l'appartenance courantes sur la requête.

    Ordre : session, puis première appartenance active. Une université
    étrangère n'est jamais retenue. L'admin plateforme travaille au niveau
    plateforme : il n'a jamais d'université courante.
    """
    request.university = None
    request.membership = None
    request.university_role = None

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return

    session = getattr(request, "session", None)
    if is_platform_admin(user):
        request.university_role = Role.PLATFORM_ADMIN
        if session is not None:
            session.pop(SESSION_KEY, None)
        return

    Membership = apps.get_model("accounts", "Membership")
    memberships = (
        Membership.objects.filter(user=user, is_active=True, university__is_active=True)
        .select_related("university")
        .order_by("university__name")
    )

    requested = request.META.get(HEADER_NAME) or (session.get(SESSION_KEY) if session is not None else None)

    membership = _match_membership(memberships, requested) if requested else None
    if membership is None:
        membership = memberships.first()

    request.membership = membership
    if membership is not None:
        request.university = membership.university
        request.university_role = membership.role

    if session is not None:
        if membership is not None:
            session[SESSION_KEY] = membership.university_id
        else:
            session.pop(SESSION_KEY, None)


def switch_tenant(request, university):
    if is_platform_admin(getattr(request, "user", None)):
        return
    request.session[SESSION_KEY] = university.pk
    resolve_tenant(request)


def has_role(request, *roles):
    role = getattr(request, "university_role", None)
    if role == Role.PLATFORM_ADMIN:
        return True
    return role in roles


def _deny_or_redirect(request, roles, need_university=True):
    from django.contrib.auth.views import redirect_to_login

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)
    if is_platform_admin(request.user):
        if need_university:
            messages.info(
                request,
                "L'administration d'une université se fait depuis sa fiche établissement.",
            )
            return redirect("portal:admin_universities")
        return None
    if need_university and getattr(request, "university", None) is None:
        messages.info(request, "Choisissez d'abord une université.")
        return redirect("portal:university_switch")
    if roles and not has_role(request, *roles):
        raise PermissionDenied("Votre rôle ne permet pas d'accéder à cette page.")
    return None


def tenant_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            denied = _deny_or_redirect(request, roles)
            if denied is not None:
                return denied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def platform_admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        denied = _deny_or_redirect(request, (Role.PLATFORM_ADMIN,), need_university=False)
        if denied is not None:
            return denied
        return view_func(request, *args, **kwargs)
    return _wrapped


class TenantMiddleware:
    """Résout l'université courante après l'authentification."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resolve_tenant(request)
        return self.get_response(request)


class TenantRequiredMixin:
    allowed_roles = None
    require_university = True

    def dispatch(self, request, *args, **kwargs):
        denied = _deny_or_redirect(request, self.allowed_roles or (), self.require_university)
        if denied is not None:
            return denied
        return super().dispatch(request, *args, **kwargs)


class TenantScopedMixin(TenantRequiredMixin):
    """Filtre le queryset sur l'université courante et l'impose à la création."""

    def get_queryset(self):
        return super().get_queryset().filter(university=self.request.university)

    def form_valid(self, form):
        if hasattr(form, "instance") and not getattr(form.instance, "university_id", None):
            form.instance.university = self.request.university
        return super().form_valid(form)


class PlatformAdminRequiredMixin(TenantRequiredMixin):
    allowed_roles = (Role.PLATFORM_ADMIN,)
    require_university = False


class AdminAreaMixin(TenantRequiredMixin):
    """Admin université (et plateforme, qui passe toujours)."""

    allowed_roles = (Role.UNIVERSITY_ADMIN,)


def role_home_url_name(role):
    """Nom de route de l'accueil pour un rôle global ou exercé."""
    if role == Role.PLATFORM_ADMIN:
        return "portal:admin_universities"
    if role in (Role.UNIVERSITY_ADMIN, "admin"):
        return "coaching:admin_dashboard"
    if role in (Role.PROFESSOR, "prof"):
        return "coaching:prof_dashboard"
    if role in (Role.STUDENT, "etudiant"):
        return "coaching:student_dashboard"
    return "portal:university_switch"


def role_home_url(user):
    if is_platform_admin(user):
        return reverse(role_home_url_name(Role.PLATFORM_ADMIN))
    profil = getattr(user, "profil", None)
    return reverse(role_home_url_name(profil.role if profil else None))


def request_home_url(request):
    """Accueil réellement accessible avec l'université courante.

    L'admin plateforme est renvoyé vers la gestion des universités ; sans
    université, un utilisateur est renvoyé vers le sélecteur pour éviter une
    boucle de redirection (inscription en attente).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return reverse("accounts:login")
    if is_platform_admin(user):
        return reverse("portal:admin_universities")
    if getattr(request, "university", None) is None:
        return reverse("portal:university_switch")
    return reverse(role_home_url_name(getattr(request, "university_role", None)))
