from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from accounts.models import Profil


class Command(BaseCommand):
    help = "Réinitialise les comptes de démonstration des trois portails."

    ACCOUNTS = (
        ("admin@eduspark.local", "Admin12345!", Profil.ROLE_ADMIN, True, True, "Marcelle", "Dupont"),
        ("prof.test@eduspark.local", "Prof12345!", Profil.ROLE_PROF, False, False, "Hélène", "Vasseur"),
        ("test.ui@example.com", "Etudiant12345!", Profil.ROLE_ETUDIANT, False, False, "Camille", "Martin"),
    )

    def handle(self, *args, **options):
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

            state = "créé" if created else "mis à jour"
            self.stdout.write(self.style.SUCCESS(
                "%s (%s) %s — mot de passe : %s" % (email, role, state, password)))
