"""Données de démonstration du module cours (idempotent).

Complète ``seed_demo`` avec un catalogue (départements, filières, matières), des
affectations d'enseignants, un emploi du temps par classe et des cours publiés
avec chapitres et supports PDF, pour parcourir le flux complet :
admin université → professeur → étudiant.
"""

from datetime import time
from io import BytesIO

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from accounts.models import Membership, SchoolClass, StudentGroup, University
from accounts.tenancy import Role
from courses.models import (
    Chapter, Course, CourseMaterial, Department, Program, ScheduleSlot, Subject, TeachingAssignment,
)
from courses.services import set_publication

PROFESSOR_PASSWORD = "Prof12345!"

EXTRA_PROFESSORS = (
    ("m.traore@u-paris.fr", "Mariam", "Traoré", "Informatique", "Bases de données", "maitre_assistant"),
    ("a.diallo@u-paris.fr", "Amadou", "Diallo", "Informatique", "Algorithmique", "assistant"),
)

PARIS = "Université Paris Cité"
LYON = "Université de Lyon"

# (nom, code, [filières]) ; une filière : (nom, code, diplôme, années, responsable)
DEPARTMENTS = {
    PARIS: (
        ("Informatique", "INFO", "prof.test@eduspark.local", (
            ("Licence Informatique", "LIC-INFO", "licence", 3, "prof.test@eduspark.local"),
            ("Master Génie Logiciel", "MST-GL", "master", 2, "m.traore@u-paris.fr"),
        )),
    ),
    LYON: (
        ("Mathématiques", "MATH", "prof.test@eduspark.local", (
            ("Master Mathématiques", "MST-MAT", "master", 2, "prof.test@eduspark.local"),
        )),
    ),
}

# Classe -> filière du catalogue
CLASS_PROGRAMS = {
    (PARIS, "Licence 3 Informatique"): "Licence Informatique",
    (PARIS, "Master 1 Génie Logiciel"): "Master Génie Logiciel",
    (LYON, "Master 1 Mathématiques"): "Master Mathématiques",
}

# (filière, code, intitulé, semestre, coef, ECTS, CM, TD, TP, description)
SUBJECTS = (
    ("Licence Informatique", "INF501", "Algorithmique avancée", 5, 3, 6, 21, 21, 12,
     "Graphes, complexité, algorithmes d'approximation."),
    ("Licence Informatique", "INF504", "Bases de données", 5, 2, 5, 14, 14, 14,
     "Modèle relationnel, SQL avancé, transactions."),
    ("Licence Informatique", "LAN301", "Anglais scientifique", 5, 1, 3, 21, 0, 0,
     "Lire et présenter un article scientifique en anglais."),
    ("Master Génie Logiciel", "GEN401", "Architecture applicative", 1, 3, 6, 21, 14, 7,
     "Architectures en couches, microservices, patrons de conception."),
    ("Master Génie Logiciel", "GEN402", "Revue de projet", 1, 2, 4, 0, 21, 0,
     "Suivi et revue des projets de l'année."),
    ("Master Mathématiques", "MAT401", "Analyse fonctionnelle", 1, 3, 6, 21, 21, 0, ""),
    ("Master Mathématiques", "MAT402", "Probabilités avancées", 1, 3, 6, 21, 14, 0, ""),
)

# (université, classe, matière, professeur)
ASSIGNMENTS = (
    (PARIS, "Licence 3 Informatique", "INF501", "prof.test@eduspark.local"),
    (PARIS, "Licence 3 Informatique", "INF504", "m.traore@u-paris.fr"),
    (PARIS, "Licence 3 Informatique", "LAN301", "m.traore@u-paris.fr"),
    (PARIS, "Master 1 Génie Logiciel", "GEN401", "prof.test@eduspark.local"),
    (PARIS, "Master 1 Génie Logiciel", "GEN402", "m.traore@u-paris.fr"),
    (LYON, "Master 1 Mathématiques", "MAT401", "prof.test@eduspark.local"),
    (LYON, "Master 1 Mathématiques", "MAT402", "prof.test@eduspark.local"),
)

