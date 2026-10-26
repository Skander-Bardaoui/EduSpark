from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import SchoolClass

from .models import GradeRecord, semester_for


@receiver(post_save, sender=SchoolClass)
def create_grade_record(sender, instance, created, **kwargs):
    """Chaque nouvelle classe dispose immédiatement d'un relevé à compléter."""
    if not created:
        return
    GradeRecord.objects.get_or_create(
        school_class=instance,
        semester=semester_for(instance),
        defaults={"university": instance.university},
    )
