"""Vérification de la possession d'une adresse e-mail.

Une appartenance n'est jamais activée sur la seule foi d'un domaine e-mail
déclaré à l'inscription : l'utilisateur doit d'abord ouvrir le lien signé
envoyé à cette adresse (ou un lien d'invitation / de réinitialisation, qui
le prouvent tout autant).
"""

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

SALT = "users.email-verification"
MAX_AGE = 3 * 24 * 3600  # 3 jours


def make_token(user):
    # L'e-mail fait partie du jeton : changer d'adresse invalide les anciens liens.
    return signing.dumps({"u": user.pk, "e": user.email}, salt=SALT)


def read_token(token):
    """Retourne l'utilisateur du jeton, ou None (invalide, expiré, e-mail changé)."""
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:  # SignatureExpired en hérite
        return None
    user = get_user_model().objects.filter(pk=data.get("u")).first()
    if user is None or user.email != data.get("e"):
        return None
    return user


def send_verification_email(request, user):
    link = request.build_absolute_uri(reverse("users:verify_email", kwargs={"token": make_token(user)}))
    body = render_to_string("users/emails/verify_email.txt", {"user": user, "link": link})
    send_mail("Confirmez votre adresse e-mail EduSpark", body, None, [user.email], fail_silently=True)


def mark_email_verified(user):
    """Marque l'adresse comme vérifiée et active les appartenances qui
    n'attendaient que cette preuve. Retourne la liste des appartenances activées."""
    from .models import Membership

    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    domain = user.email.rsplit("@", 1)[-1]
    activated = []
    waiting = Membership.objects.filter(user=user, awaiting_email_verification=True).select_related("university")
    for membership in waiting:
        membership.awaiting_email_verification = False
        # Le domaine est revérifié au moment de l'activation.
        if membership.university.email_domain and membership.university.email_domain == domain:
            membership.is_active = True
            activated.append(membership)
        membership.save(update_fields=["is_active", "awaiting_email_verification"])
        membership.ensure_profile()
    return activated
