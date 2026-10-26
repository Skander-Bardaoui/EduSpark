import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0002_material_word_documents"),
    ]

    operations = [
        migrations.AddField(
            model_name="chapter",
            name="objectives",
            field=models.TextField(
                blank=True, help_text="Un objectif par ligne.", verbose_name="Objectifs d'apprentissage",
            ),
        ),
        migrations.AddField(
            model_name="chapter",
            name="duration_hours",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="Durée (heures)",
            ),
        ),
    ]
