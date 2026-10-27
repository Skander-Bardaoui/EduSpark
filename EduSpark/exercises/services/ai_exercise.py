"""Génération d'exercices par IA (Groq) pour le module Exercices.

Reproduit le pattern de exams/services/ai_quiz.py : appel Groq,
validation côté serveur, aucune écriture en base ici.
L'enseignant relit toujours l'exercice généré avant de le publier.
"""

import json
import logging
import os
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_QUESTION_CHARS = 1200
MAX_EXPLANATION_CHARS = 800


class ExerciseGenerationError(Exception):
    """La génération a échoué (config, réseau, réponse invalide)."""


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


def ai_exercise_available():
    return bool(_api_key())


_SYSTEM_PROMPTS = {
    "qcm": (
        "Tu es un enseignant qui prépare un QCM. "
        "Chaque question a exactement 4 propositions, une seule correcte. "
        "Réponds UNIQUEMENT avec un JSON valide sans Markdown :\n"
        '{"questions":[{"prompt":"...","choices":["A","B","C","D"],"correct_index":0,"explanation":"..."}]}'
    ),
    "vrai_faux": (
        "Tu es un enseignant qui prépare un exercice Vrai/Faux. "
        "Chaque question a exactement 2 propositions : Vrai et Faux. "
        "Réponds UNIQUEMENT avec un JSON valide sans Markdown :\n"
        '{"questions":[{"prompt":"...","choices":["Vrai","Faux"],"correct_index":0,"explanation":"..."}]}'
    ),
    "trou": (
        "Tu es un enseignant qui prépare un texte à trous. "
        "Chaque question est une phrase avec ___ à compléter, 4 options dont une seule correcte. "
        "Réponds UNIQUEMENT avec un JSON valide sans Markdown :\n"
        '{"questions":[{"prompt":"phrase avec ___ manquant","choices":["A","B","C","D"],"correct_index":0,"explanation":"..."}]}'
    ),
    "probleme": (
        "Tu es un enseignant qui rédige des problèmes ouverts. "
        "Réponds UNIQUEMENT avec un JSON valide sans Markdown :\n"
        '{"questions":[{"prompt":"énoncé du problème...","choices":[],"correct_index":-1,"explanation":"éléments de correction..."}]}'
    ),
}

