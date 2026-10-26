"""Jeu de données de démonstration du module Suivi Référent (idempotent)."""

from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import (
    Membership,
    ProfessorProfile,
    SchoolClass,
    StudentProfile,
    University,
)
from accounts.tenancy import Role

from coaching.models import (
    AttendanceRecord,
    AttendanceSession,
    DifficultyNote,
    DifficultySheet,
    JournalEntry,
    PerseveranceAlert,
    StudentGoal,
    StudentTask,
    StudySession,
    TutorAssignment,
    TutorNotification,
    TutoringSession,
    TutoringSlot,
)
from coaching.services import academic_year_for, sync_student_attendance

PARIS = "Université Paris Cité"
LYON = "Université de Lyon"
PROFESSOR_EMAIL = "prof.test@eduspark.local"
SEED_SLOT_PREFIX = "SEED-"
PARIS_STUDENTS = ("test.ui@example.com", "ines.bernard@u-paris.fr", "yanis.leroy@u-paris.fr")
LYON_STUDENTS = ("lucas.moreau@univ-lyon.fr", "sofia.benali@univ-lyon.fr")
ATTENDANCE_WEEKS = 10
ATTENDANCE_PER_WEEK = 5
PARIS_MODULES = (
    "INFO301 — Algorithmique avancée",
    "INFO303 — Bases de données",
    "INFO302 — Développement web",
    "ANG201 — Anglais technique",
    "INFO304 — Systèmes distribués",
)
LYON_MODULES = (
    "MAT501 — Probabilités",
    "MAT502 — Algèbre",
    "MAT503 — Analyse fonctionnelle",
    "MAT504 — Méthodologie de la recherche",
    "MAT505 — Statistiques",
)

GOALS = {
    "test.ui@example.com": (
        ("Consolider les bases en algorithmique", "INFO301", "in_progress", 65, 6, 9, 21, None),
        ("Réussir le projet de développement web", "INFO302", "at_risk", 40, 3, 8, 35, None),
        ("Valider l'UE de bases de données", "INFO303", "achieved", 100, 10, 10, -12, "15.50"),
    ),
    "ines.bernard@u-paris.fr": (
        ("Préparer le mémoire de licence", "INFO399", "in_progress", 70, 7, 10, 40, None),
    ),
    "yanis.leroy@u-paris.fr": (
        ("Remonter la moyenne du semestre", "INFO300", "at_risk", 25, 2, 6, 14, None),
    ),
    "lucas.moreau@univ-lyon.fr": (
        ("Sécuriser les probabilités discrètes", "MAT501", "in_progress", 55, 4, 8, 18, None),
        ("Améliorer la rédaction des preuves", "MAT502", "at_risk", 30, 2, 6, 30, None),
    ),
    "sofia.benali@univ-lyon.fr": (
        ("Approfondir l'analyse fonctionnelle", "MAT503", "in_progress", 75, 7, 9, 25, None),
        ("Préparer le mémoire de recherche", "MAT504", "in_progress", 45, 3, 7, 50, None),
    ),
}

TASKS = (
    ("Relire le chapitre 4 — Arbres binaires", "Algorithmique · INFO301", "today", "high", 0, False),
    ("Terminer l'exercice 3 du TD", "Algorithmique · TD A", "today", "high", 0, False),
    ("Préparer la démonstration du projet", "Projet web · INFO302", "today", "normal", 1, False),
    ("Réviser les jointures SQL", "Bases de données · INFO303", "week", "normal", 3, False),
    ("Corriger le compte rendu de TP", "Systèmes · TP B", "week", "low", 4, True),
    ("Lire l'article sur les design patterns", "Veille · Informatique", "week", "low", 5, False),
    ("Mettre à jour le CV", "Orientation", "today", "low", 0, True),
)

JOURNAL = (
    ("Une semaine plus sereine", "confidence", 8, 0,
     "J'ai réussi à terminer le TD sans relire le cours. La méthode vue en permanence m'aide vraiment à découper les problèmes.",
     "Belle progression : continue à verbaliser ta démarche avant de coder.", 0),
    ("Le projet avance", "neutral", 6, 4,
     "Le groupe a validé la maquette. Je dois encore prendre du temps pour comprendre la partie authentification.",
     "", None),
    ("Première soutenance blanche", "pride", 9, 9,
     "J'ai présenté devant la classe et les questions du jury ne m'ont pas déstabilisée. Je me sens enfin légitime.",
     "Présentation claire et bien rythmée. Garde ce support pour la soutenance finale.", -8),
    ("Fatigue en milieu de semaine", "attention", 4, 16,
     "Trop de travail accumulé mardi, j'ai décroché pendant le cours de bases de données. Il faut que je fractionne mes révisions.",
     "", None),
    ("Meilleure organisation", "confidence", 7, 30,
     "J'ai testé le planning par blocs de 45 minutes. Résultat : moins de procrastination et plus de travail effectif.",
     "", None),
    ("Rentrée et nouveaux objectifs", "pride", 9, 45,
     "Je me sens motivée pour ce semestre. Mon objectif est de garder un rythme régulier plutôt que de tout faire à la dernière minute.",
     "", None),
)

