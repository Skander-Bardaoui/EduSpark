"""Socle multi-tenant partagé par les 6 modules.

Chaque module métier peut (et doit) importer d'ici — c'est le seul code
commun autorisé, avec AUTH_USER_MODEL et TENANT_MODEL :

    from users.tenancy import TenantModel, TenantScopedMixin

    class Exercice(TenantModel):          # ajoute la colonne « university »
        matiere = models.CharField(...)    # liens inter-modules = champs simples

    class ExerciceListView(TenantScopedMixin, ListView):
        model = Exercice                   # queryset filtré sur request.university
        allowed_roles = (Role.PROFESSOR,)  # admin plateforme toujours autorisé

Aucun import de *modèles* d'un autre module métier : ce fichier ne charge
les modèles de `users` que paresseusement (apps.get_model).
"""

from functools import wraps

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import models
from django.shortcuts import redirect


SESSION_KEY = "current_university_id"
HEADER_NAME = "HTTP_X_UNIVERSITY"  # en-tête « X-University: <slug ou id> » (API)


class Role(models.TextChoices):
    """Rôles de la plateforme.

    PLATFORM_ADMIN est global (porté par is_superuser) ; les trois autres
    sont portés par une Membership, donc définis *par université*.
    """

    PLATFORM_ADMIN = "admin_plateforme", "Admin plateforme"
    UNIVERSITY_ADMIN = "admin_universite", "Admin université"
    PROFESSOR = "professeur", "Professeur"
    STUDENT = "etudiant", "Étudiant"


MEMBERSHIP_ROLES = [
    (Role.UNIVERSITY_ADMIN.value, Role.UNIVERSITY_ADMIN.label),
    (Role.PROFESSOR.value, Role.PROFESSOR.label),
    (Role.STUDENT.value, Role.STUDENT.label),
]


def get_tenant_model():
    """Modèle université déclaré dans settings.TENANT_MODEL."""
    return apps.get_model(settings.TENANT_MODEL, require_ready=False)


# ---------------------------------------------------------------------------
# Modèle abstrait
# ---------------------------------------------------------------------------

class TenantQuerySet(models.QuerySet):
    def for_university(self, university):
        return self.filter(university=university)


class TenantModel(models.Model):
    """Ajoute la colonne « university » obligatoire à une table métier."""

    university = models.ForeignKey(
        settings.TENANT_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name="Université",
    )

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Résolution de l'université courante
# ---------------------------------------------------------------------------

def is_platform_admin(user):
    return bool(user and user.is_authenticated and user.is_superuser)


def _match(queryset, requested, field_prefix=""):
    """Filtre un queryset par slug ou par id (valeur venant de l'utilisateur)."""
    requested = str(requested).strip()
    if requested.isdigit():
        return queryset.filter(**{f"{field_prefix}pk": int(requested)}).first()
    return queryset.filter(**{f"{field_prefix}slug": requested}).first()


def resolve_tenant(request):
    """Place university / membership / university_role sur la requête.

    Ordre : en-tête X-University (API), puis la session, puis la première
    appartenance active de l'utilisateur. Une université n'est retenue que
    si l'utilisateur y a une appartenance active — sauf l'admin plateforme,
    qui peut se placer dans n'importe quelle université.
    """
    request.university = None
    request.membership = None
    request.university_role = None

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return

    University = get_tenant_model()
    Membership = apps.get_model("users", "Membership")
    memberships = (
        Membership.objects.filter(user=user, is_active=True, university__is_active=True)
        .select_related("university")
        .order_by("university__name")
    )
    session = getattr(request, "session", None)
    requested = request.META.get(HEADER_NAME) or (session.get(SESSION_KEY) if session is not None else None)

    membership = None
    university = None
    if requested:
        membership = _match(memberships, requested, "university__")
        if membership is not None:
            university = membership.university
        elif is_platform_admin(user):
            university = _match(University.objects.all(), requested)
    if university is None and membership is None:
        membership = memberships.first()
        university = membership.university if membership else None

    request.university = university
    request.membership = membership
    if is_platform_admin(user):
        request.university_role = Role.PLATFORM_ADMIN.value
    elif membership is not None:
        request.university_role = membership.role

    if session is not None:
        current = university.pk if university else None
        if session.get(SESSION_KEY) != current:
            if current is None:
                session.pop(SESSION_KEY, None)
            else:
                session[SESSION_KEY] = current


def switch_tenant(request, university):
    """Change l'université active (appelé par la vue « changer d'université »)."""
    request.session[SESSION_KEY] = university.pk
    resolve_tenant(request)


class TenantMiddleware:
    """Expose request.university (et request.membership / university_role).

    À placer après AuthenticationMiddleware. Pour l'API JWT, l'utilisateur
    n'est connu qu'une fois la vue DRF lancée : TenantAPIMixin rappelle
    resolve_tenant() après l'authentification.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resolve_tenant(request)
        return self.get_response(request)


# ---------------------------------------------------------------------------
# Permissions par rôle
# ---------------------------------------------------------------------------

def has_role(request, *roles):
    """Vrai si le rôle courant est dans roles. L'admin plateforme passe toujours."""
    role = getattr(request, "university_role", None)
    if role == Role.PLATFORM_ADMIN:
        return True
    return role in roles


def _deny_or_redirect(request, roles, need_university=True):
    """Retourne une réponse si l'accès est refusé, sinon None."""
    # Import local : ce module est chargé par les modèles, avant l'app auth.
    from django.contrib.auth.views import redirect_to_login

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if need_university and getattr(request, "university", None) is None:
        messages.info(request, "Choisissez d'abord une université.")
        return redirect("users:university_switch")
    if roles and not has_role(request, *roles):
        raise PermissionDenied("Votre rôle ne permet pas d'accéder à cette page.")
    return None


def tenant_required(*roles):
    """Décorateur de vue fonction : connexion + université courante + rôle."""
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


class TenantRequiredMixin:
    """Vue classe : connexion + université courante + rôle (allowed_roles).

    allowed_roles = None : tout membre de l'université courante.
    """

    allowed_roles = None
    require_university = True

    def dispatch(self, request, *args, **kwargs):
        denied = _deny_or_redirect(request, self.allowed_roles or (), self.require_university)
        if denied is not None:
            return denied
        return super().dispatch(request, *args, **kwargs)


class TenantScopedMixin(TenantRequiredMixin):
    """Filtre le queryset sur request.university et l'impose à la création.

    Un objet d'une autre université n'est jamais trouvé (404).
    """

    def get_queryset(self):
        return super().get_queryset().filter(university=self.request.university)

    def form_valid(self, form):
        if hasattr(form, "instance") and not getattr(form.instance, "university_id", None):
            form.instance.university = self.request.university
        return super().form_valid(form)


class PlatformAdminRequiredMixin(TenantRequiredMixin):
    allowed_roles = (Role.PLATFORM_ADMIN,)
    require_university = False


class TenantAPIMixin:
    """Vue DRF : résout l'université après l'authentification JWT."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        resolve_tenant(request._request)
        request.university = request._request.university
        request.membership = request._request.membership
        request.university_role = request._request.university_role
