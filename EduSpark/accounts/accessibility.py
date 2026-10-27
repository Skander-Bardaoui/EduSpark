"""Menu Accessibilité du portail : préférences, context processor et vue d'enregistrement.

Les préférences sont stockées dans ``Profil.accessibility`` (JSON) et toujours
passées par ``clean_preferences`` : seules les clés et valeurs de la liste
blanche sont conservées, toute valeur invalide est remplacée par la valeur par
défaut. Le navigateur applique les réglages par des classes sur ``<html>``
(voir templates/portal/_a11y_head.html et _a11y_script.html).
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import Profil

DEFAULTS = {
    "text_size": 100,
    "theme": "auto",
    "contrast": False,
    "dyslexia_font": False,
    "spacing": False,
    "reduce_motion": False,
    "underline_links": False,
    "strong_focus": False,
    "big_cursor": False,
    "reading_guide": False,
    "speech_rate": 1,
}

CHOICES = {
    "text_size": (100, 125, 150, 175),
    "theme": ("light", "dark", "auto"),
    "speech_rate": (0.75, 1, 1.25),
}

# Libellés de l'interface (partagés par le panneau et la section profil).
TEXT_SIZES = [(100, "100 %"), (125, "125 %"), (150, "150 %"), (175, "175 %")]
THEMES = [("light", "Clair", "light_mode"), ("dark", "Sombre", "dark_mode"), ("auto", "Automatique", "contrast")]
SPEECH_RATES = [(0.75, "Lente"), (1, "Normale"), (1.25, "Rapide")]
SWITCHES = [
    ("contrast", "Contraste élevé", "Renforce les contrastes et fonce les textes secondaires."),
    ("dyslexia_font", "Police lisible (dyslexie)", "Utilise la police Atkinson Hyperlegible."),
    ("spacing", "Espacement du texte", "Augmente l'interligne et l'espace entre lettres et mots."),
    ("reduce_motion", "Réduire les animations", "Supprime les animations et transitions."),
    ("underline_links", "Liens soulignés", "Souligne tous les liens du contenu."),
    ("strong_focus", "Focus renforcé", "Contour jaune épais autour de l'élément actif au clavier."),
    ("big_cursor", "Grand curseur", "Agrandit le pointeur de la souris."),
    ("reading_guide", "Guide de lecture", "Bande horizontale qui suit la souris pour suivre la ligne lue."),
]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def clean_preferences(data):
    """Préférences valides et complètes à partir de ``data`` (liste blanche)."""
    data = data if isinstance(data, dict) else {}
    cleaned = {}
    for key, default in DEFAULTS.items():
        value = data.get(key, default)
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif key in ("text_size", "speech_rate"):
            valid = _is_number(value) and value in CHOICES[key]
        else:
            valid = isinstance(value, str) and value in CHOICES[key]
        if valid and key == "text_size":
            value = int(value)
        cleaned[key] = value if valid else default
    return cleaned


def _profil(user):
    profil, _created = Profil.objects.get_or_create(user=user)
    return profil


def accessibility(request):
    """Context processor : préférences enregistrées du compte connecté, sinon ``None``."""
    user = getattr(request, "user", None)
    prefs = None
    if user is not None and user.is_authenticated:
        saved = getattr(getattr(user, "profil", None), "accessibility", None)
        if saved:
            prefs = clean_preferences(saved)
    return {
        "accessibility_prefs": prefs,
        "a11y_text_sizes": TEXT_SIZES,
        "a11y_themes": THEMES,
        "a11y_speech_rates": SPEECH_RATES,
        "a11y_switches": SWITCHES,
    }


@login_required
@require_POST
def accessibility_preferences(request):
    """Enregistre les préférences envoyées en JSON et renvoie leur version nettoyée."""
    try:
        data = json.loads(request.body.decode("utf-8") or "null")
    except (UnicodeDecodeError, ValueError):
        return JsonResponse({"error": "JSON invalide"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Objet JSON attendu"}, status=400)
    prefs = clean_preferences(data)
    profil = _profil(request.user)
    profil.accessibility = prefs
    profil.save(update_fields=["accessibility"])
    return JsonResponse(prefs)