SHEETS = (
    {
        "student": "yanis.leroy@u-paris.fr",
        "category": "attendance",
        "severity": "high",
        "status": "open",
        "observation": "Absences répétées en TD et en TP depuis trois semaines. Les rendus du projet sont incomplets malgré les relances.",
        "action_plan": "Appel de la scolarité, rendez-vous individuel et point hebdomadaire avec le référent pendant un mois.",
        "average": "8.90",
        "attendance": 74,
        "submitted": 4,
        "total": 9,
        "opened": -10,
        "contact": -9,
        "notes": (
            ("Appel téléphonique : l'étudiant évoque des difficultés de transport et de sommeil. Accord pour un point chaque lundi.", -9),
            ("Premier point réalisé. Présence rétablie cette semaine, travail à consolider sur le projet.", -2),
        ),
    },
    {
        "student": "yanis.leroy@u-paris.fr",
        "category": "methodology",
        "severity": "moderate",
        "status": "in_progress",
        "observation": "Difficulté à structurer les preuves et à réutiliser les méthodes vues en cours. Les exercices sont souvent commencés sans plan.",
        "action_plan": "Atelier méthode : fiche de résolution, reformulation de l'énoncé puis résolution guidée.",
        "average": "8.90",
        "attendance": 74,
        "submitted": 4,
        "total": 9,
        "opened": -6,
        "contact": -2,
        "notes": (
            ("Atelier réalisé : la fiche de résolution est adoptée. À vérifier sur le prochain devoir.", -2),
        ),
    },
    {
        "student": "test.ui@example.com",
        "category": "workload",
        "severity": "regular",
        "status": "in_progress",
        "observation": "Charge de travail élevée entre le projet web et les révisions. Risque de dispersion sur les échéances de fin de semestre.",
        "action_plan": "Découpage des tâches par semaine et priorisation des rendus. Point de suivi tous les quinze jours.",
        "average": "12.40",
        "attendance": 92,
        "submitted": 8,
        "total": 10,
        "opened": -5,
        "contact": -1,
        "notes": (
            ("Planning allégé validé avec l'étudiante. Les échéances du projet sont désormais étalées.", -1),
        ),
    },
    {
        "student": "ines.bernard@u-paris.fr",
        "category": "orientation",
        "severity": "moderate",
        "status": "open",
        "observation": "Hésitation entre le master recherche et l'entrée dans la vie professionnelle. Manque de visibilité sur les prérequis.",
        "action_plan": "Rendez-vous avec le service orientation et rencontre avec deux anciennes étudiantes.",
        "average": "15.20",
        "attendance": 98,
        "submitted": 10,
        "total": 10,
        "opened": -3,
        "contact": -3,
        "notes": (),
    },
)


def _aware(offset_days=0, hour=9, minute=0):
    day = timezone.localdate() + timedelta(days=offset_days)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def _since(days=0, hours=0):
    return timezone.now() - timedelta(days=days, hours=hours)


def _email(profile):
    return profile.membership.user.email


