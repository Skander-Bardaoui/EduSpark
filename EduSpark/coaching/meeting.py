"""Génération des liens de visioconférence des rendez-vous de tutorat."""

import logging
import os
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _generate_jitsi_url():
    """Salle Jitsi Meet immédiatement accessible, sans configuration."""
    base = getattr(settings, "VIDEO_MEETING_BASE_URL", "https://meet.jit.si").rstrip("/")
    return "%s/EduSpark-%s" % (base, secrets.token_hex(8))


def _event_body(session):
    start = session.scheduled_at or timezone.now()
    end = start + timedelta(minutes=session.duration_minutes or 30)
    timezone_name = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", settings.TIME_ZONE)
    return {
        "summary": "Tutorat EduSpark — %s" % session.topic,
        "description": (
            "Rendez-vous de tutorat EduSpark entre %s et %s."
            % (
                session.student.membership.user.get_full_name()
                or session.student.membership.user.email,
                session.professor.membership.user.get_full_name()
                or session.professor.membership.user.email,
            )
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": timezone_name},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone_name},
        "conferenceData": {
            "createRequest": {
                "requestId": uuid.uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            },
        },
    }


def _insert_meet_event(service, calendar_id, session):
    try:
        event = service.events().insert(
            calendarId=calendar_id or "primary",
            body=_event_body(session),
            conferenceDataVersion=1,
            sendUpdates="none",
        ).execute()
    except Exception:
        logger.exception("Impossible de créer le rendez-vous Google Meet.")
        return ""
    return event.get("hangoutLink") or ""


def _google_oauth_meet_url(session):
    client_file = getattr(settings, "GOOGLE_OAUTH_CLIENT_FILE", "")
    token_file = getattr(settings, "GOOGLE_OAUTH_TOKEN_FILE", "")
    if not client_file or not token_file or not os.path.exists(token_file):
        return ""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        logger.warning(
            "google-api-python-client / google-auth ne sont pas installés : "
            "repli sur Jitsi Meet."
        )
        return ""
    try:
        credentials = Credentials.from_authorized_user_file(token_file, GOOGLE_SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            with open(token_file, "w", encoding="utf-8") as handle:
                handle.write(credentials.to_json())
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    except Exception:
        logger.exception("Autorisation Google OAuth invalide : repli sur Jitsi Meet.")
        return ""
    return _insert_meet_event(service, settings.GOOGLE_CALENDAR_ID, session)


def _google_service_account_meet_url(session):
    credentials_file = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "")
    impersonate = getattr(settings, "GOOGLE_IMPERSONATE_USER", "")
    if not credentials_file or not impersonate:
        return ""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        logger.warning(
            "google-api-python-client / google-auth ne sont pas installés : "
            "repli sur Jitsi Meet."
        )
        return ""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=GOOGLE_SCOPES,
        ).with_subject(impersonate)
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    except Exception:
        logger.exception("Compte de service Google invalide : repli sur Jitsi Meet.")
        return ""
    return _insert_meet_event(service, settings.GOOGLE_CALENDAR_ID, session)


def generate_meeting_url(session=None):
    """Génère un lien de visioconférence réellement accessible."""
    provider = getattr(settings, "VIDEO_MEETING_PROVIDER", "jitsi").lower()
    if provider == "google" and session is not None:
        url = _google_oauth_meet_url(session) or _google_service_account_meet_url(session)
        if url:
            return url
    return _generate_jitsi_url()


def ensure_meeting_url(session):
    """Retourne le lien du rendez-vous, en le générant s'il est absent."""
    if session.meeting_url:
        return session.meeting_url
    if session.slot_id and session.slot.meeting_url:
        session.meeting_url = session.slot.meeting_url
        return session.meeting_url
    session.meeting_url = generate_meeting_url(session)
    return session.meeting_url
