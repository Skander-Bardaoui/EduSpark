from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import (
    Membership,
    ProfessorProfile,
    SchoolClass,
    StudentGroup,
    StudentProfile,
    University,
)
from accounts.tenancy import Role

UNIVERSITIES = (
    {
        "name": "Université Paris Cité",
        "defaults": {
            "slug": "universite-paris-cite",
            "code": "UPC",
            "city": "Paris",
            "country": "France",
            "email_domain": "u-paris.fr",
            "website": "https://u-paris.fr",
            "description": "Université de démonstration — sciences, santé et humanités.",
            "is_active": True,
        },
    },
    {
        "name": "Université de Lyon",
        "defaults": {
            "slug": "universite-de-lyon",
            "code": "UDL",
            "city": "Lyon",
            "country": "France",
            "email_domain": "univ-lyon.fr",
            "website": "https://www.universite-lyon.fr",
            "description": "Université de démonstration — mathématiques et informatique.",
            "is_active": True,
        },
    },
)

ACCOUNTS = (
    ("admin.paris@u-paris.fr", "Admin12345!", "Sophie", "Bernard"),
    ("admin.lyon@univ-lyon.fr", "Admin12345!", "Julien", "Morel"),
    ("prof.test@eduspark.local", "Prof12345!", "Hélène", "Vasseur"),
    ("test.ui@example.com", "Etudiant12345!", "Camille", "Martin"),
    ("ines.bernard@u-paris.fr", "Etudiant12345!", "Inès", "Bernard"),
    ("yanis.leroy@u-paris.fr", "Etudiant12345!", "Yanis", "Leroy"),
    ("lucas.moreau@univ-lyon.fr", "Etudiant12345!", "Lucas", "Moreau"),
    ("sofia.benali@univ-lyon.fr", "Etudiant12345!", "Sofia", "Benali"),
)

STUDENTS = (
    {
        "email": "test.ui@example.com",
        "university": "Université Paris Cité",
        "student_number": "UPC-2026-001",
        "program": "Informatique",
        "promotion": "2026",
    },
    {
        "email": "ines.bernard@u-paris.fr",
        "university": "Université Paris Cité",
        "student_number": "UPC-2026-002",
        "program": "Informatique",
        "promotion": "2026",
    },
    {
        "email": "yanis.leroy@u-paris.fr",
        "university": "Université Paris Cité",
        "student_number": "UPC-2026-003",
        "program": "Génie logiciel",
        "promotion": "2026",
    },
    {
        "email": "lucas.moreau@univ-lyon.fr",
        "university": "Université de Lyon",
        "student_number": "UDL-2026-001",
        "program": "Mathématiques",
        "promotion": "2026",
    },
    {
        "email": "sofia.benali@univ-lyon.fr",
        "university": "Université de Lyon",
        "student_number": "UDL-2026-002",
        "program": "Mathématiques",
        "promotion": "2026",
    },
)

PROFESSOR_PROFILES = (
    {
        "email": "prof.test@eduspark.local",
        "university": "Université Paris Cité",
        "department": "Informatique",
        "speciality": "Systèmes distribués",
        "grade": "maitre_conferences",
    },
    {
        "email": "prof.test@eduspark.local",
        "university": "Université de Lyon",
        "department": "Mathématiques",
        "speciality": "Probabilités",
        "grade": "professeur",
    },
)

CLASSES = (
    {
        "university": "Université Paris Cité",
        "name": "Licence 3 Informatique",
        "level": "3e année",
        "program": "Informatique",
        "academic_year": "2025-2026",
        "description": "Cursus de licence informatique — promotion 2026.",
        "professor_email": "prof.test@eduspark.local",
        "groups": (
            {"name": "TD A", "capacity": 24, "students": ("test.ui@example.com", "ines.bernard@u-paris.fr")},
            {"name": "TP B", "capacity": 16, "students": ("yanis.leroy@u-paris.fr",)},
        ),
    },
    {
        "university": "Université Paris Cité",
        "name": "Master 1 Génie Logiciel",
        "level": "Master 1",
        "program": "Génie logiciel",
        "academic_year": "2025-2026",
        "description": "Parcours génie logiciel et architecture applicative.",
        "professor_email": "prof.test@eduspark.local",
        "groups": (),
    },
    {
        "university": "Université de Lyon",
        "name": "Master 1 Mathématiques",
        "level": "Master 1",
        "program": "Mathématiques",
        "academic_year": "2025-2026",
        "description": "Master de mathématiques fondamentales et appliquées.",
        "professor_email": "prof.test@eduspark.local",
        "groups": (
            {"name": "Groupe 1", "capacity": 20, "students": ("lucas.moreau@univ-lyon.fr", "sofia.benali@univ-lyon.fr")},
        ),
    },
)


