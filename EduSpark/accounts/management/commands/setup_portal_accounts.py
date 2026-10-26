from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from accounts.models import Membership, Profil, University
from accounts.tenancy import Role

DEMO_UNIVERSITY = {
    "name": "Université Paris Cité",
    "code": "UPC",
    "city": "Paris",
    "country": "France",
    "email_domain": "u-paris.fr",
}


class Command(BaseCommand):
    help = "Réinitialise les comptes de démonstration des trois portails."

    ACCOUNTS = (
        ("admin@eduspark.local", "Admin12345!", Profil.ROLE_ADMIN, True, True, "Marcelle", "Dupont"),
        ("prof.test@eduspark.local", "Prof12345!", Profil.ROLE_PROF, False, False, "Hélène", "Vasseur"),
        ("test.ui@example.com", "Etudiant12345!", Profil.ROLE_ETUDIANT, False, False, "Camille", "Martin"),
    )

    MEMBERSHIP_ROLES = {
        "prof.test@eduspark.local": Role.PROFESSOR,
        "test.ui@example.com": Role.STUDENT,
    }

    def handle(self, *args, **options):
        university, _created = University.objects.get_or_create(
            name=DEMO_UNIVERSITY["name"], defaults=DEMO_UNIVERSITY,
        )

        for email, password, role, is_staff, is_superuser, first_name, last_name in self.ACCOUNTS:
            user = (
                User.objects.filter(username__iexact=email).first()
                or User.objects.filter(email__iexact=email).first()
            )
            created = user is None
            if created:
                user = User(username=email)
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.is_active = True
            user.set_password(password)
            user.save()

            profil, _ = Profil.objects.get_or_create(user=user)
            if profil.role != role:
                profil.role = role
                profil.save()
            else:
                profil.sync_group()

            membership_role = self.MEMBERSHIP_ROLES.get(email)
            if membership_role:
                membership, membership_created = Membership.objects.get_or_create(
                    user=user, university=university,
                    defaults={"role": membership_role, "is_active": True},
                )
                if not membership_created:
                    membership.role = membership_role
                    membership.is_active = True
                    membership.save(update_fields=["role", "is_active"])
                membership.ensure_profile()

            state = "créé" if created else "mis à jour"
            self.stdout.write(self.style.SUCCESS(
                "%s (%s) %s — mot de passe : %s" % (email, role, state, password)))

        self.stdout.write(self.style.SUCCESS(
            "Comptes rattachés à %s." % university.name))
