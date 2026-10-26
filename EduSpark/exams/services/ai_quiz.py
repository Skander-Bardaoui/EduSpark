"""Génération de QCM avec Groq à partir du contenu d'un cours.

Le texte source est composé de la présentation du cours, des résumés de
chapitres et, lorsqu'ils existent, du texte extrait des supports PDF. Les
questions sont produites par lots puis validées côté serveur : chaque question
doit comporter exactement quatre propositions et une seule bonne réponse.
L'enseignant relit toujours le QCM avant de le publier.
"""

import json
import logging
import os
import re
from decimal import Decimal

import requests
from django.conf import settings

from courses.files import PDF

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_SOURCE_CHARS = 40000
MAX_QUESTION_CHARS = 1200
MAX_EXPLANATION_CHARS = 800
BATCH_SIZE = 10
CHOICES_PER_QUESTION = 4
PDF_PAGE_CHARS = 4000


class QuizGenerationError(Exception):
    """La génération du QCM a échoué (configuration, réseau, réponse invalide)."""


def _api_key():
    return (
        getattr(settings, "GROQ_API_KEY", "")
        or os.environ.get("GROQ_API_KEY", "")
    ).strip()


def _model():
    return (
        getattr(settings, "GROQ_MODEL", "")
        or os.environ.get("GROQ_MODEL", "")
        or DEFAULT_MODEL
    ).strip()


def ai_quiz_available():
    """Indique si le service de génération peut réellement appeler Groq."""
    return bool(_api_key())


# ---------------------------------------------------------------------------
# Extraction du contenu du cours
# ---------------------------------------------------------------------------

def _pdf_text(path, limit=PDF_PAGE_CHARS):
    """Texte des premières pages d'un PDF, ou chaîne vide si illisible."""
    try:
        from pypdf import PdfReader
    except ImportError:  # dépendance optionnelle absente
        return ""
    try:
        reader = PdfReader(path)
    except Exception:
        logger.warning("PDF illisible pour la génération de QCM : %s", path)
        return ""
    chunks = []
    size = 0
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        text = text.strip()
        if not text:
            continue
        chunks.append(text)
        size += len(text)
        if size >= limit:
            break
    return "\n".join(chunks)[:limit]


def extract_course_text(course):
    """Retourne ``(texte, longueur_totale)`` exploitable par le modèle."""
    parts = []
    if course.description:
        parts.append("Présentation du cours :\n%s" % course.description.strip())

    for chapter in course.chapters.order_by("order", "pk"):
        block = ["Chapitre %s : %s" % (chapter.order, chapter.title)]
        if chapter.summary:
            block.append(chapter.summary.strip())
        parts.append("\n".join(block))

    for material in course.materials.order_by("created_at", "pk"):
        if material.material_type != PDF:
            continue
        try:
            path = material.file.path
        except (NotImplementedError, ValueError, OSError):
            continue
        text = _pdf_text(path)
        if text:
            parts.append(
                "Support « %s » :\n%s"
                % (material.title or material.original_name or "PDF", text)
            )

    full = "\n\n".join(part for part in parts if part).strip()
    return full[:MAX_SOURCE_CHARS], len(full)


# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Tu es un enseignant qui prépare un QCM d'examen à partir du cours fourni. "
    "Rédige uniquement des questions en français, fidèles au contenu du cours, "
    "sans invention ni référence externe. Chaque question possède exactement "
    "quatre propositions et une seule bonne réponse. Évite les formulations "
    "ambiguës, les doublons et les questions dont la réponse est dans l'énoncé. "
    "Réponds UNIQUEMENT avec un objet JSON valide, sans texte ni balise Markdown, "
    "au format exact :\n"
    "{\n"
    '  "questions": [\n'
    "    {\n"
    '      "prompt": "énoncé de la question",\n'
    '      "choices": ["proposition A", "proposition B", "proposition C", "proposition D"],\n'
    '      "correct_index": 0,\n'
    '      "explanation": "justification courte de la bonne réponse"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "correct_index est un entier de 0 à 3 désignant la bonne proposition."
)

_DIFFICULTY_HINTS = {
    "facile": "Questions de compréhension directe et de mémorisation.",
    "moyen": "Questions d'application et de compréhension.",
    "difficile": "Questions d'analyse, de raisonnement et de cas limites.",
}


def _extract_json(content):
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
    if not content.startswith("{"):
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            content = content[start:end + 1]
    return json.loads(content)


