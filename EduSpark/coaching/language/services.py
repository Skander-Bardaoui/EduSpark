"""Clients serveur des providers voix et LLM du test de langue."""

import json
import logging
import os

import requests
from django.conf import settings

from .config import (
    EXAMS,
    EXERCISE_LABELS_EN,
    LANGUAGES,
    LEVEL_LABELS_EN,
)

logger = logging.getLogger(__name__)

ELEVENLABS_TOKEN_URL = "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

EXAMINER_TEMPERATURE = 0.7
EXAMINER_MAX_TOKENS = 300

EVALUATION_SYSTEM_PROMPT = """You are an experienced IELTS and Cambridge B2 First speaking examiner.
Evaluate the candidate's performance using the official speaking criteria.

Return ONLY a JSON object with exactly this shape:
{
  "overall_level": "B1" | "B2" | "C1",
  "overall_verdict": "Ready" | "Needs Work" | "Not Ready",
  "scores": {
    "fluency": 0-9 integer,
    "vocabulary": 0-9 integer,
    "grammar": 0-9 integer,
    "task_achievement": 0-9 integer
  },
  "notes": {
    "fluency": ["specific observation", ...],
    "vocabulary": ["specific observation", ...],
    "grammar": ["specific observation", ...],
    "task_achievement": ["specific observation", ...]
  },
  "pronunciation_flags": [{"word": "word", "timestamp": 0}],
  "recommendations": ["actionable recommendation", ...]
}

Base every observation on the transcript, quoting the candidate where useful.
Never invent content that the candidate did not say."""


class ProviderError(Exception):
    """Levée quand un provider externe rejette ou échoue."""


def _env(name, default=""):
    """Lit la configuration Django (.env) avec repli sur l'environnement."""
    value = getattr(settings, name, "") or os.environ.get(name, default)
    return str(value or "").strip()


def _groq_model():
    return _env("GROQ_MODEL", "") or "openai/gpt-oss-120b"


def provider_available(name):
    """Vrai si le provider demandé a une clé configurée."""
    return bool(_env("%s_API_KEY" % name))


def _require_key(value, name):
    if not value:
        raise ProviderError(f"{name} n’est pas configuré")
    return value


def _error_detail(response):
    try:
        return response.text[:500]
    except Exception:  # pragma: no cover - défensif
        return f"HTTP {response.status_code}"


