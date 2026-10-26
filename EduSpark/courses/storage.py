"""Stockage des supports de cours, hors de MEDIA_ROOT.

Aucun fichier n'est joignable par une URL publique : la lecture passe
obligatoirement par la vue ``courses:material_file``, qui contrôle les droits
de l'utilisateur (auteur, admin de l'université, étudiants des classes où le
cours est publié).
"""

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.functional import cached_property


class ProtectedMediaStorage(FileSystemStorage):
    """Système de fichiers rangé sous ``settings.PROTECTED_MEDIA_ROOT``, sans URL."""

    @cached_property
    def base_location(self):
        return settings.PROTECTED_MEDIA_ROOT

    @cached_property
    def location(self):
        return os.path.abspath(self.base_location)

    def _clear_cached_properties(self, setting, **kwargs):
        # Permet à override_settings(PROTECTED_MEDIA_ROOT=...) d'être pris en compte (tests).
        super()._clear_cached_properties(setting, **kwargs)
        if setting == "PROTECTED_MEDIA_ROOT":
            self.__dict__.pop("base_location", None)
            self.__dict__.pop("location", None)

    def url(self, name):
        # Volontairement vide : un gabarit qui afficherait ``file.url`` ne doit
        # jamais produire un lien direct vers le fichier.
        return ""
