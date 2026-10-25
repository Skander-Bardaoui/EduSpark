from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil, ProfessorProfile, SchoolClass

# Répartition de démonstration par classe (l'affectation réelle n'est pas stockée).
_TUTOR_ALLOCATION = {
    "Licence 3 Informatique": {"students": 74, "tutors": 4, "assigned": 66},
    "Master 1 Génie Logiciel": {"students": 42, "tutors": 3, "assigned": 40},
    "Master 1 Mathématiques": {"students": 86, "tutors": 6, "assigned": 71},
}
_DEFAULT_TUTOR_ALLOCATION = {"students": 40, "tutors": 2, "assigned": 34}

ACADEMIC_YEAR = "2025-2026"


def _tenant_classes(request):
    return list(
        SchoolClass.objects.filter(university=request.university).order_by("name")
    )


def _build_allocation_rows(classes):
    rows = []
    for school_class in classes:
        data = _TUTOR_ALLOCATION.get(school_class.name, _DEFAULT_TUTOR_ALLOCATION)
        waiting = max(data["students"] - data["assigned"], 0)
        rate = round(data["assigned"] * 100 / data["students"]) if data["students"] else 0
        if rate >= 100:
            status, status_class, tags = "Complet", "bg-primary-fixed text-primary", "a_jour"
        elif rate >= 90:
            status, status_class, tags = "À jour", "bg-primary-fixed text-primary", "a_jour"
        else:
            status, status_class, tags = "À compléter", "bg-error-container text-on-error-container", "a_completer"
        rows.append({
            "school_class": school_class,
            "students": data["students"],
            "tutors": data["tutors"],
            "assigned": data["assigned"],
            "waiting": waiting,
            "rate": rate,
            "status": status,
            "status_class": status_class,
            "tags": tags,
        })
    return rows


@role_required(Profil.ROLE_ETUDIANT)
def student_dashboard(request):
    return render(request, "coaching/student_dashboard.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_progress(request):
    return render(request, "coaching/student_progress.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_tasks(request):
    return render(request, "coaching/student_tasks.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_appointments(request):
    return render(request, "coaching/student_appointments.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_journal(request):
    return render(request, "coaching/student_journal.html")


@role_required(Profil.ROLE_PROF)
def prof_dashboard(request):
    return render(request, "coaching/prof_dashboard.html")


@role_required(Profil.ROLE_PROF)
def prof_followup(request):
    return render(request, "coaching/prof_followup.html")


@role_required(Profil.ROLE_PROF)
def prof_tutoring(request):
    return render(request, "coaching/prof_tutoring.html")


@role_required(Profil.ROLE_PROF)
def prof_followup_cards(request):
    return render(request, "coaching/prof_followup_cards.html")


@role_required(Profil.ROLE_PROF)
def prof_student_journal(request):
    return render(request, "coaching/prof_student_journal.html")


@role_required(Profil.ROLE_ADMIN)
def admin_dashboard(request):
    return render(request, "coaching/admin_dashboard.html")


@role_required(Profil.ROLE_ADMIN)
def admin_perseverance(request):
    rows = _build_allocation_rows(_tenant_classes(request))
    students_total = sum(row["students"] for row in rows)
    assigned_total = sum(row["assigned"] for row in rows)
    waiting_total = max(students_total - assigned_total, 0)
    rate = round(assigned_total * 100 / students_total) if students_total else 0
    tutor_options = [
        profile.membership.user.get_full_name() or profile.membership.user.email
        for profile in ProfessorProfile.objects.filter(university=request.university)
        .select_related("membership__user")
        .order_by("membership__user__last_name", "membership__user__first_name")
    ]
    return render(request, "coaching/admin_perseverance.html", {
        "rows": rows,
        "row_count": len(rows),
        "assigned_total": assigned_total,
        "waiting_total": waiting_total,
        "students_hint": "Sur %d étudiants inscrits" % students_total,
        "waiting_hint": "%d étudiant%s en attente d'affectation" % (
            waiting_total, "" if waiting_total == 1 else "s",
        ),
        "tutor_total": sum(row["tutors"] for row in rows),
        "allocation_rate_label": "%d %%" % rate,
        "tutor_options": tutor_options,
        "academic_year": ACADEMIC_YEAR,
    })


@role_required(Profil.ROLE_ADMIN)
def admin_monitoring(request):
    return render(request, "coaching/admin_monitoring.html")
