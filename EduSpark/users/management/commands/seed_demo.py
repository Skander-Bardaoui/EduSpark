"""Données de démonstration : python manage.py seed_demo

Crée 2 universités avec admin, professeurs, étudiants, classes et groupes.
Mot de passe de tous les comptes : Demo-2026! (à ne jamais utiliser en production).
Idempotent : relancer la commande ne duplique rien.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from users.models import Membership, SchoolClass, StudentGroup, University
from users.tenancy import Role

PASSWORD = "Demo-2026!"
User = get_user_model()


class Command(BaseCommand):
    help = "Crée des données de démonstration multi-universités."

    def user(self, email, first, last, superuser=False):
        user, created = User.objects.get_or_create(
            email=email, defaults={"username": email, "first_name": first, "last_name": last},
        )
        if created:
            user.set_password(PASSWORD)
            user.is_superuser = user.is_staff = superuser
            user.save()
        return user

    def member(self, user, university, role, **profile_fields):
        membership, _ = Membership.objects.get_or_create(user=user, university=university, defaults={"role": role})
        profile = membership.ensure_profile()
        if profile is not None and profile_fields:
            for name, value in profile_fields.items():
                setattr(profile, name, value)
            profile.save()
        return profile

    @transaction.atomic
    def handle(self, *args, **options):
        self.user("admin@eduspark.local", "Admin", "Plateforme", superuser=True)
        esprit, _ = University.objects.get_or_create(
            name="ESPRIT", defaults={"code": "ESP", "city": "Tunis", "country": "Tunisie", "email_domain": "esprit.tn"},
        )
        insat, _ = University.objects.get_or_create(
            name="INSAT", defaults={"code": "INSAT", "city": "Tunis", "country": "Tunisie", "email_domain": "insat.rnu.tn"},
        )
        for uni, domain in ((esprit, "esprit.tn"), (insat, "insat.rnu.tn")):
            self.member(self.user(f"admin@{domain}", "Admin", uni.code), uni, Role.UNIVERSITY_ADMIN)

        # Une professeure qui enseigne dans les deux universités.
        sana = self.user("sana.trabelsi@eduspark.local", "Sana", "Trabelsi")
        p1 = self.member(sana, esprit, Role.PROFESSOR, department="Informatique", speciality="Intelligence artificielle", grade="maitre_conferences")
        self.member(sana, insat, Role.PROFESSOR, department="Génie logiciel", speciality="Apprentissage automatique", grade="vacataire")
        p2 = self.member(self.user("karim.ben@esprit.tn", "Karim", "Ben Salah"), esprit, Role.PROFESSOR,
                         department="Mathématiques", speciality="Statistiques", grade="assistant")

        students = []
        for i, (first, last, program) in enumerate([
            ("Amira", "Haddad", "Génie logiciel"), ("Youssef", "Mansour", "Génie logiciel"),
            ("Ines", "Gharbi", "Data science"), ("Omar", "Jaziri", "Data science"),
        ], start=1):
            students.append(self.member(
                self.user(f"{first.lower()}.{last.lower()}@esprit.tn", first, last), esprit, Role.STUDENT,
                student_number=f"ESP26{i:04d}", program=program, promotion="2026",
            ))
        self.member(self.user("lina.k@insat.rnu.tn", "Lina", "Kefi"), insat, Role.STUDENT, program="Réseaux", promotion="2027")

        gl, _ = SchoolClass.objects.get_or_create(
            university=esprit, name="4GL", academic_year="2025-2026",
            defaults={"level": "4e année", "program": "Génie logiciel"},
        )
        ds, _ = SchoolClass.objects.get_or_create(
            university=esprit, name="4DS", academic_year="2025-2026",
            defaults={"level": "4e année", "program": "Data science"},
        )
        gl.professors.add(p1)
        ds.professors.add(p1, p2)
        g1, _ = StudentGroup.objects.get_or_create(school_class=gl, name="G1", defaults={"capacity": 30})
        g2, _ = StudentGroup.objects.get_or_create(school_class=ds, name="G1", defaults={"capacity": 30})
        g1.students.add(*students[:2])
        g2.students.add(*students[2:])

        self.stdout.write(self.style.SUCCESS(
            f"Données de démonstration prêtes. Mot de passe de tous les comptes : {PASSWORD}\n"
            "  admin@eduspark.local (admin plateforme), admin@esprit.tn (admin université),\n"
            "  sana.trabelsi@eduspark.local (prof dans 2 universités), amira.haddad@esprit.tn (étudiante)"
        ))