# (université, classe, matière, professeur, type, jour, début, fin, salle, groupe)
SLOTS = (
    (PARIS, "Licence 3 Informatique", "INF501", "prof.test@eduspark.local", "cm", 0, "08:30", "10:00", "Amphi A", ""),
    (PARIS, "Licence 3 Informatique", "INF504", "m.traore@u-paris.fr", "cm", 1, "10:15", "11:45", "Salle 204", ""),
    (PARIS, "Licence 3 Informatique", "INF501", "prof.test@eduspark.local", "td", 2, "13:30", "15:00", "Salle 105", "TD A"),
    (PARIS, "Licence 3 Informatique", "INF501", "prof.test@eduspark.local", "tp", 2, "15:15", "16:45", "Salle machine B204", "TP B"),
    (PARIS, "Licence 3 Informatique", "INF504", "m.traore@u-paris.fr", "td", 3, "08:30", "10:00", "Salle 204", "TD A"),
    (PARIS, "Licence 3 Informatique", "LAN301", "m.traore@u-paris.fr", "cm", 4, "14:00", "16:00", "Salle D12", ""),
    (PARIS, "Master 1 Génie Logiciel", "GEN401", "prof.test@eduspark.local", "cm", 0, "10:15", "11:45", "Amphi B", ""),
    (PARIS, "Master 1 Génie Logiciel", "GEN402", "m.traore@u-paris.fr", "td", 4, "16:15", "17:45", "Salle projet", ""),
    (LYON, "Master 1 Mathématiques", "MAT401", "prof.test@eduspark.local", "cm", 1, "08:30", "10:00", "Amphi A", ""),
    (LYON, "Master 1 Mathématiques", "MAT402", "prof.test@eduspark.local", "td", 3, "10:15", "11:45", "Salle 105", ""),
)

# Cours : (université, professeur, matière, titre, présentation, publié pour, chapitres)
# Un chapitre : (titre, résumé, [(titre du support, lignes du PDF)])
COURSES = (
    (PARIS, "prof.test@eduspark.local", "INF501", "Algorithmique avancée — Graphes et complexité",
     "Objectifs : maîtriser les algorithmes de graphes et raisonner sur la complexité.\n"
     "Prérequis : structures de données de L2.\nÉvaluation : TP noté (30 %) et examen écrit (70 %).",
     ("Licence 3 Informatique",), (
         ("Parcours de graphes", "Largeur, profondeur, composantes connexes.", (
             ("Polycopié — Parcours de graphes", ("Parcours en largeur (BFS)", "Parcours en profondeur (DFS)", "Composantes connexes")),
         )),
         ("Plus courts chemins", "Dijkstra, Bellman-Ford, Floyd-Warshall.", (
             ("Fiche de TD 3 — Plus courts chemins", ("Exercice 1 : Dijkstra pas à pas", "Exercice 2 : détecter un cycle négatif")),
         )),
         ("NP-complétude", "Réductions polynomiales et problèmes NP-complets.", ()),
     ),
     (("Plan du cours et bibliographie", ("Cormen et al., Introduction à l'algorithmique", "Kleinberg & Tardos, Algorithm Design")),)),
    (PARIS, "prof.test@eduspark.local", "INF501", "Algorithmique — Approximation (brouillon)",
     "Cours en préparation : non publié.", (), (
         ("Algorithmes d'approximation", "À rédiger.", ()),
     ), ()),
    (PARIS, "prof.test@eduspark.local", "INF501", "Travaux pratiques d'algorithmique",
     "Sujets de TP en salle machine, un sujet par séance.", ("Licence 3 Informatique",), (
         ("TP 1 — Implémenter Dijkstra", "Python, file de priorité.", (
             ("Énoncé du TP 1", ("Implémenter Dijkstra avec heapq", "Comparer avec Bellman-Ford")),
         )),
     ), ()),
    (PARIS, "m.traore@u-paris.fr", "INF504", "Bases de données relationnelles",
     "Du modèle relationnel à l'optimisation de requêtes.", ("Licence 3 Informatique",), (
         ("Modèle relationnel et SQL", "Algèbre relationnelle, jointures, agrégats.", (
             ("Cours 1 — SQL avancé", ("Jointures et sous-requêtes", "Fonctions de fenêtrage")),
         )),
         ("Transactions", "ACID, isolation, verrouillage.", ()),
     ), ()),
    (PARIS, "prof.test@eduspark.local", "GEN401", "Architecture applicative",
     "Architectures en couches, hexagonale et microservices.", ("Master 1 Génie Logiciel",), (
         ("Architecture en couches", "Séparation des responsabilités.", (
             ("Slides — Architecture en couches", ("Présentation, métier, données", "Inversion de dépendances")),
         )),
     ), ()),
)


