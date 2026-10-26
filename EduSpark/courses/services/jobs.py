"""Tâches de fond légères du module cours (sans Celery ni Redis).

La génération d'un plan de cours IA (lecture locale des supports puis
rédaction par l'API) prend de 10 secondes à 2 minutes : elle ne doit pas
bloquer la requête HTTP. ``submit`` la lance dans un thread du serveur et
renvoie aussitôt un identifiant ; l'état de la tâche est gardé dans le cache
Django, que la page d'attente interroge.

États : ``PENDING`` (en file) → ``STARTED`` (en cours) → ``SUCCESS`` ou
``FAILURE``. Une tâche inconnue ou expirée (plus d'une heure) renvoie ``None``.

Limite assumée : le cache par défaut (mémoire locale) n'est partagé que par
un processus. Avec plusieurs processus serveur (gunicorn -w 4…), configurer un
cache partagé (Redis, Memcached ou base de données) pour que la page d'attente
retrouve la tâche.
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache
from django.db import connections

logger = logging.getLogger(__name__)

PENDING = "PENDING"
STARTED = "STARTED"
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
READY_STATES = frozenset((SUCCESS, FAILURE))

JOB_TTL = 60 * 60
MAX_WORKERS = 2

# Les tests exécutent les tâches dans le thread de la requête (même connexion à
# la base, donc mêmes données de test). Voir courses/tests/base.py.
RUN_INLINE = False

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="courses-job")


def _key(job_id):
    return "courses:job:%s" % job_id


def _store(job_id, state, result=None):
    cache.set(_key(job_id), {"state": state, "result": result}, JOB_TTL)


def get(job_id):
    """``{"state": ..., "result": ...}`` de la tâche, ou ``None`` si inconnue / expirée."""
    return cache.get(_key(job_id))


def is_ready(job):
    return job is None or job["state"] in READY_STATES


def _run(job_id, func, args):
    _store(job_id, STARTED)
    try:
        result = func(*args)
    except Exception:  # toute erreur inattendue devient un état FAILURE lisible
        logger.exception("Tâche de fond %s en échec", job_id)
        _store(job_id, FAILURE)
    else:
        _store(job_id, SUCCESS, result)
    finally:
        if not RUN_INLINE:
            # Le thread a ouvert sa propre connexion à la base : on la libère.
            connections.close_all()


def submit(func, *args):
    """Lance ``func(*args)`` en arrière-plan ; renvoie l'identifiant de la tâche."""
    job_id = str(uuid.uuid4())
    _store(job_id, PENDING)
    if RUN_INLINE:
        _run(job_id, func, args)
    else:
        _executor.submit(_run, job_id, func, args)
    return job_id
