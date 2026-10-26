"""Filtres d'affichage du module cours."""

from django import template

from courses import files
from courses.services import format_minutes

register = template.Library()


@register.filter
def minutes_fr(value):
    """``210`` -> ``3 h 30``."""
    return format_minutes(value)


@register.filter
def size_fr(value):
    """Octets -> ``4,8 Mo``."""
    return files.format_size(value)
