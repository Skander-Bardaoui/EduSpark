"""Cohérence des données : fichiers orphelins et publications devenues sans objet."""

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import CourseMaterial, SchoolClass, TeachingAssignment, purge_publications


@receiver(post_delete, sender=CourseMaterial)
def delete_material_file(sender, instance, **kwargs):
    """Supprime le fichier du disque, une fois la suppression validée en base."""
    name, storage = instance.file.name, instance.file.storage
    if name:
        transaction.on_commit(lambda: storage.delete(name))


@receiver(post_delete, sender=TeachingAssignment)
def purge_publications_of_deleted_assignment(sender, instance, **kwargs):
    """Sans affectation, le professeur n'enseigne plus la matière à la classe :
    ses cours n'y sont plus publiés."""
    purge_publications(instance.school_class_id, instance.subject_id, instance.professor_id)
    still_assigned = TeachingAssignment.objects.filter(
        school_class_id=instance.school_class_id, professor_id=instance.professor_id,
    ).exists()
    if not still_assigned:
        school_class = SchoolClass.objects.filter(pk=instance.school_class_id).first()
        if school_class is not None:
            school_class.professors.remove(instance.professor_id)
