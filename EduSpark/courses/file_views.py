"""Accès contrôlé aux supports de cours : page d'aperçu et flux du fichier.

Les fichiers sont stockés hors de MEDIA_ROOT (voir ``courses.storage``) : ils
n'ont aucune URL publique et ne sont lisibles qu'à travers ``material_file``,
qui vérifie que l'utilisateur a le droit de voir le cours (auteur, admin de
l'université, étudiant d'une classe où le cours est publié).
"""

import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.http import content_disposition_header
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET

from accounts.tenancy import Role

from . import files
from .models import CourseMaterial
from .services import can_access_material

logger = logging.getLogger(__name__)

RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK_SIZE = 64 * 1024
UNSATISFIABLE = "unsatisfiable"


def parse_range(header, size):
    """Interprète un en-tête ``Range`` à une seule plage.

    Retourne ``(début, fin)`` (octets inclusifs), ``None`` s'il faut ignorer
    l'en-tête (absent, mal formé ou à plages multiples : on sert alors tout le
    fichier) ou ``UNSATISFIABLE`` si la plage est hors du fichier (416).
    """
    match = RANGE_PATTERN.match((header or "").strip())
    if not match:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:  # « bytes=-N » : les N derniers octets
        length = int(last)
        if length == 0:
            return UNSATISFIABLE
        return max(size - length, 0), size - 1
    start = int(first)
    if last and int(last) < start:
        return None
    if start >= size:
        return UNSATISFIABLE
    end = min(int(last), size - 1) if last else size - 1
    return start, end


class _RangeIterator:
    """Lit la portion ``[start, start + length)`` d'un fichier ouvert, puis le ferme."""

    def __init__(self, handle, start, length):
        self.handle = handle
        self.remaining = length
        handle.seek(start)

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining <= 0:
            raise StopIteration
        chunk = self.handle.read(min(CHUNK_SIZE, self.remaining))
        if not chunk:
            raise StopIteration
        self.remaining -= len(chunk)
        return chunk

    def close(self):
        self.handle.close()


def serve_material(request, material, as_attachment):
    """Réponse HTTP du fichier : complète (200), partielle (206) ou refusée (416)."""
    try:
        handle = material.file.open("rb")
        size = material.file.size
    except (OSError, ValueError):
        logger.warning("Fichier du support %s introuvable sur le disque.", material.pk)
        raise Http404("Fichier introuvable.")

    # Le type annoncé vient de la liste blanche des extensions, jamais du contenu.
    content_type = files.mime_for(material.original_name or material.file.name)
    requested = parse_range(request.headers.get("Range"), size)
    if requested == UNSATISFIABLE:
        handle.close()
        response = HttpResponse(status=416)
        response["Content-Range"] = "bytes */%d" % size
    elif requested is not None:
        start, end = requested
        length = end - start + 1
        response = StreamingHttpResponse(
            _RangeIterator(handle, start, length), status=206, content_type=content_type,
        )
        response["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
        response["Content-Length"] = str(length)
    else:
        response = FileResponse(handle, content_type=content_type)
        response["Content-Length"] = str(size)
    response["Content-Disposition"] = content_disposition_header(
        as_attachment, material.original_name or "support",
    )
    response["Accept-Ranges"] = "bytes"
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, private=True, no_cache=True)
    return response


def _accessible_material(request, pk):
    material = get_object_or_404(
        CourseMaterial.objects.select_related(
            "course__subject", "course__professor__membership__user", "chapter",
        ),
        pk=pk,
    )
    if not can_access_material(request.user, material):
        # 404 plutôt que 403 : on ne révèle pas l'existence d'un support à qui n'y a pas droit.
        raise Http404("Support introuvable.")
    return material


@login_required
@require_GET
@xframe_options_sameorigin  # l'aperçu PDF est affiché dans une <iframe> de la même origine
def material_file(request, pk):
    material = _accessible_material(request, pk)
    wants_download = request.GET.get("telecharger") == "1"
    return serve_material(request, material, as_attachment=wants_download or not material.can_preview)


@login_required
@require_GET
def material_view(request, pk):
    """Page d'aperçu d'un support : lecteur vidéo / audio, PDF intégré ou lien de téléchargement."""
    material = _accessible_material(request, pk)
    course = material.course
    membership = request.user.memberships.filter(university_id=course.university_id).first()
    role = Role.PLATFORM_ADMIN if request.user.is_superuser else (membership.role if membership else None)
    if role == Role.STUDENT:
        back_url = reverse("courses:student_course_detail", args=[course.pk])
    elif role == Role.PROFESSOR:
        back_url = reverse("courses:prof_course_detail", args=[course.pk])
    else:
        back_url = reverse("courses:admin_course_detail", args=[course.pk])
    return render(request, "courses/material_view.html", {
        "material": material,
        "course": course,
        "back_url": back_url,
        "file_url": reverse("courses:material_file", args=[material.pk]),
        "download_url": reverse("courses:material_file", args=[material.pk]) + "?telecharger=1",
    })