class Command(BaseCommand):
    help = "Crée les données de démonstration du suivi référent (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Exécuter même quand DEBUG=False.",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "seed_coaching est réservé au développement (DEBUG=False). "
                "Relancez avec --force pour l'exécuter malgré tout."
            )

        base = self.resolve_base()
        with transaction.atomic():
            self.seed_university(base, "paris")
            self.seed_university(base, "lyon")

        totals = {
            "affectations": TutorAssignment.objects.count(),
            "objectifs": StudentGoal.objects.count(),
            "sessions": StudySession.objects.count(),
            "tâches": StudentTask.objects.count(),
            "journal": JournalEntry.objects.count(),
            "créneaux": TutoringSlot.objects.count(),
            "rendez-vous": TutoringSession.objects.count(),
            "fiches": DifficultySheet.objects.count(),
            "alertes": PerseveranceAlert.objects.count(),
            "séances": AttendanceSession.objects.count(),
            "présences": AttendanceRecord.objects.count(),
        }
        self.stdout.write(self.style.SUCCESS(
            "Seed coaching terminé : %s." % ", ".join(
                "%s %s" % (value, label) for label, value in totals.items()
            )
        ))

    # -- résolution du socle existant ---------------------------------------
    def resolve_base(self):
        universities = {}
        for name in (PARIS, LYON):
            university = University.objects.filter(name=name).first()
            if university is None:
                raise CommandError(
                    "Université « %s » introuvable. Lancez d'abord "
                    "`python manage.py seed_demo`." % name
                )
            universities[name] = university

        for university in universities.values():
            if not Membership.objects.filter(
                university=university,
                user__email__iexact=PROFESSOR_EMAIL,
                role=Role.PROFESSOR,
                is_active=True,
            ).exists():
                raise CommandError(
                    "Professeur %s introuvable dans %s. Lancez d'abord "
                    "`python manage.py seed_demo`." % (PROFESSOR_EMAIL, university)
                )

        for name, emails in ((PARIS, PARIS_STUDENTS), (LYON, LYON_STUDENTS)):
            for email in emails:
                if not Membership.objects.filter(
                    university=universities[name],
                    user__email__iexact=email,
                    role=Role.STUDENT,
                    is_active=True,
                ).exists():
                    raise CommandError(
                        "Étudiant %s introuvable dans %s. Lancez d'abord "
                        "`python manage.py seed_demo`." % (email, name)
                    )
        return universities

    def _student(self, university, email):
        membership = Membership.objects.filter(
            university=university, user__email__iexact=email, is_active=True,
        ).first()
        if membership is None or membership.role != Role.STUDENT:
            raise CommandError(
                "Étudiant %s introuvable dans %s. Lancez `seed_demo`." % (email, university)
            )
        return membership.ensure_profile()

    def _professor(self, university):
        membership = Membership.objects.filter(
            university=university, user__email__iexact=PROFESSOR_EMAIL, is_active=True,
        ).first()
        if membership is None or membership.role != Role.PROFESSOR:
            raise CommandError(
                "Professeur %s introuvable dans %s. Lancez `seed_demo`." % (
                    PROFESSOR_EMAIL, university,
                )
            )
        return membership.ensure_profile()

    def _admin_user(self, university):
        membership = Membership.objects.filter(
            university=university, role=Role.UNIVERSITY_ADMIN, is_active=True,
        ).select_related("user").first()
        return membership.user if membership else None

    def _class(self, university, name):
        school_class = SchoolClass.objects.filter(
            university=university, name=name,
        ).order_by("-academic_year").first()
        if school_class is None:
            raise CommandError(
                "Classe « %s » introuvable dans %s. Lancez `seed_demo`." % (
                    name, university,
                )
            )
        return school_class

    # -- jeu de données -------------------------------------------------------
    def seed_university(self, universities, key):
        if key == "paris":
            university = universities[PARIS]
            professor = self._professor(university)
            admin = self._admin_user(university)
            school_class = self._class(university, "Licence 3 Informatique")
            year = school_class.academic_year or academic_year_for(university)
            students = {
                email: self._student(university, email)
                for email in (
                    "test.ui@example.com",
                    "ines.bernard@u-paris.fr",
                    "yanis.leroy@u-paris.fr",
                )
            }
            camille = students["test.ui@example.com"]
            ines = students["ines.bernard@u-paris.fr"]
            yanis = students["yanis.leroy@u-paris.fr"]

            self._assign(camille, professor, school_class, year, admin, {
                "average_grade": "12.40", "previous_average": "13.10",
                "attendance_rate": 92, "assignments_submitted": 8, "assignments_total": 10,
                "risk_level": TutorAssignment.RISK_WATCH,
                "risk_reason": "Baisse de régime sur les rendus du projet, investissement irrégulier en TD.",
                "last_contact_at": _since(2, 3),
            })
            self._assign(ines, professor, school_class, year, admin, {
                "average_grade": "15.20", "previous_average": "15.00",
                "attendance_rate": 98, "assignments_submitted": 10, "assignments_total": 10,
                "risk_level": TutorAssignment.RISK_LOW,
                "risk_reason": "",
                "last_contact_at": _since(1, 2),
            })
            self._assign(yanis, professor, school_class, year, admin, {
                "average_grade": "8.90", "previous_average": "10.20",
                "attendance_rate": 74, "assignments_submitted": 4, "assignments_total": 9,
                "risk_level": TutorAssignment.RISK_HIGH,
                "risk_reason": "Absences répétées et décrochage sur les évaluations récentes.",
                "last_contact_at": _since(9, 4),
            })

            self._goals(students)
            self._study_sessions(camille, (
                ("Cours — Algorithmique avancée", "INFO301", StudySession.KIND_COURSE,
                 0, 8, 30, 90, StudySession.STATUS_COMPLETED, "Amphi B"),
                ("Révision — Bases de données", "INFO303", StudySession.KIND_REVISION,
                 1, 18, 0, 60, StudySession.STATUS_SCHEDULED, "Bibliothèque"),
                ("Révision — Anglais technique", "ANG201", StudySession.KIND_REVISION,
                 2, 17, 30, 45, StudySession.STATUS_SCHEDULED, "Salle 204"),
                ("Examen — Algorithmique avancée", "INFO301", StudySession.KIND_EXAM,
                 10, 9, 0, 120, StudySession.STATUS_SCHEDULED, "Amphi B"),
            ))
            self._camille_tasks(camille)
            self._journal(camille, professor)
            self._journal(ines, professor, (
                ("Un semestre qui se dessine", "confidence", 8, 2,
                 "Les portes ouvertes du master recherche m'ont rassurée. Je vais demander un rendez-vous au responsable de parcours.",
                 "Très bonne initiative. Prépare trois questions précises avant l'entretien.", -1),
                ("Doute sur mon orientation", "attention", 5, 12,
                 "Je compare encore beaucoup avec les autres et je perds du temps. J'ai besoin de clarifier mes critères de choix.",
                 "", None),
            ))
            self._journal(yanis, professor, (
                ("Reprendre le rythme", "neutral", 5, 3,
                 "J'ai assisté à tous les cours cette semaine. Le réveil reste difficile mais je me tiens à l'objectif.",
                 "Premier pas important. On fait le point lundi sur les devoirs en retard.", -2),
            ))

            slots = self._slots(professor, school_class, "PARIS", (
                (1, 9, 0, TutoringSlot.MODE_INDIVIDUAL, "Bureau 214", TutoringSlot.STATUS_OPEN),
                (1, 14, 30, TutoringSlot.MODE_VIDEO, "", TutoringSlot.STATUS_OPEN),
                (2, 10, 0, TutoringSlot.MODE_INDIVIDUAL, "Bureau 214", TutoringSlot.STATUS_BOOKED),
                (3, 15, 0, TutoringSlot.MODE_GROUP, "Salle de tutorat", TutoringSlot.STATUS_OPEN),
                (4, 9, 30, TutoringSlot.MODE_VIDEO, "", TutoringSlot.STATUS_OPEN),
                (5, 16, 0, TutoringSlot.MODE_INDIVIDUAL, "Bureau 214", TutoringSlot.STATUS_OPEN),
                (6, 11, 0, TutoringSlot.MODE_INDIVIDUAL, "Bureau 214", TutoringSlot.STATUS_OPEN),
            ))
            self._sessions(professor, school_class, {
                "camille": camille, "ines": ines, "yanis": yanis,
            }, slots)

            sheets = self._sheets(university, professor, students, SHEETS[:3])
            self._sheets(university, professor, {"ines.bernard@u-paris.fr": ines}, SHEETS[3:])

            self._alert(yanis, school_class, "attendance", {
                "title": "Absences répétées · Yanis Leroy",
                "detail": "Quatre absences non justifiées et deux rendus manquants sur les trois dernières semaines.",
                "priority": PerseveranceAlert.PRIORITY_HIGH,
                "status": PerseveranceAlert.STATUS_OPEN,
                "reported_by": professor,
                "detected_at": _since(10),
            })
            self._alert(camille, school_class, "confidence", {
                "title": "Baisse de confiance · Camille Martin",
                "detail": "Le journal de progression signale une fatigue en milieu de semaine et une baisse de confiance.",
                "priority": PerseveranceAlert.PRIORITY_NORMAL,
                "status": PerseveranceAlert.STATUS_OPEN,
                "reported_by": professor,
                "detected_at": _since(4),
            })
            self._alert(yanis, school_class, "grade", {
                "title": "Décrochage sur les évaluations · Yanis Leroy",
                "detail": "Moyenne en recul de 1,3 point sur les deux dernières évaluations.",
                "priority": PerseveranceAlert.PRIORITY_HIGH,
                "status": PerseveranceAlert.STATUS_TAKEN,
                "reported_by": professor,
                "detected_at": _since(12),
                "taken_by": admin,
                "taken_at": _since(10),
                "handling_note": "Entretien programmé avec le référent et la scolarité ; emploi du temps allégé cette semaine.",
                "resolution_note": "",
            })
            self._alert(ines, school_class, "engagement", {
                "title": "Signalement pédagogique · Ines Bernard",
                "detail": "Participation en baisse depuis la rentrée, l'étudiante traverse une période de doute sur son orientation.",
                "priority": PerseveranceAlert.PRIORITY_NORMAL,
                "status": PerseveranceAlert.STATUS_CLOSED,
                "reported_by": professor,
                "detected_at": _since(20),
                "taken_by": admin,
                "taken_at": _since(17),
                "handling_note": "Rendez-vous avec le responsable de parcours et avis du service d'orientation.",
                "closed_at": _since(14),
                "resolution_note": "Entretien réalisé avec le responsable de parcours ; l'étudiante a validé son choix de master.",
            })
            self._relance(yanis, professor, {
                "title": "Faire le point sur ta progression",
                "message": "Bonjour Yanis, je souhaite que l'on fasse le point sur ta progression. Tes absences récentes et les rendus manquants m'inquiètent. Peux-tu me répondre ici et, si besoin, réserver un créneau de tutorat ?",
                "read_at": _since(1, 20),
                "reply": "Bonjour Monsieur, merci pour votre message. Je reprends les devoirs cette semaine et je réserve le créneau de jeudi.",
                "replied_at": _since(1, 20),
                "created_at": _since(2),
            })
            self._relance(camille, professor, {
                "title": "Faire le point sur ta progression",
                "message": "Bonjour Camille, je souhaite que l'on fasse le point sur ta progression. Ta baisse de régime sur les rendus du projet me questionne. Peux-tu me répondre ici et, si besoin, réserver un créneau de tutorat ?",
                "read_at": None,
                "reply": "",
                "replied_at": None,
                "created_at": _since(1),
            })
            self._touch_sheets(sheets, professor)
            self._attendance(professor, school_class, {
                camille: 92, ines: 98, yanis: 74,
            }, PARIS_MODULES)
        else:
            university = universities[LYON]
            professor = self._professor(university)
            admin = self._admin_user(university)
            school_class = self._class(university, "Master 1 Mathématiques")
            year = school_class.academic_year or academic_year_for(university)
            students = {
                email: self._student(university, email)
                for email in ("lucas.moreau@univ-lyon.fr", "sofia.benali@univ-lyon.fr")
            }
            lucas = students["lucas.moreau@univ-lyon.fr"]
            sofia = students["sofia.benali@univ-lyon.fr"]

            self._assign(lucas, professor, school_class, year, admin, {
                "average_grade": "11.60", "previous_average": "12.00",
                "attendance_rate": 88, "assignments_submitted": 6, "assignments_total": 8,
                "risk_level": TutorAssignment.RISK_WATCH,
                "risk_reason": "Difficultés sur les probabilités et participation en baisse.",
                "last_contact_at": _since(5, 1),
            })
            self._assign(sofia, professor, school_class, year, admin, {
                "average_grade": "14.80", "previous_average": "14.20",
                "attendance_rate": 96, "assignments_submitted": 8, "assignments_total": 8,
                "risk_level": TutorAssignment.RISK_LOW,
                "risk_reason": "",
                "last_contact_at": _since(2, 6),
            })

            self._goals(students)
            self._study_sessions(lucas, (
                ("Cours — Probabilités", "MAT501", StudySession.KIND_COURSE,
                 0, 10, 0, 90, StudySession.STATUS_COMPLETED, "Amphi 3"),
                ("Révision — Probabilités discrètes", "MAT501", StudySession.KIND_REVISION,
                 2, 16, 0, 60, StudySession.STATUS_SCHEDULED, "Bibliothèque"),
                ("Examen — Probabilités", "MAT501", StudySession.KIND_EXAM,
                 9, 9, 0, 120, StudySession.STATUS_SCHEDULED, "Amphi 3"),
            ))
            self._study_sessions(sofia, (
                ("Révision — Analyse fonctionnelle", "MAT503", StudySession.KIND_REVISION,
                 1, 9, 0, 60, StudySession.STATUS_SCHEDULED, "Salle 12"),
                ("Révision — Algèbre", "MAT502", StudySession.KIND_REVISION,
                 3, 17, 0, 45, StudySession.STATUS_SCHEDULED, "Bibliothèque"),
            ))
            self._journal(lucas, professor, (
                ("Les probabilités se débloquent", "confidence", 7, 1,
                 "La séance de tutorat sur les variables aléatoires m'a beaucoup aidé. Je refais les exercices seuls pour vérifier.",
                 "Bon réflexe. Envoie-moi tes deux démonstrations avant vendredi.", 0),
                ("Semaine chargée", "attention", 5, 14,
                 "Le rythme des partiels est intense et je n'arrive pas à tenir mes révisions. Je dois revoir mon planning.",
                 "", None),
                ("Exposé réussi", "pride", 9, 28,
                 "J'ai présenté mon exposé sans notes. Le retour du groupe était positif et j'ai gagné en assurance.",
                 "", None),
            ))
            self._journal(sofia, professor, (
                ("Un cap clair pour le mémoire", "confidence", 8, 2,
                 "Le sujet de mémoire est validé. J'ai hâte de commencer la bibliographie et de rencontrer ma directrice de recherche.",
                 "Sujet prometteur. Commence par une fiche de lecture par semaine.", -1),
                ("Appréhension à l'oral", "attention", 5, 11,
                 "La soutenance approche et j'ai peur de perdre mes moyens. Je vais répéter avec une camarade.",
                 "", None),
            ))

            slots = self._slots(professor, school_class, "LYON", (
                (1, 11, 0, TutoringSlot.MODE_INDIVIDUAL, "Bureau 108", TutoringSlot.STATUS_OPEN),
                (2, 14, 0, TutoringSlot.MODE_VIDEO, "", TutoringSlot.STATUS_OPEN),
                (3, 9, 0, TutoringSlot.MODE_INDIVIDUAL, "Bureau 108", TutoringSlot.STATUS_OPEN),
                (4, 15, 30, TutoringSlot.MODE_GROUP, "Salle 12", TutoringSlot.STATUS_OPEN),
            ))
            self._sessions(professor, school_class, {
                "camille": lucas, "ines": sofia, "yanis": None,
            }, slots, lyon=True)

            sheet = DifficultySheet.objects.filter(
                student=lucas, category=DifficultySheet.CATEGORY_WORKLOAD,
            ).exclude(status=DifficultySheet.STATUS_CLOSED).first()
            if sheet is None:
                sheet = DifficultySheet.objects.create(
                    university=university, student=lucas, professor=professor,
                    school_class=school_class,
                    category=DifficultySheet.CATEGORY_WORKLOAD,
                    severity=DifficultySheet.SEVERITY_MODERATE,
                    status=DifficultySheet.STATUS_OPEN,
                    observation="Charge de travail importante entre les partiels et la préparation de l'exposé.",
                    action_plan="Planning allégé sur deux semaines et priorisation des révisions.",
                    average_grade="11.60", attendance_rate=88,
                    assignments_submitted=6, assignments_total=8,
                    opened_at=_since(6), last_contact_at=_since(5),
                )
            self._note(sheet, professor, "Planning réaménagé avec l'étudiant. Point prévu la semaine prochaine.", -4)
            sheet2 = DifficultySheet.objects.filter(
                student=sofia, category=DifficultySheet.CATEGORY_ORIENTATION,
            ).exclude(status=DifficultySheet.STATUS_CLOSED).first()
            if sheet2 is None:
                sheet2 = DifficultySheet.objects.create(
                    university=university, student=sofia, professor=professor,
                    school_class=school_class,
                    category=DifficultySheet.CATEGORY_ORIENTATION,
                    severity=DifficultySheet.SEVERITY_REGULAR,
                    status=DifficultySheet.STATUS_IN_PROGRESS,
                    observation="Appréhension de l'oral et besoin de clarifier le projet de recherche.",
                    action_plan="Répétitions de soutenance et rencontre avec la directrice de mémoire.",
                    average_grade="14.80", attendance_rate=96,
                    assignments_submitted=8, assignments_total=8,
                    opened_at=_since(7), last_contact_at=_since(2),
                )
            self._note(sheet2, professor, "Première répétition encourageante, travail sur le regard et le rythme.", -2)

            self._alert(lucas, school_class, "attendance", {
                "title": "Assiduité fragile · Lucas Moreau",
                "detail": "Deux absences en cours magistral et un retard répété en travaux dirigés.",
                "priority": PerseveranceAlert.PRIORITY_NORMAL,
                "status": PerseveranceAlert.STATUS_OPEN,
                "reported_by": professor,
                "detected_at": _since(5),
            })
            self._alert(sofia, school_class, "confidence", {
                "title": "Appréhension de l'oral · Sofia Benali",
                "detail": "Le journal signale une forte appréhension avant la soutenance de mi-parcours.",
                "priority": PerseveranceAlert.PRIORITY_LOW,
                "status": PerseveranceAlert.STATUS_OPEN,
                "detected_at": _since(3),
            })
            self._alert(lucas, school_class, "grade", {
                "title": "Moyenne en recul · Lucas Moreau",
                "detail": "Résultats fragiles sur l'UE de probabilités.",
                "priority": PerseveranceAlert.PRIORITY_NORMAL,
                "status": PerseveranceAlert.STATUS_CLOSED,
                "reported_by": professor,
                "detected_at": _since(9),
                "taken_by": admin,
                "taken_at": _since(7),
                "handling_note": "Point avec le tuteur référent et mobilisation du dispositif de tutorat mathématiques.",
                "closed_at": _since(4),
                "resolution_note": "Séance de tutorat programmée.",
            })
            self._attendance(professor, school_class, {
                lucas: 88, sofia: 96,
            }, LYON_MODULES)

    # -- fabriques ------------------------------------------------------------
    def _attendance(self, professor, school_class, targets, modules):
        """Crée 50 séances et les présences menant aux taux demandés."""
        total_sessions = ATTENDANCE_WEEKS * ATTENDANCE_PER_WEEK
        start = timezone.localdate() - timedelta(days=ATTENDANCE_WEEKS * 7 - 1)
        start -= timedelta(days=start.weekday())
        sessions = []
        for week in range(ATTENDANCE_WEEKS):
            for day in range(ATTENDANCE_PER_WEEK):
                index = week * ATTENDANCE_PER_WEEK + day
                day_date = start + timedelta(days=week * 7 + day)
                hour = (8, 10, 14, 16, 9)[day]
                starts_at = timezone.make_aware(datetime.combine(day_date, time(hour, 0)))
                title = modules[index % len(modules)]
                kind = AttendanceSession.KIND_CHOICES[index % len(AttendanceSession.KIND_CHOICES)][0]
                session, _created = AttendanceSession.objects.get_or_create(
                    professor=professor,
                    school_class=school_class,
                    starts_at=starts_at,
                    title=title,
                    defaults={
                        "university": school_class.university,
                        "kind": kind,
                        "duration_minutes": 90,
                        "status": AttendanceSession.STATUS_COMPLETED,
                        "created_by": professor.membership.user,
                    },
                )
                sessions.append(session)
        existing = {
            (record.session_id, record.student_id): record
            for record in AttendanceRecord.objects.filter(
                session__in=sessions, student__in=list(targets),
            )
        }
        to_create = []
        to_update = []
        for student, target in targets.items():
            attended_target = round(int(target) * total_sessions / 100)
            absent_count = max(total_sessions - attended_target, 0)
            absent_indices = {
                round(position * total_sessions / absent_count)
                for position in range(absent_count)
            } if absent_count else set()
            for index, session in enumerate(sessions):
                status = (
                    AttendanceRecord.STATUS_ABSENT
                    if index in absent_indices
                    else AttendanceRecord.STATUS_PRESENT
                )
                record = existing.get((session.pk, student.pk))
                if record is None:
                    to_create.append(AttendanceRecord(
                        university=student.university,
                        session=session,
                        student=student,
                        status=status,
                        recorded_by=professor.membership.user,
                    ))
                elif record.status != status:
                    record.status = status
                    to_update.append(record)
        if to_create:
            AttendanceRecord.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            AttendanceRecord.objects.bulk_update(to_update, ["status"])
        for student in targets:
            sync_student_attendance(student)

    def _assign(self, student, professor, school_class, year, admin, values):
        assignment = TutorAssignment.objects.filter(
            student=student, academic_year=year, status=TutorAssignment.STATUS_ACTIVE,
        ).first()
        if assignment is None:
            assignment = TutorAssignment(
                university=student.university, student=student, academic_year=year,
                status=TutorAssignment.STATUS_ACTIVE,
            )
        assignment.professor = professor
        assignment.school_class = school_class
        assignment.assigned_by = admin
        for field, value in values.items():
            setattr(assignment, field, value)
        assignment.save()

    def _goals(self, students):
        for email, student in students.items():
            for title, code, status, progress, skills, total, offset, grade in GOALS.get(email, ()):
                StudentGoal.objects.update_or_create(
                    student=student,
                    semester="Semestre 1",
                    title=title,
                    defaults={
                        "university": student.university,
                        "course_code": code,
                        "description": "Objectif de démonstration suivi avec le référent pédagogique.",
                        "status": status,
                        "progress": progress,
                        "skills_acquired": skills,
                        "skills_total": total,
                        "target_date": timezone.localdate() + timedelta(days=offset),
                        "grade": grade,
                    },
                )

    def _study_sessions(self, student, specs):
        for title, code, kind, offset, hour, minute, duration, status, place in specs:
            StudySession.objects.update_or_create(
                student=student, title=title, kind=kind,
                defaults={
                    "university": student.university,
                    "course_code": code,
                    "starts_at": _aware(offset, hour, minute),
                    "duration_minutes": duration,
                    "status": status,
                    "location": place,
                    "notes": "Session de démonstration du suivi référent.",
                },
            )

    def _camille_tasks(self, student):
        for title, context, horizon, priority, offset, done in TASKS:
            StudentTask.objects.update_or_create(
                student=student,
                title=title,
                defaults={
                    "university": student.university,
                    "context_label": context,
                    "horizon": horizon,
                    "priority": priority,
                    "due_at": timezone.localdate() + timedelta(days=offset),
                    "is_done": done,
                },
            )

    def _journal(self, student, professor, entries=JOURNAL):
        JournalEntry.objects.filter(
            student=student, title__in=[entry[0] for entry in entries],
        ).delete()
        for title, sentiment, confidence, offset, reflection, feedback, feedback_offset in entries:
            entry_date = timezone.localdate() - timedelta(days=offset)
            created_at = timezone.make_aware(datetime.combine(entry_date, time(20, 30)))
            entry = JournalEntry.objects.create(
                university=student.university,
                student=student,
                title=title,
                reflection=reflection,
                sentiment=sentiment,
                confidence=confidence,
                entry_date=entry_date,
                feedback=feedback,
                feedback_by=professor if feedback else None,
                feedback_at=(
                    _aware(feedback_offset, 18, 0) if feedback and feedback_offset is not None else None
                ),
            )
            JournalEntry.objects.filter(pk=entry.pk).update(created_at=created_at)

    def _slots(self, professor, school_class, tag, specs):
        TutoringSlot.objects.filter(
            professor=professor, reference__startswith=SEED_SLOT_PREFIX,
        ).delete()
        slots = {}
        for index, (offset, hour, minute, mode, location, status) in enumerate(specs, start=1):
            reference = "%s%s-%02d" % (SEED_SLOT_PREFIX, tag, index)
            starts_at = _aware(offset, hour, minute)
            slot = TutoringSlot.objects.create(
                university=professor.university,
                professor=professor,
                school_class=school_class,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                mode=mode,
                location=location,
                meeting_url=(
                    "https://visio.eduspark.example/seed-%s-%02d"
                    % (professor.pk, index) if mode == TutoringSlot.MODE_VIDEO else ""
                ),
                status=status,
                reference=reference,
                created_by=professor.membership.user,
            )
            slots[reference] = slot
        return slots

    def _session(self, student, professor, school_class, topic, **values):
        session = TutoringSession.objects.filter(
            student=student, professor=professor, topic=topic,
        ).first()
        if session is None:
            session = TutoringSession(
                university=student.university, student=student,
                professor=professor, topic=topic,
            )
        session.school_class = school_class
        for field, value in values.items():
            setattr(session, field, value)
        session.save()
        return session

    def _sessions(self, professor, school_class, students, slots, lyon=False):
        teacher = professor.membership.user
        if not lyon:
            self._session(
                students["ines"], professor, school_class,
                "Méthodologie de révision pour les partiels",
                preferred_at=_aware(3, 10),
                duration_minutes=30,
                mode=TutoringSlot.MODE_VIDEO,
                priority=TutoringSession.PRIORITY_HIGH,
                status=TutoringSession.STATUS_PENDING,
                created_by=students["ines"].membership.user,
            )
            self._session(
                students["yanis"], professor, school_class,
                "Reprendre le projet web et l'assiduité",
                preferred_at=_aware(4, 14, 30),
                duration_minutes=30,
                mode=TutoringSlot.MODE_INDIVIDUAL,
                priority=TutoringSession.PRIORITY_HIGH,
                status=TutoringSession.STATUS_PENDING,
                created_by=students["yanis"].membership.user,
            )
            accepted_slot = slots.get(SEED_SLOT_PREFIX + "PARIS-03")
            self._session(
                students["camille"], professor, school_class,
                "Entretien de suivi personnalisé",
                slot=accepted_slot,
                preferred_at=_aware(2, 10),
                scheduled_at=_aware(2, 10),
                duration_minutes=30,
                mode=TutoringSlot.MODE_INDIVIDUAL,
                location="Bureau 214",
                priority=TutoringSession.PRIORITY_NORMAL,
                status=TutoringSession.STATUS_ACCEPTED,
                decision_note="Créneau confirmé, merci de préparer vos questions sur le projet.",
                decided_by=teacher,
                decided_at=_since(1),
                created_by=students["camille"].membership.user,
            )
            self._session(
                students["camille"], professor, school_class,
                "Bilan de mi-semestre",
                scheduled_at=_aware(-12, 14),
                duration_minutes=30,
                mode=TutoringSlot.MODE_INDIVIDUAL,
                location="Bureau 214",
                priority=TutoringSession.PRIORITY_NORMAL,
                status=TutoringSession.STATUS_COMPLETED,
                summary_points="Résultats stables, bonne autonomie sur les travaux pratiques. Fatigue liée à la charge du projet.",
                summary_actions="Échelonner les rendus et conserver les créneaux de révision du mercredi.",
                completed_at=_aware(-12, 14) + timedelta(minutes=45),
                decided_by=teacher,
                decided_at=_aware(-13, 9),
                created_by=students["camille"].membership.user,
            )
            self._session(
                students["yanis"], professor, school_class,
                "Point sur l'assiduité et les rendus",
                scheduled_at=_aware(-8, 15),
                duration_minutes=30,
                mode=TutoringSlot.MODE_INDIVIDUAL,
                location="Bureau 214",
                priority=TutoringSession.PRIORITY_HIGH,
                status=TutoringSession.STATUS_COMPLETED,
                summary_points="Absences liées à des contraintes personnelles. Deux devoirs restent à rendre.",
                summary_actions="Point hebdomadaire et dépôt des devoirs avant vendredi.",
                completed_at=_aware(-8, 15) + timedelta(minutes=30),
                decided_by=teacher,
                decided_at=_aware(-9, 10),
                created_by=students["yanis"].membership.user,
            )
        else:
            self._session(
                students["camille"], professor, school_class,
                "Aide sur les probabilités conditionnelles",
                preferred_at=_aware(2, 14),
                duration_minutes=30,
                mode=TutoringSlot.MODE_VIDEO,
                priority=TutoringSession.PRIORITY_NORMAL,
                status=TutoringSession.STATUS_PENDING,
                created_by=students["camille"].membership.user,
            )
            self._session(
                students["ines"], professor, school_class,
                "Préparer l'exposé de mathématiques",
                preferred_at=_aware(5, 10),
                scheduled_at=_aware(5, 10),
                duration_minutes=30,
                mode=TutoringSlot.MODE_VIDEO,
                priority=TutoringSession.PRIORITY_NORMAL,
                status=TutoringSession.STATUS_ACCEPTED,
                decision_note="Créneau confirmé en visioconférence.",
                decided_by=teacher,
                decided_at=_since(1),
                created_by=students["ines"].membership.user,
            )
            self._session(
                students["camille"], professor, school_class,
                "Premier point de suivi",
                scheduled_at=_aware(-15, 11),
                duration_minutes=30,
                mode=TutoringSlot.MODE_INDIVIDUAL,
                location="Bureau 108",
                priority=TutoringSession.PRIORITY_NORMAL,
                status=TutoringSession.STATUS_COMPLETED,
                summary_points="Bilan des résultats, difficultés ciblées sur les probabilités.",
                summary_actions="Exercices supplémentaires et rendez-vous hebdomadaire.",
                completed_at=_aware(-15, 11) + timedelta(minutes=30),
                decided_by=teacher,
                decided_at=_aware(-16, 9),
                created_by=students["camille"].membership.user,
            )
            self._session(
                students["ines"], professor, school_class,
                "Préparer la soutenance blanche",
                scheduled_at=_aware(-10, 16),
                duration_minutes=45,
                mode=TutoringSlot.MODE_INDIVIDUAL,
                location="Bureau 108",
                priority=TutoringSession.PRIORITY_NORMAL,
                status=TutoringSession.STATUS_COMPLETED,
                summary_points="Soutenance blanche réussie, appréhension de l'oral encore présente.",
                summary_actions="Répétition enregistrée et travail sur le rythme.",
                completed_at=_aware(-10, 16) + timedelta(minutes=45),
                decided_by=teacher,
                decided_at=_aware(-11, 9),
                created_by=students["ines"].membership.user,
            )

    def _sheets(self, university, professor, students, specs):
        created = []
        for spec in specs:
            student = students[spec["student"]]
            group = student.groups.select_related("school_class").first()
            sheet = DifficultySheet.objects.filter(
                student=student, category=spec["category"],
            ).exclude(status=DifficultySheet.STATUS_CLOSED).first()
            values = {
                "university": university,
                "professor": professor,
                "school_class": group.school_class if group else None,
                "severity": spec["severity"],
                "status": spec["status"],
                "observation": spec["observation"],
                "action_plan": spec["action_plan"],
                "average_grade": spec["average"],
                "attendance_rate": spec["attendance"],
                "assignments_submitted": spec["submitted"],
                "assignments_total": spec["total"],
                "opened_at": _since(-spec["opened"]),
                "last_contact_at": _since(-spec["contact"]) if spec["contact"] is not None else None,
            }
            if sheet is None:
                sheet = DifficultySheet.objects.create(
                    student=student, category=spec["category"], **values,
                )
            else:
                for field, value in values.items():
                    setattr(sheet, field, value)
                sheet.save()
            for note_text, offset in spec["notes"]:
                self._note(sheet, professor, note_text, offset)
            created.append(sheet)
        return created

    def _note(self, sheet, professor, text, offset):
        note, _created = DifficultyNote.objects.get_or_create(
            sheet=sheet, author=professor.membership.user, note=text,
        )
        if offset is not None:
            DifficultyNote.objects.filter(pk=note.pk).update(
                created_at=timezone.make_aware(datetime.combine(
                    timezone.localdate() + timedelta(days=offset), time(17, 30),
                ))
            )

    def _alert(self, student, school_class, alert_type, values):
        alert = PerseveranceAlert.objects.filter(
            student=student, alert_type=alert_type,
        ).order_by("pk").first()
        if alert is None:
            alert = PerseveranceAlert(
                university=student.university, student=student,
                school_class=school_class, alert_type=alert_type,
            )
        if values.get("status") == PerseveranceAlert.STATUS_OPEN:
            alert.taken_by = None
            alert.taken_at = None
            alert.handling_note = ""
            alert.closed_at = None
            alert.resolution_note = ""
        elif values.get("status") == PerseveranceAlert.STATUS_TAKEN:
            alert.closed_at = None
            alert.resolution_note = ""
        for field, value in values.items():
            setattr(alert, field, value)
        alert.save()
        return alert

    def _relance(self, student, professor, values):
        notification = TutorNotification.objects.filter(
            student=student, kind=TutorNotification.KIND_RELANCE,
        ).order_by("pk").first()
        if notification is None:
            notification = TutorNotification(
                university=student.university, student=student,
                professor=professor, kind=TutorNotification.KIND_RELANCE,
            )
        created_at = values.pop("created_at", None)
        for field, value in values.items():
            setattr(notification, field, value)
        notification.save()
        if created_at is not None:
            type(notification).objects.filter(pk=notification.pk).update(created_at=created_at)
            notification.refresh_from_db()
        return notification

    def _touch_sheets(self, sheets, professor):
        for sheet in sheets:
            if not sheet.notes.exists():
                self._note(sheet, professor, "Suivi initial ouvert avec l'étudiant.", -1)
