"""Évaluation assistée par IA d'un projet étudiant déposé en ZIP.

L'IA ne reçoit que les noms de fichiers et le texte extrait (txt, md, code,
PDF). Elle renvoie une appréciation par critère et une note pondérée. Le
professeur garde toujours la possibilité de remplacer cette note.
"""

import io
import json
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import zipfile

import requests
from django.conf import settings

from .ai_quiz import _extract_json, ai_quiz_available

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".yaml",
    ".yml", ".ini", ".cfg", ".conf", ".log", ".html", ".htm", ".css",
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".py", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".php", ".rb", ".go", ".rs", ".swift", ".kt",
    ".sql", ".sh", ".bat", ".ps1", ".ipynb", ".r", ".m",
}
PDF_EXTENSION = ".pdf"
MAX_FILE_TEXT = 12000
MAX_FILES_FOR_PROMPT = 80


class ProjectEvaluationError(Exception):
    """L'évaluation IA n'a pas pu être produite."""


def _model():
    return (
        getattr(settings, "GROQ_MODEL", "") or DEFAULT_MODEL
    ).strip()


def _max_zip_bytes():
    return int(getattr(settings, "EXAM_PROJECT_MAX_ZIP_BYTES", 50 * 1024 * 1024))


def _max_uncompressed_bytes():
    return int(getattr(
        settings, "EXAM_PROJECT_MAX_UNCOMPRESSED_BYTES", 150 * 1024 * 1024,
    ))


def _max_files():
    return int(getattr(settings, "EXAM_PROJECT_MAX_FILES", 250))


def _max_text_chars():
    return int(getattr(settings, "EXAM_PROJECT_MAX_TEXT_CHARS", 40000))