def build_pdf(title, lines):
    """PDF d'une page (reportlab) : titre puis une ligne par élément."""
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    page.setTitle(title)
    page.setFont("Helvetica-Bold", 18)
    page.drawString(72, 780, title)
    page.setFont("Helvetica", 12)
    y = 740
    for line in lines:
        page.drawString(72, y, line)
        y -= 20
    page.setFont("Helvetica-Oblique", 9)
    page.drawString(72, 60, "Document de démonstration EduSpark")
    page.showPage()
    page.save()
    return buffer.getvalue()


class Command(BaseCommand):
    help = (
        "Crée un catalogue de démonstration (filières, matières, affectations, emploi du temps, "
        "cours publiés). Idempotent ; exécute d'abord seed_demo."
    )

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Exécuter même quand DEBUG=False.")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "seed_courses est réservé au développement (DEBUG=False). "
                "Relancez avec --force pour l'exécuter malgré tout."
            )
        call_command("seed_demo", force=True, stdout=self.stdout, verbosity=0)

        with transaction.atomic():
            self.universities = {u.name: u for u in University.objects.filter(name__in=(PARIS, LYON))}
            self.professors = self.ensure_professors()
            self.create_catalogue()
            self.create_assignments()
            self.create_slots()
            self.create_courses()

        self.stdout.write(self.style.SUCCESS(
            "Seed terminé : %s départements, %s filières, %s matières, %s affectations, %s séances, "
            "%s cours (%s publiés), %s supports."
            % (
                Department.objects.count(), Program.objects.count(), Subject.objects.count(),
                TeachingAssignment.objects.count(), ScheduleSlot.objects.count(), Course.objects.count(),
                Course.objects.filter(publications__is_published=True).distinct().count(),
                CourseMaterial.objects.count(),
            )
        ))
        self.stdout.write(
            "Admin Paris : admin.paris@u-paris.fr / Admin12345!   (catalogue, affectations, emploi du temps)\n"
            "Professeur : prof.test@eduspark.local / Prof12345!   (cours, chapitres, supports, publication)\n"
            "Professeurs : m.traore@u-paris.fr, a.diallo@u-paris.fr / %s\n"
            "Étudiant : test.ui@example.com / Etudiant12345!   (classe L3 Informatique, groupe TD A)"
            % PROFESSOR_PASSWORD
        )

    # -- comptes ----------------------------------------------------------------
    def ensure_professors(self):
        paris = self.universities[PARIS]
        for email, first_name, last_name, department, speciality, grade in EXTRA_PROFESSORS:
            user = User.objects.filter(username__iexact=email).first() or User(username=email)
            user.email, user.first_name, user.last_name, user.is_active = email, first_name, last_name, True
            if not user.pk:
                user.set_password(PROFESSOR_PASSWORD)
            user.save()
            membership, _created = Membership.objects.update_or_create(
                user=user, university=paris, defaults={"role": Role.PROFESSOR, "is_active": True},
            )
            profile = membership.ensure_profile()
            profile.department, profile.speciality, profile.grade = department, speciality, grade
            profile.save()
        professors = {}
        for membership in Membership.objects.filter(
            role=Role.PROFESSOR, is_active=True, university__in=self.universities.values(),
        ).select_related("user", "university"):
            professors[(membership.university.name, membership.user.email)] = membership.professor_profile
        return professors

    def professor(self, university_name, email):
        return self.professors[(university_name, email)]

    # -- catalogue --------------------------------------------------------------
    def create_catalogue(self):
        self.programs = {}
        for university_name, departments in DEPARTMENTS.items():
            university = self.universities[university_name]
            for name, code, head, programs in departments:
                department, _created = Department.objects.update_or_create(
                    university=university, name=name,
                    defaults={"code": code, "head": self.professor(university_name, head)},
                )
                for program_name, program_code, degree, years, coordinator in programs:
                    program, _created = Program.objects.update_or_create(
                        university=university, name=program_name,
                        defaults={
                            "department": department, "code": program_code, "degree": degree,
                            "duration_years": years,
                            "coordinator": self.professor(university_name, coordinator),
                        },
                    )
                    self.programs[(university_name, program_name)] = program

        self.subjects = {}
        for program_name, code, name, semester, coefficient, credits, cm, td, tp, description in SUBJECTS:
            university_name = next(key[0] for key in self.programs if key[1] == program_name)
            program = self.programs[(university_name, program_name)]
            subject, _created = Subject.objects.update_or_create(
                university=program.university, code=code,
                defaults={
                    "program": program, "name": name, "semester": semester, "coefficient": coefficient,
                    "credits": credits, "hours_cm": cm, "hours_td": td, "hours_tp": tp,
                    "description": description, "is_active": True,
                },
            )
            self.subjects[(university_name, code)] = subject

        for (university_name, class_name), program_name in CLASS_PROGRAMS.items():
            school_class = self.school_class(university_name, class_name)
            school_class.study_program = self.programs[(university_name, program_name)]
            school_class.save()

    def school_class(self, university_name, class_name):
        return SchoolClass.objects.get(university=self.universities[university_name], name=class_name)

    # -- affectations et emploi du temps ---------------------------------------
    def create_assignments(self):
        self.assignments = {}
        for university_name, class_name, code, email in ASSIGNMENTS:
            assignment, _created = TeachingAssignment.objects.get_or_create(
                school_class=self.school_class(university_name, class_name),
                subject=self.subjects[(university_name, code)],
                professor=self.professor(university_name, email),
            )
            # seed_demo réinitialise l'encadrement des classes à chaque exécution : on le rétablit.
            assignment.school_class.professors.add(assignment.professor)
            self.assignments[(university_name, class_name, code, email)] = assignment

    def create_slots(self):
        for university_name, class_name, code, email, kind, weekday, start, end, room, group_name in SLOTS:
            assignment = self.assignments[(university_name, class_name, code, email)]
            group = (
                StudentGroup.objects.get(school_class=assignment.school_class, name=group_name)
                if group_name else None
            )
            slot, created = ScheduleSlot.objects.get_or_create(
                assignment=assignment, weekday=weekday, start_time=time.fromisoformat(start),
                group=group, session_type=kind,
                defaults={
                    "end_time": time.fromisoformat(end), "room": room,
                },
            )
            if created:
                slot.full_clean(exclude=["university"])  # garde-fou : le jeu de démo ne doit contenir aucun conflit

    # -- cours ------------------------------------------------------------------
    def create_courses(self):
        for (university_name, email, code, title, description, published_for,
             chapters, general_materials) in COURSES:
            professor = self.professor(university_name, email)
            course, _created = Course.objects.update_or_create(
                professor=professor, subject=self.subjects[(university_name, code)], title=title,
                defaults={"description": description},
            )
            for order, (chapter_title, summary, materials) in enumerate(chapters, start=1):
                chapter, _created = Chapter.objects.update_or_create(
                    course=course, title=chapter_title, defaults={"summary": summary, "order": order},
                )
                for material_title, lines in materials:
                    self.ensure_material(course, chapter, material_title, lines, professor)
            for material_title, lines in general_materials:
                self.ensure_material(course, None, material_title, lines, professor)
            for class_name in published_for:
                set_publication(course, self.school_class(university_name, class_name), True)

    def ensure_material(self, course, chapter, title, lines, professor):
        if CourseMaterial.objects.filter(course=course, title=title).exists():
            return
        slug = "".join(char if char.isalnum() else "-" for char in title.lower()).strip("-")
        CourseMaterial.objects.create(
            course=course, chapter=chapter, title=title, description="Support de démonstration.",
            file=ContentFile(build_pdf(title, lines), name="%s.pdf" % slug[:80]),
            uploaded_by=professor.user,
        )