def _clean_text(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _validate_questions(raw_questions, *, known_prompts):
    """Filtre les questions invalides ou déjà générées."""
    clean = []
    seen = set(known_prompts)
    for item in raw_questions or []:
        if not isinstance(item, dict):
            continue
        prompt = _clean_text(item.get("prompt"), MAX_QUESTION_CHARS)
        if len(prompt) < 10:
            continue
        signature = prompt.casefold()
        if signature in seen:
            continue

        choices = item.get("choices")
        if not isinstance(choices, list) or len(choices) != CHOICES_PER_QUESTION:
            continue
        labels = [_clean_text(choice, 500) for choice in choices]
        if any(not label for label in labels) or len({label.casefold() for label in labels}) != CHOICES_PER_QUESTION:
            continue

        try:
            correct_index = int(item.get("correct_index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= correct_index < CHOICES_PER_QUESTION:
            continue

        explanation = _clean_text(item.get("explanation"), MAX_EXPLANATION_CHARS)
        seen.add(signature)
        clean.append({
            "prompt": prompt,
            "choices": [
                {"label": label, "is_correct": index == correct_index}
                for index, label in enumerate(labels)
            ],
            "explanation": explanation,
        })
    return clean


def _request_batch(*, source, count, difficulty, known_prompts, timeout=60):
    user_prompt = (
        "Contenu du cours :\n\n%s\n\n"
        "Génère %d questions de difficulté %s. %s\n"
        "Ne répète pas les questions suivantes : %s"
        % (
            source,
            count,
            difficulty,
            _DIFFICULTY_HINTS.get(difficulty, _DIFFICULTY_HINTS["moyen"]),
            json.dumps(list(known_prompts)[:80], ensure_ascii=False) if known_prompts else "aucune",
        )
    )
    payload = {
        "model": _model(),
        "temperature": 0.35,
        "max_tokens": 3000,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    response = requests.post(
        GROQ_CHAT_URL,
        headers={
            "Authorization": "Bearer %s" % _api_key(),
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if response.status_code == 401:
        raise QuizGenerationError("La clé Groq est invalide ou a expiré.")
    if response.status_code == 429:
        raise QuizGenerationError(
            "Le service IA est saturé. Réessayez dans quelques secondes."
        )
    if response.status_code != 200:
        logger.error(
            "Groq quiz generation failed (%s): %s",
            response.status_code, response.text[:300],
        )
        raise QuizGenerationError("Le service IA n'a pas pu générer le QCM.")

    try:
        content = response.json()["choices"][0]["message"]["content"]
        data = _extract_json(content)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise QuizGenerationError("La réponse de l'IA est illisible.") from exc

    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list):
        raise QuizGenerationError("L'IA n'a renvoyé aucune question exploitable.")
    return questions


def generate_quiz_questions(course, count=30, difficulty="moyen"):
    """Génère et valide ``count`` questions pour un cours.

    Retourne ``(questions, metadata)`` où chaque question est un dict prêt à
    être enregistré. Aucune donnée n'est écrite en base ici.
    """
    if not ai_quiz_available():
        raise QuizGenerationError(
            "La clé GROQ_API_KEY n'est pas configurée. Ajoutez-la dans .env "
            "(voir .env.example) puis redémarrez le serveur."
        )
    count = max(1, min(int(count or 1), 100))
    source, source_length = extract_course_text(course)
    if len(source) < 200:
        raise QuizGenerationError(
            "Le cours ne contient pas assez de texte exploitable. Ajoutez une "
            "présentation, des résumés de chapitres ou un PDF avec du texte "
            "(les PDF scannés sans OCR ne sont pas pris en charge)."
        )
    if difficulty not in _DIFFICULTY_HINTS:
        difficulty = "moyen"

    questions = []
    known_prompts = set()
    attempts = 0
    max_attempts = max(2, (count // BATCH_SIZE) + 2)
    while len(questions) < count and attempts < max_attempts:
        attempts += 1
        missing = min(BATCH_SIZE, count - len(questions))
        try:
            batch = _request_batch(
                source=source,
                count=missing,
                difficulty=difficulty,
                known_prompts=known_prompts,
            )
        except requests.RequestException as exc:
            raise QuizGenerationError(
                "Impossible de joindre le service IA. Réessayez dans un instant."
            ) from exc
        except QuizGenerationError:
            if questions:
                break
            raise
        cleaned = _validate_questions(batch, known_prompts=known_prompts)
        if not cleaned:
            continue
        for question in cleaned[: count - len(questions)]:
            questions.append(question)
            known_prompts.add(question["prompt"].casefold())

    if not questions:
        raise QuizGenerationError(
            "L'IA n'a produit aucune question valide. Réessayez ou complétez "
            "le contenu du cours."
        )

    metadata = {
        "model": _model(),
        "source_chars": source_length,
        "requested": count,
        "generated": len(questions),
    }
    return questions, metadata


def save_generated_quiz(quiz, questions, metadata, *, points=None):
    """Remplace les questions du QCM par celles générées.

    Le QCM repasse en brouillon : l'enseignant doit le relire puis le publier.
    """
    from exams.models import QuizChoice, QuizQuestion

    quiz.questions.all().delete()
    for index, item in enumerate(questions, start=1):
        question = QuizQuestion.objects.create(
            quiz=quiz,
            order=index,
            prompt=item["prompt"],
            explanation=item.get("explanation", ""),
            points=points or Decimal("1"),
        )
        QuizChoice.objects.bulk_create([
            QuizChoice(
                question=question,
                order=choice_index,
                label=choice["label"],
                is_correct=choice["is_correct"],
            )
            for choice_index, choice in enumerate(item["choices"], start=1)
        ])
    quiz.question_count = len(questions)
    quiz.generated_by_ai = True
    quiz.ai_model = metadata.get("model", "")
    quiz.source_chars = metadata.get("source_chars", 0)
    quiz.status = quiz.STATUS_DRAFT
    quiz.published_at = None
    quiz.save(update_fields=[
        "question_count", "generated_by_ai", "ai_model", "source_chars",
        "status", "published_at", "updated_at",
    ])
    return quiz
