from .decorators import get_user_role
from .portal_nav import NAV_SECTIONS, ROLE_META


def portal_context(request):
    """Navigation, identity and notification data for the portal shell."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    role = get_user_role(user)
    meta = ROLE_META.get(role)
    if meta is None:
        return {}

    view_name = getattr(request.resolver_match, "view_name", "") or ""
    sections = []
    current_label = ""
    current_section = ""
    active_found = False

    for section in NAV_SECTIONS.get(role, ()):
        items = []
        section_active = False
        for item in section["items"]:
            is_active = False
            if not active_found and item["url_name"] == view_name:
                is_active = True
                active_found = True
                current_label = item["label"]
                current_section = section["label"]
            items.append({**item, "active": is_active})
            section_active = section_active or is_active
        sections.append(
            {"label": section["label"], "items": items, "active": section_active}
        )

    full_name = user.get_full_name().strip()
    if not full_name:
        full_name = (user.first_name or "").strip() or user.email.split("@")[0]
    initials = "".join(part[0] for part in full_name.replace("-", " ").split()[:2]).upper()
    if not initials:
        initials = (user.email[:1] or "?").upper()

    return {
        "portal_role": role,
        "portal_role_label": meta["label"],
        "portal_label": meta["portal_label"],
        "portal_home_url_name": meta["home_url_name"],
        "portal_profile_url_name": meta["profile_url_name"],
        "portal_notifications": meta["notifications"],
        "portal_nav_sections": sections,
        "portal_current_label": current_label or meta["portal_label"],
        "portal_current_section": current_section,
        "portal_user_name": full_name,
        "portal_user_initials": initials,
        "portal_user_email": user.email,
    }
