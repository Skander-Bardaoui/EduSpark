"""Métriques d'évaluation du plan de cours IA (fonctions pures, testées).

Le pipeline est génératif : pas de matrice de confusion ni de classes. On
mesure donc ce qui fait la qualité d'un plan pour un professeur :

Lecteur local (thèmes extraits des supports)
  * précision : part des thèmes réellement ancrés dans le texte du support
    (au moins un mot significatif du thème présent dans le document) ;
  * rappel : part des notions de référence (annotées à la main) retrouvées ;
  * F1 : moyenne harmonique des deux ;
  * conformité de langue : part des thèmes écrits dans la langue demandée.

Rédacteur (plan JSON)
  * validité du JSON au premier essai (schéma strict) ;
  * respect du nombre de chapitres demandé ;
  * écart relatif entre le volume horaire obtenu et demandé ;
  * part des chapitres ayant 2 à 4 objectifs.

Performance : latence moyenne, médiane (p50) et p95 de chaque étape.
"""

import math
import re
import unicodedata

from . import ai

STOPWORDS = {
    "les", "des", "une", "aux", "pour", "avec", "dans", "sur", "par", "and", "the", "for", "with",
    "of", "de", "du", "la", "le", "et", "en", "à", "au", "d", "l", "un", "into", "from",
}
ARABIC_RE = re.compile(r"[؀-ۿ]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ÿ]")


def normalize(text):
    """Minuscules sans accents ni ponctuation, pour comparer des notions."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def significant_words(text):
    return [word for word in normalize(text).split() if len(word) > 3 and word not in STOPWORDS]


def _stem(word):
    """Racine grossière (pluriels, accords) : « graphes » et « graphe » se rejoignent."""
    if len(word) > 4 and word[-1] in "sx":
        word = word[:-1]
    return word[:6]


def is_grounded(topic, source_text):
    """Vrai si au moins un mot significatif du thème figure dans le texte source."""
    source = {_stem(word) for word in significant_words(source_text)}
    words = significant_words(topic)
    return bool(words) and any(_stem(word) in source for word in words)


def keyword_found(keyword, topics):
    target = [_stem(word) for word in normalize(keyword).split() if len(word) > 2]
    haystack = {_stem(word) for topic in topics for word in normalize(topic).split()}
    return bool(target) and all(stem in haystack for stem in target)


def topic_precision(topics, source_text):
    if not topics:
        return 0.0
    return sum(is_grounded(topic, source_text) for topic in topics) / len(topics)


def topic_recall(topics, keywords):
    if not keywords:
        return None  # pas de référence annotée pour ce cas
    return sum(keyword_found(keyword, topics) for keyword in keywords) / len(keywords)


def f1(precision, recall):
    """Moyenne harmonique ; ``None`` si l'une des deux mesures manque."""
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def in_language(topic, language):
    """Thème écrit dans l'alphabet de la langue demandée, sans idéogrammes CJK."""
    if ai.CJK_RE.search(topic):
        return False
    if language == "ar":
        return bool(ARABIC_RE.search(topic))
    return bool(LATIN_RE.search(topic)) and not ARABIC_RE.search(topic)


def language_compliance(topics, language):
    if not topics:
        return 0.0
    return sum(in_language(topic, language) for topic in topics) / len(topics)


def syllabus_checks(chapters, options):
    """Respect des consignes par un plan validé (liste de chapitres)."""
    requested_count = options.get("chapter_count")
    requested_hours = options.get("total_hours")
    hours = sum(chapter["duration_hours"] for chapter in chapters)
    return {
        "chapter_count_ok": requested_count is None or len(chapters) == requested_count,
        "hours_error": abs(hours - requested_hours) / requested_hours if requested_hours else None,
        "objectives_ok": (
            sum(2 <= len(chapter["objectives"]) <= 4 for chapter in chapters) / len(chapters)
            if chapters else 0.0
        ),
    }


def percentile(values, rank):
    """Percentile (méthode du rang le plus proche) ; ``None`` pour une liste vide."""
    values = sorted(values)
    if not values:
        return None
    index = max(0, math.ceil(rank / 100 * len(values)) - 1)
    return values[index]


def latency_summary(values):
    values = [value for value in values if value is not None]
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values),
    }


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def rate(flags):
    flags = list(flags)
    return sum(1 for flag in flags if flag) / len(flags) if flags else None
