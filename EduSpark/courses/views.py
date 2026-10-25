from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import Profil, SchoolClass, StudentProfile

WEEKDAYS = ("Lundi 20", "Mardi 21", "Mercredi 22", "Jeudi 23", "Vendredi 24")

# Planning de démonstration (aucune séance n'est stockée en base).
_DEMO_SESSIONS = {
    "Licence 3 Informatique": (
        (0, "08:30", "10:00", "INF501", "Algorithmique avancée", "CM", "Amphi A", "H. Vasseur"),
        (1, "10:15", "11:45", "MAT301", "Probabilités", "CM", "Salle 204", "S. Lambert"),
        (2, "13:30", "15:00", "TP INF501", "Algorithmique avancée", "TP", "Salle machine B204", "A. Diallo"),
        (3, "08:30", "10:00", "INF504", "Bases de données", "CM", "Salle 204", "M. Traoré"),
    ),
    "Master 1 Génie Logiciel": (
        (0, "10:15", "11:45", "INF502", "Systèmes distribués", "CM", "Amphi B", "H. Vasseur"),
        (1, "13:30", "15:00", "TP GEN", "Atelier génie logiciel", "TP", "Labo info", "A. Diallo"),
        (2, "08:30", "10:00", "GEN401", "Architecture applicative", "CM", "Amphi B", "M. Traoré"),
        (4, "13:30", "15:00", "GEN402", "Revue de projet", "TD", "Salle projet", "H. Vasseur"),
    ),
    "Master 1 Mathématiques": (
        (0, "08:30", "10:00", "MAT401", "Analyse fonctionnelle", "CM", "Amphi A", "É. Moreau"),
        (1, "10:15", "11:45", "MAT402", "Probabilités avancées", "CM", "Salle 105", "S. Lambert"),
        (2, "13:30", "15:00", "TP MAT", "Analyse numérique", "TP", "Salle 105", "É. Moreau"),
        (3, "08:30", "10:00", "MAT201", "Algèbre bilinéaire", "CM", "Amphi B", "Dr. Leroux"),
    ),
}


def _build_class_timetable(school_class):
    sessions = [
        {
            "day": day,
            "start": start,
            "end": end,
            "code": code,
            "title": title,
            "kind": kind,
            "room": room,
            "teacher": teacher,
        }
        for day, start, end, code, title, kind, room, teacher
        in _DEMO_SESSIONS.get(school_class.name, ())
    ]
    days = [{"label": label, "sessions": []} for label in WEEKDAYS]
    for session in sessions:
        days[session["day"]]["sessions"].append(session)
    return {
        "school_class": school_class,
        "days": days,
        "session_count": len(sessions),
        "teacher_count": len({session["teacher"] for session in sessions}),
        "group_count": school_class.groups.count(),
    }


_STUDENT_COURSES = (
    {
        "code": "INF501", "title": "Algorithmique avancée", "teacher": "H. Vasseur",
        "ects": 6, "status": "Obligatoire", "progress": 68, "validated": False,
        "tags": ("obligatoire",),
    },
    {
        "code": "MAT301", "title": "Probabilités", "teacher": "S. Lambert",
        "ects": 4, "status": "Obligatoire", "progress": 55, "validated": False,
        "tags": ("obligatoire",),
    },
    {
        "code": "INF504", "title": "Bases de données", "teacher": "M. Traoré",
        "ects": 5, "status": "Obligatoire", "progress": 82, "validated": False,
        "tags": ("obligatoire",),
    },
    {
        "code": "LAN301", "title": "Anglais scientifique", "teacher": "C. Petit",
        "ects": 3, "status": "Optionnel", "progress": 100, "validated": True,
        "tags": ("optionnel", "valide"),
    },
)


@role_required(Profil.ROLE_ETUDIANT)
def student_catalogue(request):
    profile = None
    if request.membership is not None:
        profile = StudentProfile.objects.filter(membership=request.membership).first()
    school_class = None
    if profile is not None:
        group = profile.groups.select_related("school_class").first()
        if group is not None:
            school_class = group.school_class
    courses = [
        dict(course, tags=" ".join(course["tags"])) for course in _STUDENT_COURSES
    ]
    return render(request, "courses/student_catalogue.html", {
        "profile": profile,
        "school_class": school_class,
        "courses": courses,
        "course_count": len(courses),
        "ects_total": sum(course["ects"] for course in courses),
        "average_progress": (
            round(sum(course["progress"] for course in courses) / len(courses))
            if courses else 0
        ),
        "validated_count": sum(1 for course in courses if course["validated"]),
    })


@role_required(Profil.ROLE_ETUDIANT)
def student_timetable(request):
    return render(request, "courses/student_timetable.html")


@role_required(Profil.ROLE_PROF)
def prof_course(request):
    return render(request, "courses/prof_course.html")


@role_required(Profil.ROLE_PROF)
def prof_timetable(request):
    return render(request, "courses/prof_timetable.html")


@role_required(Profil.ROLE_PROF)
def prof_subjects(request):
    return render(request, "courses/prof_subjects.html")


@role_required(Profil.ROLE_ETUDIANT)
def student_course_materials(request):
    return render(request, "courses/student_course_materials.html")


@role_required(Profil.ROLE_PROF)
def prof_course_materials(request):
    return render(request, "courses/prof_course_materials.html")


@role_required(Profil.ROLE_ADMIN)
def admin_timetable(request):
    school_classes = (
        SchoolClass.objects.filter(university=request.university)
        .prefetch_related("groups")
        .order_by("name")
    )
    timetables = [_build_class_timetable(school_class) for school_class in school_classes]
    sessions = [session for entry in timetables for day in entry["days"] for session in day["sessions"]]
    return render(request, "courses/admin_timetable.html", {
        "timetables": timetables,
        "class_count": len(timetables),
        "session_count": len(sessions),
        "teacher_count": len({session["teacher"] for session in sessions}),
    })


@role_required(Profil.ROLE_ADMIN)
def admin_program_offer(request):
    return render(request, "courses/admin_program_offer.html")


@role_required(Profil.ROLE_ADMIN)
def admin_courses(request):
    return render(request, "courses/admin_courses.html")
