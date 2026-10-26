"""Autorisation OAuth Google pour créer de vrais liens Google Meet."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from coaching.meeting import GOOGLE_SCOPES


class Command(BaseCommand):
    help = "Ouvre le consentement Google et enregistre le jeton OAuth local."

    def handle(self, *args, **options):
        client_file = getattr(settings, "GOOGLE_OAUTH_CLIENT_FILE", "")
        token_file = getattr(settings, "GOOGLE_OAUTH_TOKEN_FILE", "")
        if not client_file:
            raise CommandError(
                "GOOGLE_OAUTH_CLIENT_FILE est vide. Téléchargez le client OAuth "
                "Desktop depuis Google Cloud et renseignez son chemin dans .env."
            )
        if not os.path.exists(client_file):
            raise CommandError("Fichier client OAuth introuvable : %s" % client_file)
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as error:
            raise CommandError(
                "google-auth-oauthlib n'est pas installé. Lancez : "
                "pip install -r requirements.txt"
            ) from error

        flow = InstalledAppFlow.from_client_secrets_file(client_file, GOOGLE_SCOPES)
        credentials = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
        )
        token_dir = os.path.dirname(token_file)
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)
        with open(token_file, "w", encoding="utf-8") as handle:
            handle.write(credentials.to_json())
        self.stdout.write(self.style.SUCCESS(
            "Autorisation Google enregistrée dans : %s" % token_file
        ))
