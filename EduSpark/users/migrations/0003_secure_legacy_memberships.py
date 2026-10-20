"""Rattrapage des bases créées avant la vérification de l'e-mail.

L'ancienne règle activait immédiatement un étudiant inscrit avec le domaine
officiel de l'université, sans preuve de possession de l'adresse. La 0002 a
ajouté les champs mais laissé ces appartenances actives avec
email_verified=False. Cette migration :

1. marque vérifiés les comptes ayant accepté une invitation envoyée à leur
   adresse (le lien reçu par e-mail en prouvait déjà la possession) ;
2. repasse en « activation à la vérification de l'e-mail » toute appartenance
   étudiante encore active dont l'adresse, non vérifiée, correspond au domaine
   officiel de l'université.

On ne peut pas distinguer, a posteriori, un étudiant activé par l'ancienne
règle d'un étudiant ajouté par l'admin avec la même adresse : par sécurité,
les deux doivent prouver leur adresse (lien de vérification renvoyable depuis
le tableau de bord, ou « mot de passe oublié »), ce qui réactive l'accès.
"""

from django.db import migrations
from django.db.models import F


def secure_legacy_memberships(apps, schema_editor):
    User = apps.get_model("users", "User")
    Membership = apps.get_model("users", "Membership")

    User.objects.filter(
        email_verified=False,
        accepted_invitations__status="accepted",
        accepted_invitations__email__iexact=F("email"),
    ).update(email_verified=True)

    legacy = (
        Membership.objects.filter(role="etudiant", is_active=True, user__email_verified=False)
        .exclude(university__email_domain="")
        .exclude(user__is_superuser=True)
        .select_related("user", "university")
    )
    to_secure = [
        m.pk for m in legacy
        if m.user.email.rsplit("@", 1)[-1].lower() == m.university.email_domain.strip().lower().lstrip("@")
    ]
    Membership.objects.filter(pk__in=to_secure).update(is_active=False, awaiting_email_verification=True)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_email_verification"),
    ]

    operations = [
        # Irréversible au sens strict (on ne sait plus qui était actif) : le
        # retour arrière laisse les données telles quelles.
        migrations.RunPython(secure_legacy_memberships, migrations.RunPython.noop),
    ]
