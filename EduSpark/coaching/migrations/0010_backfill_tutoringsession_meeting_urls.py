import secrets
import string

from django.conf import settings
from django.db import migrations


def backfill_meeting_urls(apps, schema_editor):
    TutoringSession = apps.get_model("coaching", "TutoringSession")
    alphabet = string.ascii_lowercase
    base = getattr(settings, "GOOGLE_MEET_BASE_URL", "https://meet.google.com").rstrip("/")
    for session in TutoringSession.objects.filter(
        meeting_url="",
        status__in=("accepted", "completed"),
    ):
        code = "-".join(
            "".join(secrets.choice(alphabet) for _ in range(length))
            for length in (3, 4, 3)
        )
        session.meeting_url = "%s/%s" % (base, code)
        session.save(update_fields=["meeting_url"])


class Migration(migrations.Migration):

    dependencies = [
        ("coaching", "0009_tutoringsession_meeting_url"),
    ]

    operations = [
        migrations.RunPython(backfill_meeting_urls, migrations.RunPython.noop),
    ]
