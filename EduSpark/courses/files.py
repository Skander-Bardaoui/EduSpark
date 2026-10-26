"""Types de supports de cours acceptés (PDF, présentations, vidéos, audios)
et validation des fichiers téléversés."""

import os

from django.core.exceptions import ValidationError

MB = 1024 * 1024

PDF = "pdf"
PRESENTATION = "presentation"
VIDEO = "video"
AUDIO = "audio"

TYPE_CHOICES = (
    (PDF, "PDF"),
    (PRESENTATION, "Présentation"),
    (VIDEO, "Vidéo"),
    (AUDIO, "Audio"),
)

TYPE_RULES = {
    PDF: {
        "extensions": (".pdf",),
        "max_size": 50 * MB,
        "icon": "picture_as_pdf",
        "tone": "bg-error-container text-on-error-container",
    },
    PRESENTATION: {
        "extensions": (".ppt", ".pptx", ".pps", ".ppsx", ".odp"),
        "max_size": 100 * MB,
        "icon": "slideshow",
        "tone": "bg-tertiary-fixed text-on-tertiary-fixed",
    },
    VIDEO: {
        "extensions": (".mp4", ".webm", ".ogv", ".mov", ".m4v"),
        "max_size": 500 * MB,
        "icon": "movie",
        "tone": "bg-secondary-fixed text-on-secondary-fixed",
    },
    AUDIO: {
        "extensions": (".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac"),
        "max_size": 100 * MB,
        "icon": "headphones",
        "tone": "bg-primary-fixed text-primary",
    },
}

# Content-Type renvoyé au téléchargement : toujours issu de cette liste blanche
# (jamais du contenu du fichier ni de ce que déclare le navigateur).
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pps": "application/vnd.ms-powerpoint",
    ".ppsx": "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
}

# Types que le navigateur sait afficher : ils sont servis « inline » (aperçu
# dans la page) ; les présentations sont toujours proposées en téléchargement.
INLINE_TYPES = (PDF, VIDEO, AUDIO)

ACCEPTED_LABEL = (
    "PDF (.pdf), présentations (.ppt, .pptx, .pps, .ppsx, .odp), "
    "vidéos (.mp4, .webm, .ogv, .mov, .m4v) et audios "
    "(.mp3, .wav, .ogg, .m4a, .aac, .flac)"
)

# Extensions rassemblées pour l'attribut ``accept`` du champ fichier.
ACCEPT_ATTRIBUTE = ",".join(
    extension for rule in TYPE_RULES.values() for extension in rule["extensions"]
)


def extension_of(name):
    return os.path.splitext(name or "")[1].lower()


def detect_type(name):
    """Type de support (``pdf``/``presentation``/``video``/``audio``) d'après l'extension."""
    extension = extension_of(name)
    for material_type, rule in TYPE_RULES.items():
        if extension in rule["extensions"]:
            return material_type
    return None


def mime_for(name):
    return MIME_TYPES.get(extension_of(name), "application/octet-stream")


def safe_original_name(name):
    """Nom d'origine conservé pour l'affichage : sans chemin, limité à 255 caractères."""
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    return base[:255] or "support"


def format_size(size):
    """Taille lisible en français : ``4,8 Mo``."""
    size = int(size or 0)
    if size < 1024:
        return "%d o" % size
    value = float(size)
    for unit in ("Ko", "Mo", "Go"):
        value /= 1024
        if value < 1024 or unit == "Go":
            text = ("%.1f" % value).replace(".", ",")
            if text.endswith(",0"):
                text = text[:-2]
            return "%s %s" % (text, unit)


def _looks_like_pdf(upload):
    upload.seek(0)
    head = upload.read(1024)
    upload.seek(0)
    return b"%PDF-" in head


def validate_upload(upload):
    """Valide un fichier téléversé et retourne son type de support.

    Contrôle l'extension (liste blanche), la taille maximale propre au type
    et, pour les PDF, la signature du fichier.
    """
    material_type = detect_type(upload.name)
    if material_type is None:
        raise ValidationError(
            "Format non pris en charge. Formats acceptés : %s." % ACCEPTED_LABEL
        )
    if upload.size == 0:
        raise ValidationError("Le fichier est vide.")
    max_size = TYPE_RULES[material_type]["max_size"]
    if upload.size > max_size:
        raise ValidationError(
            "Fichier trop volumineux (%s). La taille maximale pour ce type est de %s."
            % (format_size(upload.size), format_size(max_size))
        )
    if material_type == PDF and not _looks_like_pdf(upload):
        raise ValidationError("Ce fichier n'est pas un PDF valide.")
    return material_type
