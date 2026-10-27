"""Envoi des e-mails transactionnels du module de suivi."""

import html
import re

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def send_templated_email(subject, recipients, template_name, context, reply_to=None):
    """Envoie un e-mail HTML (avec repli texte) sans jamais bloquer l'action."""
    emails = list(dict.fromkeys(email for email in recipients if email))
    if not emails:
        return 0
    html_body = render_to_string(template_name, context)
    text_body = html.unescape(strip_tags(html_body))
    text_body = re.sub(r"[ \t]+\n", "\n", text_body)
    text_body = re.sub(r"\n\s*\n+", "\n\n", text_body).strip()
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=emails,
        reply_to=reply_to or None,
    )
    message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=True)