class Command(BaseCommand):
    help = "Crée un jeu de données de démonstration multi-universités (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Exécuter même quand DEBUG=False.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "seed_demo est réservé au développement (DEBUG=False). "
                "Relancez avec --force pour l'exécuter malgré tout."
            )

        with transaction.atomic():
            universities = self.create_universities()
            users = self.create_accounts()
            self.create_memberships(universities, users)
            self.create_professor_profiles(universities, users)
            self.create_students(universities, users)
            self.create_classes(universities, users)

        memberships = Membership.objects.count()
        self.stdout.write(self.style.SUCCESS(
            "Seed terminé : %s universités, %s comptes, %s appartenances."
            % (len(universities), len(users), memberships)
        ))
        self.stdout.write(
            "Admin Paris : admin.paris@u-paris.fr / Admin12345!\n"
            "Admin Lyon : admin.lyon@univ-lyon.fr / Admin12345!\n"
            "Professeur (2 universités) : prof.test@eduspark.local / Prof12345!\n"
            "Étudiant : test.ui@example.com / Etudiant12345!"
        )

    def create_universities(self):
        universities = {}
        for entry in UNIVERSITIES:
            university, _created = University.objects.update_or_create(
                name=entry["name"], defaults=entry["defaults"],
            )
            universities[university.name] = university
        return universities

    def create_accounts(self):
        users = {}
        for email, password, first_name, last_name in ACCOUNTS:
            user = (
                User.objects.filter(username__iexact=email).first()
                or User.objects.filter(email__iexact=email).first()
            )
            if user is None:
                user = User(username=email)
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = True
            user.set_password(password)
            user.save()
            users[email] = user
        return users

    def create_memberships(self, universities, users):
        memberships = {}
        pairs = (
            ("admin.paris@u-paris.fr", "Université Paris Cité", Role.UNIVERSITY_ADMIN),
            ("admin.lyon@univ-lyon.fr", "Université de Lyon", Role.UNIVERSITY_ADMIN),
            ("prof.test@eduspark.local", "Université Paris Cité", Role.PROFESSOR),
            ("prof.test@eduspark.local", "Université de Lyon", Role.PROFESSOR),
        )
        pairs += tuple(
            (entry["email"], entry["university"], Role.STUDENT) for entry in STUDENTS
        )
        for email, university_name, role in pairs:
            membership, _created = Membership.objects.update_or_create(
                user=users[email], university=universities[university_name],
                defaults={"role": role, "is_active": True},
            )
            membership.ensure_profile()
            memberships[(email, university_name)] = membership
        return memberships

    def create_professor_profiles(self, universities, users):
        for entry in PROFESSOR_PROFILES:
            membership = Membership.objects.get(
                user=users[entry["email"]], university=universities[entry["university"]],
            )
            ProfessorProfile.objects.update_or_create(
                membership=membership,
                defaults={
                    "department": entry["department"],
                    "speciality": entry["speciality"],
                    "grade": entry["grade"],
                },
            )

    def create_students(self, universities, users):
        for entry in STUDENTS:
            membership = Membership.objects.get(
                user=users[entry["email"]], university=universities[entry["university"]],
            )
            StudentProfile.objects.update_or_create(
                membership=membership,
                defaults={
                    "student_number": entry["student_number"],
                    "program": entry["program"],
                    "promotion": entry["promotion"],
                },
            )

    def create_classes(self, universities, users):
        for entry in CLASSES:
            university = universities[entry["university"]]
            school_class, _created = SchoolClass.objects.update_or_create(
                university=university,
                name=entry["name"],
                academic_year=entry["academic_year"],
                defaults={
                    "level": entry["level"],
                    "program": entry["program"],
                    "description": entry["description"],
                },
            )
            professor_membership = Membership.objects.get(
                user=users[entry["professor_email"]], university=university,
            )
            school_class.professors.set([professor_membership.professor_profile])

            for group_entry in entry["groups"]:
                group, _created = StudentGroup.objects.update_or_create(
                    school_class=school_class,
                    name=group_entry["name"],
                    defaults={"capacity": group_entry["capacity"]},
                )
                profiles = StudentProfile.objects.filter(
                    membership__university=university,
                    membership__user__in=[users[email] for email in group_entry["students"]],
                )
                group.students.set(profiles)
