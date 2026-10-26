"""Tâches de fond du module cours, exécutées par courses.services.jobs."""

import logging

from .services import ai

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"


def generate_syllabus_task(title, level, course_id, options):
    """Lance le pipeline IA et renvoie un résultat sérialisable.

    Les erreurs attendues (IA indisponible) sont renvoyées comme un statut, pas
    levées : la page d'attente peut alors proposer la saisie manuelle. La
    limite d'appels est comptée par la vue, avant le lancement.
    """
    try:
        result = ai.generate_syllabus(title, level, course_id=course_id, options=options)
    except ai.AIUnavailable as error:
        logger.warning("Plan de cours IA indisponible (cours %s) : %s", course_id, error)
        return {"status": STATUS_UNAVAILABLE, "message": str(error)}
    return dict(result, status=STATUS_OK)