def create_realtime_token():
    api_key = _require_key(_env("ELEVENLABS_API_KEY"), "ELEVENLABS_API_KEY")
    try:
        response = requests.post(
            ELEVENLABS_TOKEN_URL,
            headers={"xi-api-key": api_key},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise ProviderError("Impossible de joindre ElevenLabs") from exc

    if response.status_code != 200:
        logger.error(
            "ElevenLabs token failed (%s): %s",
            response.status_code,
            _error_detail(response),
        )
        raise ProviderError("Impossible de démarrer une session de transcription")

    try:
        token = response.json().get("token")
    except ValueError as exc:
        raise ProviderError("ElevenLabs a renvoyé une réponse invalide") from exc

    if not token:
        raise ProviderError("ElevenLabs a renvoyé un jeton vide")
    return token


def stream_examiner_reply(system_prompt, transcript, history):
    api_key = _require_key(_env("GROQ_API_KEY"), "GROQ_API_KEY")
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": transcript})

    payload = {
        "model": _groq_model(),
        "temperature": EXAMINER_TEMPERATURE,
        "max_tokens": EXAMINER_MAX_TOKENS,
        "stream": True,
        "messages": messages,
    }

    try:
        response = requests.post(
            GROQ_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            stream=True,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise ProviderError("Impossible de joindre Groq") from exc

    if response.status_code != 200:
        logger.error(
            "Groq stream failed (%s): %s",
            response.status_code,
            _error_detail(response),
        )
        response.close()
        raise ProviderError("L’examinateur n’a pas répondu")

    def generate():
        try:
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except ValueError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    yield delta
        finally:
            response.close()

    return generate()


def open_tts_stream(text, voice="onyx"):
    api_key = _require_key(_env("OPENAI_API_KEY"), "OPENAI_API_KEY")
    payload = {
        "model": "tts-1",
        "voice": voice,
        "input": text,
        "response_format": "mp3",
    }

    try:
        response = requests.post(
            OPENAI_TTS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            stream=True,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise ProviderError("Impossible de joindre OpenAI") from exc

    if response.status_code != 200:
        logger.error(
            "OpenAI TTS failed (%s): %s",
            response.status_code,
            _error_detail(response),
        )
        response.close()
        if response.status_code == 429:
            raise ProviderError("OpenAI TTS n’a plus de crédits disponibles")
        raise ProviderError("Impossible de générer l’audio de l’examinateur")

    def generate():
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            response.close()

    return generate()


def _transcript_to_text(entries):
    lines = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        speaker = str(entry.get("speaker") or entry.get("role") or "user")
        text = str(entry.get("text") or entry.get("content") or "").strip()
        if not text:
            continue
        label = "Examiner" if speaker in ("assistant", "examiner") else "Candidate"
        timestamp = entry.get("timestamp")
        prefix = f"[{timestamp}] " if timestamp is not None else ""
        lines.append(f"{prefix}{label}: {text}")
    return "\n".join(lines)[:12000]


def _clamp_score(value):
    try:
        return max(0, min(9, int(value)))
    except (TypeError, ValueError):
        return 0


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [
        str(item)
        for item in value
        if isinstance(item, (str, int, float)) and str(item).strip()
    ]


def _normalize_feedback(data, session):
    scores = data.get("scores") or {}
    notes = data.get("notes") or {}

    overall_level = str(data.get("overall_level") or session.level).upper()
    if overall_level not in {"B1", "B2", "C1"}:
        overall_level = session.level.upper()

    verdict = str(data.get("overall_verdict") or "").strip()
    if verdict not in {"Ready", "Needs Work", "Not Ready"}:
        verdict = "Needs Work"

    flags = data.get("pronunciation_flags")
    pronunciation_flags = []
    if isinstance(flags, list):
        for flag in flags[:50]:
            if isinstance(flag, dict) and flag.get("word"):
                pronunciation_flags.append(
                    {
                        "word": str(flag.get("word")),
                        "timestamp": flag.get("timestamp", 0),
                    }
                )

    return {
        "overall_level": overall_level,
        "overall_verdict": verdict,
        "fluency_score": _clamp_score(scores.get("fluency")),
        "vocabulary_score": _clamp_score(scores.get("vocabulary")),
        "grammar_score": _clamp_score(scores.get("grammar")),
        "task_achievement_score": _clamp_score(scores.get("task_achievement")),
        "fluency_notes": _string_list(notes.get("fluency")),
        "vocabulary_notes": _string_list(notes.get("vocabulary")),
        "grammar_notes": _string_list(notes.get("grammar")),
        "task_achievement_notes": _string_list(notes.get("task_achievement")),
        "pronunciation_flags": pronunciation_flags,
        "recommendations": _string_list(data.get("recommendations")),
    }


def evaluate_transcript(session, entries):
    api_key = _require_key(_env("GROQ_API_KEY"), "GROQ_API_KEY")
    transcript_text = _transcript_to_text(entries)
    if not transcript_text:
        raise ProviderError("Aucune transcription à évaluer")

    exam = EXAMS.get(session.exam_type, {})
    language = LANGUAGES.get(session.language, LANGUAGES["en"])
    prompt = (
        f'Exam: {exam.get("name", session.exam_type)}\n'
        f'Target level: {LEVEL_LABELS_EN.get(session.level, session.level)}\n'
        f'Exercise: {EXERCISE_LABELS_EN.get(session.exercise_type, session.exercise_type)}\n'
        f'Exam language: {language["label"]}\n\n'
        f"Transcript:\n{transcript_text}"
    )

    system_prompt = EVALUATION_SYSTEM_PROMPT
    if session.language == "fr":
        system_prompt += (
            "\n\nWrite every observation in the notes and every recommendation in "
            "French. Keep all JSON keys and the allowed enum values (overall_level: "
            "B1/B2/C1; overall_verdict: Ready/Needs Work/Not Ready) exactly as "
            "specified above, in English."
        )

    payload = {
        "model": _groq_model(),
        "temperature": 0.3,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        response = requests.post(
            GROQ_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90,
        )
        if response.status_code == 400:
            # Certains modèles Groq ne supportent pas le mode JSON.
            payload.pop("response_format", None)
            response = requests.post(
                GROQ_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=90,
            )
    except requests.RequestException as exc:
        raise ProviderError("Impossible de joindre Groq") from exc

    if response.status_code != 200:
        logger.error(
            "Groq evaluation failed (%s): %s",
            response.status_code,
            _error_detail(response),
        )
        raise ProviderError("Le bilan n’a pas pu être généré")

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProviderError("Groq a renvoyé une réponse d’évaluation invalide") from exc

    try:
        data = json.loads(content)
    except ValueError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ProviderError("L’évaluation n’était pas un JSON valide")
        try:
            data = json.loads(content[start : end + 1])
        except ValueError as exc:
            raise ProviderError("L’évaluation n’était pas un JSON valide") from exc

    return _normalize_feedback(data, session)
