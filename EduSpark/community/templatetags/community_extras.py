"""Petits filtres d'affichage partagés par les pages de la classe virtuelle."""

from django import template
from django.utils.timesince import timesince

register = template.Library()

_TONES = (
    "bg-primary-fixed text-on-primary-fixed",
    "bg-secondary-fixed text-on-secondary-fixed",
    "bg-tertiary-fixed text-on-tertiary-fixed",
    "bg-secondary-container text-on-secondary-container",
)


@register.filter
def display_name(user):
    if user is None:
        return "Compte supprimé"
    return user.get_full_name().strip() or user.email


@register.filter
def initials(user):
    parts = display_name(user).replace("-", " ").replace("@", " ").split()
    return "".join(part[0] for part in parts[:2]).upper() or "?"


@register.filter
def tone(user):
    """Couleur d'avatar stable pour un utilisateur."""
    return _TONES[(user.pk if user is not None else 0) % len(_TONES)]


@register.filter
def ago(value):
    """« il y a 3 heures » : première unité de timesince()."""
    if not value:
        return ""
    return "il y a " + timesince(value).split(",")[0].replace("\xa0", " ")
