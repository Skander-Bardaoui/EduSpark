"""Assistant « Suggérer une réponse » : seul appel IA du module community.

Même fournisseur que le module coaching (Groq, clé GROQ_API_KEY dans .env).
Le texte renvoyé n'est qu'un brouillon : la vue le met dans le champ de
réponse, que la personne relit et modifie avant de publier. Si l'IA est
indisponible, `AIUnavailable` est levée et le reste du module continue de
fonctionner.
"""

import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_QUESTION_CHARS = 3000
MAX_CONTEXT_REPLIES = 5
MAX_REPLY_CHARS = 800
MAX_ANSWER_CHARS = 4000

SYSTEM_PROMPT = (
    "Tu es l'assistant pédagogique d'un forum universitaire. Un étudiant a posé une question ; "
    "tu rédiges un brouillon de réponse en français que le professeur ou un étudiant relira, "
    "corrigera puis publiera. Sois clair, bienveillant et concis (150 mots maximum). "
    "Explique la démarche plutôt que de donner uniquement le résultat. Si la question manque de "
    "précisions ou dépend du cours de l'enseignant que tu ne connais pas, dis-le et indique ce qu'il "
    "faut vérifier ; n'invente jamais de références, de notes ou de consignes d'examen. "
    "Ne réponds qu'avec le texte de la réponse, sans titre ni introduction. Écris en texte brut : "
    "pas de Markdown (ni **, ni #, ni puces à tirets complexes) et pas de LaTeX ; note les formules "
    "simplement, par exemple u(n+1) <= M."
)


class AIUnavailable(Exception):
    """L'IA ne peut pas répondre (pas de clé, réseau, quota, réponse vide)."""


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def build_messages(thread, replies):
    """Messages envoyés au modèle : la question, puis les réponses déjà publiées."""
    forum = thread.forum
    context = [f"Forum : {forum.title}"]
    if forum.course_ref:
        context.append(f"Cours : {forum.course_ref}")
    context.append(f"Sujet : {thread.title}")
    context.append(f"Question de l'étudiant :\n{thread.body[:MAX_QUESTION_CHARS]}")

    previous = [r for r in replies if not r.is_hidden][:MAX_CONTEXT_REPLIES]
    if previous:
        lines = [f"- {r.body[:MAX_REPLY_CHARS]}" for r in previous]
        context.append("Réponses déjà publiées (ne pas les répéter, les compléter si utile) :\n" + "\n".join(lines))

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(context)},
    ]


def clean_answer(text):
    """Retire les blocs de raisonnement éventuels et borne la longueur."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    return text[:MAX_ANSWER_CHARS]


def suggest_reply(thread, replies=()):
    api_key = _env("GROQ_API_KEY")
    if not api_key:
        raise AIUnavailable("GROQ_API_KEY n'est pas configurée.")

    payload = {
        "model": _env("GROQ_MODEL", "qwen/qwen3.8-27b"),
        "temperature": 0.4,
        "max_tokens": 700,
        "messages": build_messages(thread, list(replies)),
    }
    try:
        response = requests.post(
            GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise AIUnavailable("Impossible de joindre le service d'IA.") from exc

    if response.status_code != 200:
        logger.error("Groq suggestion failed (%s): %s", response.status_code, response.text[:300])
        raise AIUnavailable("Le service d'IA a refusé la demande.")

    try:
        answer = clean_answer(response.json()["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIUnavailable("Réponse du service d'IA illisible.") from exc
    if not answer:
        raise AIUnavailable("Le service d'IA n'a renvoyé aucun texte.")
    return answer
