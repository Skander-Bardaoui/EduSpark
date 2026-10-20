"""Unique point d'appel à l'IA du module users : génération d'une bio de profil.

Le reste du module ne dépend jamais de ce fichier pour fonctionner : toute
erreur (clé absente, SDK non installé, réseau, quota, refus…) est convertie
en AIUnavailable, que la vue affiche comme un simple message.

Configuration (.env) :
    ANTHROPIC_API_KEY   clé de l'API Claude (sans clé : IA désactivée)
    EDUSPARK_AI_MODEL   modèle (défaut : claude-opus-5-5)
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = (
    "Tu rédiges des présentations de profil pour une plateforme universitaire "
    "francophone. Écris en français, à la première personne, sur un ton "
    "professionnel et chaleureux, en 3 à 5 phrases (90 mots maximum). "
    "N'invente aucun fait, diplôme, chiffre ou établissement qui ne figure pas "
    "dans les informations fournies. Réponds uniquement avec le texte de la "
    "présentation, sans titre, sans guillemets ni mise en forme Markdown."
)


class AIUnavailable(Exception):
    """L'IA ne peut pas répondre ; le message est affichable tel quel."""


def _client():
    try:
        import anthropic
    except Exception as exc:  # SDK absent ou installation cassée
        raise AIUnavailable("Le service d'IA n'est pas installé sur ce serveur.") from exc
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        raise AIUnavailable("L'assistant IA n'est pas configuré (clé API absente).")
    try:
        return anthropic, anthropic.Anthropic(timeout=45.0, max_retries=1)
    except Exception as exc:  # configuration invalide (URL, proxy, version du SDK…)
        logger.exception("IA : initialisation du client impossible")
        raise AIUnavailable("L'assistant IA ne peut pas démarrer sur ce serveur.") from exc


def _profile_facts(user, university=None, role_label="", extra=None, draft=""):
    lines = [f"Nom : {user.get_full_name() or user.email}"]
    if role_label:
        lines.append(f"Rôle : {role_label}")
    if university is not None:
        lines.append(f"Université : {university.name}")
    for label, value in (extra or {}).items():
        if value:
            lines.append(f"{label} : {value}")
    if draft.strip():
        lines.append(f"Brouillon ou mots-clés fournis par l'utilisateur : {draft.strip()}")
    return "\n".join(lines)


def generate_profile_bio(user, university=None, role_label="", extra=None, draft=""):
    """Retourne une suggestion de bio (str).

    Ne lève jamais autre chose que AIUnavailable : quelle que soit la panne
    (initialisation, réseau, API, réponse inattendue), la page appelante
    affiche un message et le reste du module continue de fonctionner.
    """
    anthropic, client = _client()
    facts = _profile_facts(user, university, role_label, extra, draft)
    try:
        response = client.beta.messages.create(
            model=os.environ.get("EDUSPARK_AI_MODEL", DEFAULT_MODEL),
            max_tokens=4000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Rédige la présentation de profil à partir de ces informations :\n\n{facts}",
            }],
        )
        if response.stop_reason == "refusal":
            raise AIUnavailable("L'assistant IA n'a pas pu générer de présentation pour ce profil.")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
    except AIUnavailable:
        raise
    except anthropic.AuthenticationError as exc:
        logger.warning("IA : clé API refusée (%s)", exc)
        raise AIUnavailable("L'assistant IA est mal configuré (clé API refusée).") from exc
    except anthropic.RateLimitError as exc:
        raise AIUnavailable("L'assistant IA est très sollicité, réessayez dans un instant.") from exc
    except anthropic.APIStatusError as exc:
        logger.warning("IA : erreur API %s (%s)", exc.status_code, exc)
        raise AIUnavailable("L'assistant IA est momentanément indisponible.") from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("IA : connexion impossible (%s)", exc)
        raise AIUnavailable("Impossible de joindre l'assistant IA (réseau).") from exc
    except Exception as exc:  # garde-fou : une panne de l'IA ne doit jamais casser la page
        logger.exception("IA : erreur inattendue")
        raise AIUnavailable("L'assistant IA a rencontré une erreur inattendue.") from exc

    if not text:
        raise AIUnavailable("L'assistant IA n'a renvoyé aucun texte. Réessayez.")
    return text
