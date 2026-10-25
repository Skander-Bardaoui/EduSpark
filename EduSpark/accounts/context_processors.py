from .decorators import get_user_role
from .models import Profil
from .portal_nav import NAV_SECTIONS, ROLE_META
from .tenancy import Role, is_platform_admin

_MEMBERSHIP_TO_PORTAL_ROLE = {
    Role.UNIVERSITY_ADMIN: Profil.ROLE_ADMIN,
    Role.PROFESSOR: Profil.ROLE_PROF,
    Role.STUDENT: Profil.ROLE_ETUDIANT,
}

# Base de page (thème Tailwind, fond) associée au rôle du portail. Les pages
# partagées par plusieurs rôles héritent ainsi du bon habillage.
_ROLE_BASE_TEMPLATES = {
    Profil.ROLE_ADMIN: "portal/base_admin.html",
    Profil.ROLE_PROF: "portal/base_prof.html",
    Profil.ROLE_ETUDIANT: "portal/base_student.html",
}


def _effective_portal_role(request, user):
    """Rôle du portail : d'abord le rôle exercé dans l'université courante."""
    if is_platform_admin(user):
        return Profil.ROLE_ADMIN
    membership = getattr(request, "membership", None)
    if membership is not None:
        mapped = _MEMBERSHIP_TO_PORTAL_ROLE.get(membership.role)
        if mapped:
            return mapped
    return get_user_role(user)


def portal_context(request):
    """Navigation, identité et université courante pour le shell du portail."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    role = _effective_portal_role(request, user)
    meta = ROLE_META.get(role)
    if meta is None:
        return {}

    platform = is_platform_admin(user)
    university = getattr(request, "university", None)
    has_university = university is not None
    view_name = getattr(request.resolver_match, "view_name", "") or ""
    sections = []
    visible_url_names = set()
    current_label = ""
    current_section = ""
    active_found = False

    for section in NAV_SECTIONS.get(role, ()):
        items = []
        section_active = False
        for item in section["items"]:
            if item.get("platform_only") and not platform:
                continue
            # L'admin plateforme ne travaille dans aucune université : aucun
            # changement de contexte ne lui est proposé.
            if platform and item["url_name"] == "portal:university_switch":
                continue
            if not has_university and not item.get("tenant_free"):
                continue
            visible_url_names.add(item["url_name"])
            is_active = False
            if not active_found and item["url_name"] == view_name:
                is_active = True
                active_found = True
                current_label = item["label"]
                current_section = section["label"]
            items.append({**item, "active": is_active})
            section_active = section_active or is_active
        if items:
            sections.append({"label": section["label"], "items": items, "active": section_active})

    # Une notification n'est affichée que si sa page cible figure dans la
    # navigation du rôle et de l'université courante.
    notifications = tuple(
        notif for notif in meta["notifications"] if notif["url_name"] in visible_url_names
    )

    full_name = user.get_full_name().strip()
    if not full_name:
        full_name = (user.first_name or "").strip() or user.email.split("@")[0]
    initials = "".join(part[0] for part in full_name.replace("-", " ").split()[:2]).upper()
    if not initials:
        initials = (user.email[:1] or "?").upper()
    first_name = (user.first_name or "").strip() or full_name.split()[0]
    last_name = (user.last_name or "").strip() or full_name

    if platform or has_university:
        profile_url_name = meta["profile_url_name"]
        profile_label = "Mon profil"
    elif role == Profil.ROLE_ADMIN:
        profile_url_name = "portal:admin_profile"
        profile_label = "Mon profil"
    else:
        profile_url_name = "portal:university_switch"
        profile_label = "Choisir une université"

    if platform:
        home_url_name = "portal:admin_universities"
    elif has_university:
        home_url_name = meta["home_url_name"]
    else:
        home_url_name = "portal:university_switch"

    return {
        "portal_role": role,
        "portal_role_label": meta["label"],
        "portal_base_template": _ROLE_BASE_TEMPLATES[role],
        "portal_scope_label": Role.LABELS.get(
            getattr(request, "university_role", None), "En attente",
        ),
        "portal_label": meta["portal_label"] if platform or has_university else "Portail en attente",
        "portal_home_url_name": home_url_name,
        "portal_profile_url_name": profile_url_name,
        "portal_profile_label": profile_label,
        "portal_notifications": notifications,
        "portal_nav_sections": sections,
        "portal_current_label": current_label or meta["portal_label"],
        "portal_current_section": current_section,
        "portal_user_name": full_name,
        "portal_user_first_name": first_name,
        "portal_user_last_name": last_name,
        "portal_user_initials": initials,
        "portal_user_email": user.email,
        "portal_university": university,
        "portal_has_university": has_university,
        "portal_membership": getattr(request, "membership", None),
        "portal_university_role": getattr(request, "university_role", None),
        "portal_is_platform_admin": platform,
        "portal_can_switch_university": (
            not platform and getattr(request, "university_role", None) != Role.UNIVERSITY_ADMIN
        ),
        "portal_memberships": user.memberships.filter(
            is_active=True, university__is_active=True,
        ).select_related("university").order_by("university__name"),
        "portal_pending_memberships": user.memberships.filter(
            is_active=False,
        ).select_related("university").order_by("university__name"),
    }
