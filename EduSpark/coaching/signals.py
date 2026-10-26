"""Mise à jour automatique de l'assiduité après un relevé de présence."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import AttendanceRecord
from .services import sync_student_attendance


@receiver(post_save, sender=AttendanceRecord)
def attendance_record_saved(sender, instance, **kwargs):
    sync_student_attendance(instance.student)


@receiver(post_delete, sender=AttendanceRecord)
def attendance_record_deleted(sender, instance, **kwargs):
    sync_student_attendance(instance.student)
