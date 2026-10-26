"""Qui voit quoi dans la classe virtuelle.

Tout est filtré sur request.university (posée par TenantMiddleware). Dans
l'université courante : l'administration voit tout, un professeur voit les
classes qu'il enseigne, un étudiant voit les classes dont il est membre
(via ses groupes) ; un forum ou une annonce sans classe est ouvert à tous.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q

from accounts.models import SchoolClass
from accounts.tenancy import Role

from .models import Announcement, Forum, Message, Reply, Report, Thread

ADMIN, PROF, STUDENT = "admin", "prof", "etudiant"


def role_kind(request):
    role = getattr(request, "university_role", None)
    if role in (Role.PLATFORM_ADMIN, Role.UNIVERSITY_ADMIN):
        return ADMIN
    if role == Role.PROFESSOR:
        return PROF
    return STUDENT


_SECTION_URLS = {
    "announcements": {
        STUDENT: "community:student_announcements",
        PROF: "community:prof_announcements",
        ADMIN: "community:admin_communication",
    },
    "forums": {
        STUDENT: "community:student_forums",
        PROF: "community:prof_forums",
        ADMIN: "community:admin_forum_supervision",
    },
    "messages": {
        STUDENT: "community:student_messages",
        PROF: "community:prof_messages",
        ADMIN: "community:prof_messages",
    },
    "moderation": {
        STUDENT: "community:student_forums",
        PROF: "community:prof_moderation",
        ADMIN: "community:admin_reports",
    },
}


def section_url_name(request, section):
    """Nom d'URL de la page d'accueil d'une section, selon le rôle (la navigation du portail en dépend)."""
    return _SECTION_URLS[section][role_kind(request)]


def is_admin(request):
    return role_kind(request) == ADMIN


def is_staff_member(request):
    """Professeur ou administration : peut publier des annonces et modérer."""
    return role_kind(request) in (ADMIN, PROF)


def _profile(request, attr):
    membership = getattr(request, "membership", None)
    if membership is None:
        return None
    try:
        return getattr(membership, attr)
    except ObjectDoesNotExist:
        return None


def visible_classes(request):
    classes = SchoolClass.objects.filter(university=request.university)
    kind = role_kind(request)
    if kind == ADMIN:
        return classes
    if kind == PROF:
        profile = _profile(request, "professor_profile")
        return classes.filter(professors=profile) if profile else classes.none()
    profile = _profile(request, "student_profile")
    return classes.filter(groups__students=profile).distinct() if profile else classes.none()


def _class_scope(request, field="school_class"):
    if is_admin(request):
        return Q()
    return Q(**{f"{field}__isnull": True}) | Q(**{f"{field}__in": visible_classes(request)})


def forums_for(request):
    return Forum.objects.filter(university=request.university).filter(_class_scope(request))


def announcements_for(request):
    qs = Announcement.objects.filter(university=request.university)
    if is_admin(request):
        return qs
    scope = Q(audience=Announcement.AUDIENCE_ALL) | Q(school_class__in=visible_classes(request))
    if role_kind(request) == PROF:
        scope |= Q(author=request.user)
    return qs.filter(scope)


def threads_for(request, include_hidden=False):
    qs = Thread.objects.filter(university=request.university, forum__in=forums_for(request))
    if not (include_hidden or is_staff_member(request)):
        qs = qs.filter(is_hidden=False)
    return qs


def replies_for(request):
    return Reply.objects.filter(university=request.university, thread__forum__in=forums_for(request))


def messages_for(request):
    return Message.objects.filter(university=request.university)


def can_manage_forum(request, forum):
    """Administration, ou professeur qui enseigne la classe du forum / l'a créé."""
    if is_admin(request):
        return True
    if role_kind(request) != PROF:
        return False
    if forum.created_by_id == request.user.pk:
        return True
    return forum.school_class_id is not None and visible_classes(request).filter(pk=forum.school_class_id).exists()


def can_moderate(request, forum):
    return can_manage_forum(request, forum)


def can_validate_solution(request, forum):
    """Seul un professeur qui enseigne la classe du forum (ou l'a créé) valide une solution.

    Ni l'auteur de la question, ni l'administration : la validation est un acte pédagogique.
    """
    return role_kind(request) == PROF and can_manage_forum(request, forum)


def can_edit_announcement(request, announcement):
    return is_admin(request) or (role_kind(request) == PROF and announcement.author_id == request.user.pk)


def manageable_forums(request):
    forums = Forum.objects.filter(university=request.university)
    if is_admin(request):
        return forums
    if role_kind(request) == PROF:
        return forums.filter(Q(created_by=request.user) | Q(school_class__in=visible_classes(request)))
    return forums.none()


def reports_for(request):
    """Signalements que l'utilisateur peut traiter (professeur : ses forums)."""
    qs = Report.objects.filter(university=request.university)
    if is_admin(request):
        return qs
    forums = manageable_forums(request)
    return qs.filter(Q(thread__forum__in=forums) | Q(reply__thread__forum__in=forums)).distinct()