def _safe_zip_name(name):
    normalised = str(name or "").replace("\\", "/")
    if not normalised or normalised.startswith("/"):
        return None
    parts = [part for part in normalised.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _pdf_text(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return ""
    chunks = []
    size = 0
    for page in reader.pages:
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            continue
        if not text:
            continue
        chunks.append(text)
        size += len(text)
        if size >= MAX_FILE_TEXT:
            break
    return "\n".join(chunks)[:MAX_FILE_TEXT]


def _file_text(data, suffix):
    if suffix == PDF_EXTENSION:
        return _pdf_text(data)
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)[:MAX_FILE_TEXT]
        except UnicodeDecodeError:
            continue
    return ""


def extract_project_source(submission):
    """Retourne les noms de fichiers et le texte exploitable du ZIP."""
    try:
        handle = submission.file.open("rb")
    except (OSError, ValueError) as exc:
        raise ProjectEvaluationError(
            "L'archive du projet est introuvable sur le serveur."
        ) from exc

    with handle:
        try:
            with zipfile.ZipFile(handle) as archive:
                infos = [
                    info for info in archive.infolist()
                    if not info.is_dir()
                    and not info.filename.replace("\\", "/").startswith("__MACOSX/")
                ]
                if not infos:
                    raise ProjectEvaluationError("L'archive ZIP est vide.")
                if len(infos) > _max_files():
                    raise ProjectEvaluationError(
                        "L'archive contient trop de fichiers pour être analysée."
                    )
                total = sum(max(0, info.file_size) for info in infos)
                if total > _max_uncompressed_bytes():
                    raise ProjectEvaluationError(
                        "Le contenu décompressé du projet est trop volumineux."
                    )

                files = []
                blocks = []
                size = 0
                for info in infos:
                    name = _safe_zip_name(info.filename)
                    if not name:
                        continue
                    files.append(name)
                    suffix = Path(name).suffix.lower()
                    basename = Path(name).name.lower()
                    if suffix not in TEXT_EXTENSIONS and suffix != PDF_EXTENSION:
                        if not basename.startswith("readme"):
                            continue
                    if info.file_size > 5 * 1024 * 1024:
                        continue
                    try:
                        data = archive.read(info)
                    except (RuntimeError, zipfile.BadZipFile, OSError):
                        continue
                    text = _file_text(data, suffix).strip()
                    if not text:
                        continue
                    remaining = _max_text_chars() - size
                    if remaining <= 0:
                        break
                    text = text[:remaining]
                    blocks.append("--- %s ---\n%s" % (name, text))
                    size += len(text)
        except zipfile.BadZipFile as exc:
            raise ProjectEvaluationError("Le fichier n'est pas une archive ZIP valide.") from exc

    if not files:
        raise ProjectEvaluationError("Aucun fichier exploitable dans l'archive.")
    return {
        "files": files[:MAX_FILES_FOR_PROMPT],
        "file_count": len(files),
        "text": "\n\n".join(blocks),
        "text_chars": size,
    }


def _request_json(system_prompt, user_prompt, timeout=90):
    api_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if not api_key:
        raise ProjectEvaluationError(
            "La clé GROQ_API_KEY n'est pas configurée : utilisez la notation manuelle."
        )
    try:
        response = requests.post(
            GROQ_CHAT_URL,
            headers={
                "Authorization": "Bearer %s" % api_key,
                "Content-Type": "application/json",
            },
            json={
                "model": _model(),
                "temperature": 0.1,
                "max_tokens": 3000,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ProjectEvaluationError(
            "Impossible de joindre le service IA. Utilisez la notation manuelle."
        ) from exc
    if response.status_code != 200:
        raise ProjectEvaluationError(
            "Le service IA a répondu avec le statut %s." % response.status_code
        )
    try:
        content = response.json()["choices"][0]["message"]["content"]
        return _extract_json(content)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ProjectEvaluationError(
            "La réponse du service IA est illisible. Utilisez la notation manuelle."
        ) from exc


def _score(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return max(Decimal("0"), min(Decimal("20"), number))


def _clean_text(value, limit=800):
    return " ".join(str(value or "").split()).strip()[:limit]


def evaluate_project(submission):
    """Évalue un projet et retourne un résultat JSON validé et noté."""
    if not ai_quiz_available():
        raise ProjectEvaluationError(
            "La clé GROQ_API_KEY n'est pas configurée : utilisez la notation manuelle."
        )

    session = submission.session
    criteria = list(session.project_criteria.all())
    if not criteria:
        from ..models import ProjectCriterion
        criteria = list(ProjectCriterion.ensure_defaults(session))
    if not criteria:
        raise ProjectEvaluationError(
            "Ajoutez au moins un critère avant de lancer l'évaluation IA."
        )

    source = extract_project_source(submission)
    if not source["text"] and not source["files"]:
        raise ProjectEvaluationError(
            "Le projet ne contient aucun texte ou fichier exploitable par l'IA."
        )

    criteria_payload = [
        {
            "criterion_id": criterion.pk,
            "label": criterion.label,
            "expected": criterion.description,
            "weight": criterion.weight,
        }
        for criterion in criteria
    ]
    payload = {
        "projet": session.title,
        "matiere": str(session.course_subject) if session.course_subject_id else "",
        "fichiers": source["files"],
        "nombre_de_fichiers": source["file_count"],
        "contenu": source["text"][: _max_text_chars()],
        "criteres": criteria_payload,
    }

    data = _request_json(
        "Tu es un professeur qui corrige un projet étudiant. Évalue uniquement "
        "à partir des fichiers et du texte fournis, sans inventer de contenu. "
        "Pour chaque critère, indique met (booléen), score (0 à 20) et comment "
        "(justification courte). Ajoute summary (synthèse) et overall_comment. "
        "Réponds UNIQUEMENT en JSON valide, sans Markdown, au format : "
        '{"summary":"...","overall_comment":"...","criteria":['
        '{"criterion_id":1,"met":true,"score":15,"comment":"..."}]}',
        "Évalue ce projet en français :\n%s"
        % json.dumps(payload, ensure_ascii=False),
    )

    raw_rows = data.get("criteria") or []
    rows_by_id = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("criterion_id") or row.get("id") or "").strip()
        if key:
            rows_by_id[key] = row

    result_rows = []
    weighted_total = Decimal("0")
    weight_total = Decimal("0")
    for criterion in criteria:
        row = rows_by_id.get(str(criterion.pk), {})
        value = _score(row.get("score"))
        met = bool(row.get("met"))
        comment = _clean_text(row.get("comment"), limit=500)
        if not comment:
            comment = "Non évalué par l'IA." if not row else ""
        weight = Decimal(criterion.weight or 1)
        weighted_total += value * weight
        weight_total += weight
        result_rows.append({
            "criterion_id": criterion.pk,
            "label": criterion.label,
            "weight": criterion.weight,
            "met": met,
            "score": float(value),
            "comment": comment,
        })

    score_20 = (
        (weighted_total / weight_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if weight_total else Decimal("0")
    )
    return {
        "source": "ia",
        "model": _model(),
        "summary": _clean_text(data.get("summary"), limit=900),
        "overall_comment": _clean_text(data.get("overall_comment"), limit=1200),
        "criteria": result_rows,
        "score_20": float(score_20),
        "files": source["files"],
        "file_count": source["file_count"],
        "extracted_chars": source["text_chars"],
    }
