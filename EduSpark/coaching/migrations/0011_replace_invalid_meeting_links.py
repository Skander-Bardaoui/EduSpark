import secrets

from django.conf import settings
from django.db import migrations

PLACEHOLDER_TOPICS = (
    "Précisez le motif de votre demande.",
    "Décrivez brièvement votre demande...",
    "Précisez votre situation, vos difficultés ou vos questions...",
)


def replace_invalid_meeting_links(apps, schema_editor):
    TutoringSession = apps.get_model("coaching", "TutoringSession")
    TutoringSlot = apps.get_model("coaching", "TutoringSlot")
    base = getattr(settings, "VIDEO_MEETING_BASE_URL", "https://meet.jit.si").rstrip("/")

    for model, queryset in (
        (TutoringSession, TutoringSession.objects.all()),
        (TutoringSlot, TutoringSlot.objects.all()),
    ):
        for item in queryset.exclude(meeting_url=""):
            if not item.meeting_url.startswith("https://meet.google.com/"):
                continue
            item.meeting_url = "%s/EduSpark-%s" % (base, secrets.token_hex(8))
            item.save(update_fields=["meeting_url"])

    TutoringSession.objects.filter(topic__in=PLACEHOLDER_TOPICS).update(
        topic="Rendez-vous de tutorat",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("coaching", "0010_backfill_tutoringsession_meeting_urls"),
    ]

    operations = [
        migrations.RunPython(replace_invalid_meeting_links, migrations.RunPython.noop),
    ]
