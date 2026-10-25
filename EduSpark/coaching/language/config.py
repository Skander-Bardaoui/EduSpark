"""Référentiels du test de langue orale (examens, niveaux, langues)."""

EXAM_TYPES = ("ielts", "cambridge_b2")
LEVELS = ("b1", "b2", "c1")
EXERCISE_TYPES = ("topic_discussion", "debate")
EXERCISE_SELECTIONS = EXERCISE_TYPES + ("random",)

DEFAULT_LANGUAGE = "en"
SCORE_MAX = 9

EXAMS = {
    "ielts": {
        "name": "IELTS",
        "description": "Test d’expression orale académique — 3 parties, jusqu’à 14 minutes.",
        "duration_seconds": 840,
    },
    "cambridge_b2": {
        "name": "Cambridge B2 First",
        "description": "Cambridge B2 First — 4 parties, environ 15 minutes.",
        "duration_seconds": 900,
    },
}

LEVEL_LABELS = {
    "b1": "B1 — Intermédiaire",
    "b2": "B2 — Intermédiaire avancé",
    "c1": "C1 — Avancé",
}

LEVEL_LABELS_EN = {
    "b1": "B1 — Intermediate",
    "b2": "B2 — Upper Intermediate",
    "c1": "C1 — Advanced",
}

LEVEL_ORDER = {"B1": 1, "B2": 2, "C1": 3}

EXERCISE_LABELS = {
    "topic_discussion": "Discussion thématique",
    "debate": "Débat",
}

EXERCISE_LABELS_EN = {
    "topic_discussion": "Topic Discussion",
    "debate": "Debate",
}

EXERCISE_DESCRIPTIONS = {
    "random": "Laissez l’examinateur choisir le type d’exercice.",
    "topic_discussion": "Discutez d’un sujet en profondeur avec des questions de suivi.",
    "debate": "Prenez position et défendez-la face à l’examinateur.",
}

LANGUAGES = {
    "en": {
        "code": "en",
        "label": "Anglais",
        "description": "Passez l’examen oral en anglais.",
        "stt_code": "en",
        "tts_voice": "onyx",
        "locale": "en-US",
    },
    "fr": {
        "code": "fr",
        "label": "Français",
        "description": "Passez l’examen oral en français.",
        "stt_code": "fr",
        "tts_voice": "alloy",
        "locale": "fr-FR",
    },
}
LANGUAGE_CODES = tuple(LANGUAGES)
LANGUAGE_CHOICES = [(code, data["label"]) for code, data in LANGUAGES.items()]

EXAM_CHOICES = [(key, value["name"]) for key, value in EXAMS.items()]
LEVEL_CHOICES = [(key, LEVEL_LABELS[key]) for key in LEVELS]
EXERCISE_CHOICES = [(key, EXERCISE_LABELS[key]) for key in EXERCISE_TYPES]

VERDICT_LABELS = {
    "Ready": "Prêt",
    "Needs Work": "À consolider",
    "Not Ready": "Pas encore prêt",
}

VERDICT_STYLES = {
    "Ready": "bg-primary-fixed text-primary",
    "Needs Work": "bg-tertiary-fixed text-on-tertiary-fixed",
    "Not Ready": "bg-error-container text-on-error-container",
}

STATUS_LABELS = {
    "active": "En cours",
    "completed": "Terminé",
    "abandoned": "Abandonné",
}

STATUS_STYLES = {
    "active": "bg-tertiary-fixed text-on-tertiary-fixed",
    "completed": "bg-primary-fixed text-primary",
    "abandoned": "bg-surface-container-high text-on-surface-variant",
}