_DIFFICULTY_HINTS = {
    "facile": "Questions de niveau débutant, compréhension directe.",
    "moyen": "Questions d'application et de compréhension intermédiaire.",
    "difficile": "Questions d'analyse, raisonnement et cas limites.",
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


def _validate_questions(raw_questions, exercise_type, *, known_prompts):
    clean = []
    seen = set(known_prompts)
    expected = {"qcm": 4, "vrai_faux": 2, "trou": 4, "probleme": 0}.get(exercise_type, 4)

    for item in raw_questions or []:
        if not isinstance(item, dict):
            continue
        prompt = _clean_text(item.get("prompt"), MAX_QUESTION_CHARS)
        if len(prompt) < 10:
            continue
        sig = prompt.casefold()
        if sig in seen:
            continue

        choices_raw = item.get("choices") or []
        if exercise_type == "probleme":
            choices_data = []
            correct_index = -1
        else:
            if not isinstance(choices_raw, list) or len(choices_raw) != expected:
                continue
            labels = [_clean_text(c, 500) for c in choices_raw]
            if any(not l for l in labels):
                continue
            try:
                correct_index = int(item.get("correct_index", 0))
            except (TypeError, ValueError):
                correct_index = 0
            if not (0 <= correct_index < expected):
                correct_index = 0
            choices_data = [
                {"label": lbl, "is_correct": idx == correct_index}
                for idx, lbl in enumerate(labels)
            ]

        explanation = _clean_text(item.get("explanation"), MAX_EXPLANATION_CHARS)
        seen.add(sig)
        clean.append({
            "prompt": prompt,
            "choices": choices_data,
            "correct_index": correct_index,
            "explanation": explanation,
        })
    return clean


def _request_batch(*, subject, topic, count, difficulty, exercise_type, known_prompts, timeout=60):
    system_prompt = _SYSTEM_PROMPTS.get(exercise_type, _SYSTEM_PROMPTS["qcm"])
    diff_hint = _DIFFICULTY_HINTS.get(difficulty, _DIFFICULTY_HINTS["moyen"])

    user_prompt = (
        "Matière : {subject}\nSujet : {topic}\n\n"
        "Génère {count} question(s) de type {etype}, difficulté {diff}.\n{hint}\n"
        "Ne répète pas : {known}"
    ).format(
        subject=subject, topic=topic, count=count, etype=exercise_type,
        diff=difficulty, hint=diff_hint,
        known=json.dumps(list(known_prompts)[:40], ensure_ascii=False) if known_prompts else "aucune",
    )

    payload = {
        "model": _model(),
        "temperature": 0.40,
        "max_tokens": 3000,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = requests.post(
        GROQ_CHAT_URL,
        headers={"Authorization": "Bearer %s" % _api_key(), "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if resp.status_code == 401:
        raise ExerciseGenerationError("Clé Groq invalide ou expirée.")
    if resp.status_code == 429:
        raise ExerciseGenerationError("Service IA saturé. Réessayez dans quelques secondes.")
    if resp.status_code != 200:
        logger.error("Groq error (%s): %s", resp.status_code, resp.text[:300])
        raise ExerciseGenerationError("Le service IA n'a pas pu générer l'exercice.")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
        data = _extract_json(content)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ExerciseGenerationError("Réponse IA illisible.") from exc

    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list):
        raise ExerciseGenerationError("L'IA n'a renvoyé aucune question.")
    return questions


def generate_exercise_questions(subject, topic, exercise_type="qcm", difficulty="moyen", count=5):
    """Génère et valide ``count`` questions. Retourne (questions, metadata)."""
    if not ai_exercise_available():
        raise ExerciseGenerationError(
            "GROQ_API_KEY non configurée. Ajoutez-la dans .env puis redémarrez."
        )
    count = max(1, min(int(count or 1), 20))
    if difficulty not in _DIFFICULTY_HINTS:
        difficulty = "moyen"
    if exercise_type not in _SYSTEM_PROMPTS:
        exercise_type = "qcm"

    questions = []
    known_prompts = set()
    attempts = 0
    max_attempts = max(2, count + 1)

    while len(questions) < count and attempts < max_attempts:
        attempts += 1
        missing = count - len(questions)
        try:
            batch = _request_batch(
                subject=subject, topic=topic, count=missing,
                difficulty=difficulty, exercise_type=exercise_type,
                known_prompts=known_prompts,
            )
        except requests.RequestException as exc:
            raise ExerciseGenerationError("Impossible de joindre l'IA. Réessayez.") from exc
        except ExerciseGenerationError:
            if questions:
                break
            raise
        cleaned = _validate_questions(batch, exercise_type, known_prompts=known_prompts)
        if not cleaned:
            continue
        for q in cleaned[: count - len(questions)]:
            questions.append(q)
            known_prompts.add(q["prompt"].casefold())

    if not questions:
        raise ExerciseGenerationError("L'IA n'a produit aucune question valide. Réessayez.")

    return questions, {
        "model": _model(), "subject": subject, "topic": topic,
        "exercise_type": exercise_type, "difficulty": difficulty,
        "requested": count, "generated": len(questions),
    }


def save_generated_questions(exercise, questions):
    """Enregistre les questions en base et met l'exercice en brouillon IA."""
    from exercises.models import Choice, Question

    exercise.questions.all().delete()

    for idx, item in enumerate(questions, start=1):
        n = len(item["choices"])
        if n == 4:
            q_type = "qcm"
        elif n == 2:
            q_type = "vrai_faux"
        else:
            q_type = "ouverte"

        question = Question.objects.create(
            exercise=exercise,
            order=idx,
            question_type=q_type,
            text=item["prompt"],
            points=1,
            explanation=item.get("explanation", ""),
        )
        for i, choice_data in enumerate(item.get("choices", []), start=1):
            Choice.objects.create(
                question=question,
                text=choice_data["label"],
                is_correct=choice_data["is_correct"],
                order=i,
            )

    exercise.ai_generated = True
    exercise.ai_validated = False
    exercise.status = "brouillon"
    exercise.save(update_fields=["ai_generated", "ai_validated", "status", "updated_at"])
