from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_schoolclass_study_program'),
    ]

    operations = [
        migrations.AddField(
            model_name='schoolclass',
            name='section',
            field=models.CharField(blank=True, help_text='ex. A, B, Sciences, Littérature', max_length=60, verbose_name='Section'),
        ),
        migrations.RemoveConstraint(
            model_name='schoolclass',
            name='unique_class_per_year',
        ),
        migrations.AddConstraint(
            model_name='schoolclass',
            constraint=models.UniqueConstraint(fields=('university', 'name', 'section', 'academic_year'), name='unique_class_per_year'),
        ),
    ]
