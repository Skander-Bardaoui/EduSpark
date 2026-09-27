from django.db import migrations


def create_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ("admin", "prof", "etudiant"):
        Group.objects.get_or_create(name=name)


def remove_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=("admin", "prof", "etudiant")).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_role_groups, remove_role_groups),
    ]
