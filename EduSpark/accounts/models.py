from django.contrib.auth.models import Group, User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profil(models.Model):
    """Profil étendu de l'utilisateur avec son rôle fonctionnel.

    Rôles : admin (gestion via back-office), prof (enseignant),
    etudiant (apprenant). Le rôle est synchronisé avec les groupes
    Django de même nom pour le contrôle d'accès.
    """

    ROLE_ADMIN = "admin"
    ROLE_PROF = "prof"
    ROLE_ETUDIANT = "etudiant"

    ROLE_CHOICES = (
        (ROLE_ETUDIANT, "Étudiant"),
        (ROLE_PROF, "Prof"),
        (ROLE_ADMIN, "Admin"),
    )

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profil",
        verbose_name="Utilisateur",
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default=ROLE_ETUDIANT,
        verbose_name="Rôle",
    )

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profils"

    def __str__(self):
        return "%s (%s)" % (self.user.email or self.user.username, self.role)

    def sync_group(self):
        """Aligne les groupes Django sur le rôle (un seul groupe de rôle)."""
        for name, _label in self.ROLE_CHOICES:
            group, _created = Group.objects.get_or_create(name=name)
            if name == self.role:
                self.user.groups.add(group)
            else:
                self.user.groups.remove(group)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            self.sync_group()
        except Exception:
            # Base pas encore migrée (ex. première migration) : on ignore.
            pass


@receiver(post_save, sender=User)
def setup_user_profil(sender, instance, created, **kwargs):
    """Crée le profil et force le rôle admin pour le staff / superuser.

    On mute l'objet profil déjà mis en cache sur l'instance en mémoire
    (get_or_create y dépose l'objet créé) pour ne jamais laisser un
    profil périmé derrière soi.
    """
    profil, _created = Profil.objects.get_or_create(user=instance)
    cached = instance._state.fields_cache.get("profil")
    target = cached if cached is not None and cached.pk == profil.pk else profil
    if instance.is_superuser or instance.is_staff:
        if target.role != Profil.ROLE_ADMIN:
            target.role = Profil.ROLE_ADMIN
            target.save()
