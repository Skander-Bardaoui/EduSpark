from .tenancy import Role, has_role, is_platform_admin


def tenant(request):
    """Université courante, rôle et menus disponibles pour tous les templates."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    role = getattr(request, "university_role", None)
    university = getattr(request, "university", None)
    switchable = user.memberships.filter(is_active=True, university__is_active=True).count()
    return {
        "current_university": university,
        "current_role": role,
        "current_role_label": Role(role).label if role else "",
        "is_platform_admin": is_platform_admin(user),
        "is_university_admin": university is not None and has_role(request, Role.UNIVERSITY_ADMIN),
        "is_professor_or_admin": university is not None and has_role(request, Role.UNIVERSITY_ADMIN, Role.PROFESSOR),
        "can_switch_university": is_platform_admin(user) or switchable > 1,
    }
