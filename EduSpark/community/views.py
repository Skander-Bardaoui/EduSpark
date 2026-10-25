from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil, SchoolClass

# Activité de démonstration par classe (aucun message n'est stocké en base).
_FORUM_ACTIVITY = {
    "Licence 3 Informatique": {"messages": 642, "members": 86, "last": "il y a 12 min"},
    "Master 1 Génie Logiciel": {"messages": 318, "members": 42, "last": "il y a 44 min"},
    "Master 1 Mathématiques": {"messages": 411, "members": 74, "last": "il y a 1 h"},
}
_DEFAULT_FORUM_ACTIVITY = {"messages": 216, "members": 36, "last": "il y a 2 h"}


def _tenant_classes(request):
    return list(
        SchoolClass.objects.filter(university=request.university).order_by("name")
    )


def _build_forum_rows(classes):
    rows = []
    for index, school_class in enumerate(classes):
        activity = _FORUM_ACTIVITY.get(school_class.name, _DEFAULT_FORUM_ACTIVITY)
        row = {
            "name": f"Forum {school_class.name}",
            "class_label": " · ".join(
                part for part in (school_class.level, school_class.program) if part
            ),
            "messages": activity["messages"],
            "members": activity["members"],
            "last": activity["last"],
            "tags": "actif surveillance" if index == 0 else "actif",
            "status": "Sous surveillance" if index == 0 else "Actif",
            "status_class": (
                "bg-error-container text-on-error-container"
                if index == 0
                else "bg-primary-fixed text-primary"
            ),
            "status_dot": index != 0,
        }
        rows.append(row)
    rows.append({
        "name": "Forum Vie de campus",
        "class_label": "Toutes les promotions",
        "messages": 892,
        "members": 420,
        "last": "il y a 6 min",
        "tags": "actif",
        "status": "Actif",
        "status_class": "bg-primary-fixed text-primary",
        "status_dot": True,
    })
    return rows


@role_required(Profil.ROLE_ETUDIANT)
def student_forums(request):
    return render(request, "community/student_forums.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_announcements(request):
    return render(request, "community/student_announcements.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_messages(request):
    return render(request, "community/student_messages.html")


@role_required(Profil.ROLE_PROF)
def prof_forums(request):
    return render(request, "community/prof_forums.html")


@role_required(Profil.ROLE_PROF)
def prof_announcements(request):
    return render(request, "community/prof_announcements.html")


@role_required(Profil.ROLE_PROF)
def prof_messages(request):
    return render(request, "community/prof_messages.html")


@role_required(Profil.ROLE_PROF)
def prof_moderation(request):
    return render(request, "community/prof_moderation.html")


@role_required(Profil.ROLE_ADMIN)
def admin_communication(request):
    return render(request, "community/admin_communication.html", {
        "classes": _tenant_classes(request),
    })


@role_required(Profil.ROLE_ADMIN)
def admin_forum_supervision(request):
    classes = _tenant_classes(request)
    forums = _build_forum_rows(classes)
    return render(request, "community/admin_forum_supervision.html", {
        "classes": classes,
        "forums": forums,
        "forum_count": len(forums),
        "message_count": sum(row["messages"] for row in forums),
        "moderator_count": len(classes) + 2,
    })


@role_required(Profil.ROLE_ADMIN)
def admin_reports(request):
    classes = _tenant_classes(request)
    return render(request, "community/admin_reports.html", {
        "main_class": classes[0] if classes else None,
    })
