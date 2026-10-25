from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil, SchoolClass

EXAM_SEMESTER = "Semestre 1 · 2025-2026"

# Données de démonstration présentées dans les pages d'administration.
_EXAM_SESSIONS = {
    "Licence 3 Informatique": (
        {"date": "2025-11-03", "date_label": "Lundi 3 novembre", "start": "08:30", "end": "10:30",
         "course": "INF501 · Algorithmique avancée", "room": "Amphi A", "status": "Convocation envoyée"},
        {"date": "2025-11-06", "date_label": "Jeudi 6 novembre", "start": "13:30", "end": "15:30",
         "course": "MAT301 · Probabilités", "room": "Salle 204", "status": "Planifiée"},
    ),
    "Master 1 Génie Logiciel": (
        {"date": "2025-11-04", "date_label": "Mardi 4 novembre", "start": "08:30", "end": "10:30",
         "course": "INF502 · Systèmes distribués", "room": "Amphi B", "status": "Convocation envoyée"},
        {"date": "2025-11-07", "date_label": "Vendredi 7 novembre", "start": "10:15", "end": "12:15",
         "course": "GEN401 · Architecture applicative", "room": "Salle 204", "status": "Planifiée"},
    ),
    "Master 1 Mathématiques": (
        {"date": "2025-11-03", "date_label": "Lundi 3 novembre", "start": "10:15", "end": "12:15",
         "course": "MAT401 · Analyse fonctionnelle", "room": "Amphi A", "status": "Convocation envoyée"},
        {"date": "2025-11-06", "date_label": "Jeudi 6 novembre", "start": "08:30", "end": "10:30",
         "course": "MAT402 · Probabilités avancées", "room": "Salle 105", "status": "Planifiée"},
    ),
}

_CLASS_RECORDS = {
    "Licence 3 Informatique": {"students": 74, "average": "12,4", "pv_signed": True, "transcript_published": True},
    "Master 1 Génie Logiciel": {"students": 24, "average": "13,1", "pv_signed": False, "transcript_published": False},
    "Master 1 Mathématiques": {"students": 36, "average": "12,9", "pv_signed": False, "transcript_published": False},
}

_CLASS_RESULTS = {
    "Licence 3 Informatique": {"students": 74, "admitted": 66, "average": 12.4},
    "Master 1 Génie Logiciel": {"students": 24, "admitted": 22, "average": 13.1},
    "Master 1 Mathématiques": {"students": 36, "admitted": 29, "average": 12.9},
}


def _tenant_classes(request):
    return SchoolClass.objects.filter(university=request.university).order_by("name")


@role_required(Profil.ROLE_ETUDIANT)
def student_exams(request):
    return render(request, "exams/student_exams.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_transcript(request):
    return render(request, "exams/student_transcript.html")


@role_required(Profil.ROLE_PROF)
def prof_corrections(request):
    return render(request, "exams/prof_corrections.html")


@role_required(Profil.ROLE_PROF)
def prof_exam_sessions(request):
    return render(request, "exams/prof_exam_sessions.html")


@role_required(Profil.ROLE_PROF)
def prof_grade_sheets(request):
    return render(request, "exams/prof_grade_sheets.html")


@role_required(Profil.ROLE_ADMIN)
def admin_exam_sessions(request):
    sessions = []
    for school_class in _tenant_classes(request):
        for entry in _EXAM_SESSIONS.get(school_class.name, ()):
            sessions.append({
                **entry,
                "school_class": school_class,
                "tag": "convocation" if entry["status"] == "Convocation envoyée" else "planifiee",
            })
    sessions.sort(key=lambda session: (session["date"], session["start"]))
    return render(request, "exams/admin_exam_sessions.html", {
        "semester": EXAM_SEMESTER,
        "sessions": sessions,
        "session_count": len(sessions),
        "convocation_count": sum(1 for session in sessions if session["tag"] == "convocation"),
        "room_count": len({session["room"] for session in sessions}),
    })


@role_required(Profil.ROLE_ADMIN)
def admin_statistics(request):
    results = []
    for school_class in _tenant_classes(request):
        data = _CLASS_RESULTS.get(school_class.name)
        if not data:
            continue
        results.append({
            **data,
            "school_class": school_class,
            "rate": round(data["admitted"] * 100 / data["students"]),
            "rate_label": "%s %%" % round(data["admitted"] * 100 / data["students"]),
            "average_label": ("%.1f" % data["average"]).replace(".", ","),
        })
    students_total = sum(result["students"] for result in results)
    admitted_total = sum(result["admitted"] for result in results)
    weighted_average = (
        sum(result["average"] * result["students"] for result in results) / students_total
        if students_total else 0
    )
    return render(request, "exams/admin_statistics.html", {
        "semester": EXAM_SEMESTER,
        "results": results,
        "class_count": len(results),
        "students_total": students_total,
        "admitted_total": admitted_total,
        "success_rate": round(admitted_total * 100 / students_total) if students_total else 0,
        "average_label": ("%.1f" % weighted_average).replace(".", ","),
    })


@role_required(Profil.ROLE_ADMIN)
def admin_official_records(request):
    records = []
    for school_class in _tenant_classes(request):
        data = _CLASS_RECORDS.get(school_class.name)
        if not data:
            continue
        records.append({**data, "school_class": school_class})
    return render(request, "exams/admin_official_records.html", {
        "semester": EXAM_SEMESTER,
        "records": records,
        "jury_count": len(records),
        "published_count": sum(1 for record in records if record["transcript_published"]),
        "pending_count": sum(1 for record in records if not record["pv_signed"]),
    })
