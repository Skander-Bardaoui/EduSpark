"""Les deux fonctions IA du parcours QCM : feedback étudiant et analyse prof.

Les appels Groq sont optionnels : sans clé configurée, ou en cas d'erreur
réseau, un diagnostic local déterministe est produit. L'interface reste donc
toujours utilisable, et les résultats sont mis en cache sur le modèle.
"""

import logging

import requests
from django.conf import settings
from django.utils import timezone

from .ai_quiz import _extract_json, ai_quiz_available

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"


def _model():
    return (
        getattr(settings, "GROQ_MODEL", "")
        or DEFAULT_MODEL
    ).strip()


def _api_key():
    return (getattr(settings, "GROQ_API_KEY", "") or "").strip()


def _clean_list(values, limit=4):
    cleaned = []
    for value in values or []:
        text = " ".join(str(value or "").split()).strip()
        if text and text not in cleaned:
            cleaned.append(text[:280])
        if len(cleaned) >= limit:
            break
    return cleaned


def _request_json(system_prompt, user_prompt, timeout=45):
    response = requests.post(
        GROQ_CHAT_URL,
        headers={
            "Authorization": "Bearer %s" % _api_key(),
            "Content-Type": "application/json",
        },
        json={
            "model": _model(),
            "temperature": 0.2,
            "max_tokens": 1200,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError("Groq a répondu %s" % response.status_code)
    content = response.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def _student_rows(attempt):
    answers = {
        answer.question_id: answer
        for answer in attempt.answers.select_related("selected_choice", "question")
    }
    rows = []
    for question in attempt.quiz.questions.prefetch_related("choices").order_by("order", "pk"):
        answer = answers.get(question.pk)
        selected = answer.selected_choice if answer else None
        correct = question.correct_choices.first()
        rows.append({
            "question": question,
            "selected": selected,
            "correct": correct,
            "is_correct": bool(selected and selected.is_correct),
        })
    return rows


def _local_student_feedback(attempt, rows):
    correct = sum(1 for row in rows if row["is_correct"])
    total = len(rows)
    wrong = [row["question"].prompt for row in rows if not row["is_correct"]]
    score = attempt.score_20
    if score is None:
        summary = "Votre tentative n'a pas pu être notée."
    elif score >= 16:
        summary = "Très bon résultat : la maîtrise du cours est solide."
    elif score >= 10:
        summary = "Résultat correct : les bases sont acquises, quelques notions restent à consolider."
    else:
        summary = "Les bases doivent être retravaillées avant de progresser sur ce chapitre."
    strengths = []
    if correct:
        strengths.append(
            "%s bonne(s) réponse(s) sur %s question(s)." % (correct, total)
        )
    if score is not None and score >= attempt.quiz.pass_score:
        strengths.append("Le seuil de validation du QCM est atteint.")
    focus = [
        "Revoir : %s" % prompt[:180]
        for prompt in wrong[:3]
    ] or ["Aucune difficulté majeure détectée sur ce QCM."]
    next_steps = [
        "Relisez les explications des questions manquées.",
        "Reprenez le chapitre correspondant puis refaites le QCM d'entraînement.",
    ]
    if score is not None and score < 10:
        next_steps.insert(0, "Travaillez en priorité les notions des questions échouées.")
    return {
        "source": "local",
        "summary": summary,
        "strengths": strengths or ["Participation au QCM enregistrée."],
        "focus": focus,
        "next_steps": next_steps,
    }


def generate_student_feedback(attempt, *, force=False):
    """Produit et enregistre un feedback personnalisé pour une tentative."""
    if attempt.ai_feedback and not force:
        return attempt.ai_feedback

    rows = _student_rows(attempt)
    feedback = None
    if ai_quiz_available():
        payload = {
            "quiz": attempt.quiz.session.title,
            "score_20": float(attempt.score_20 or 0),
            "pass_score": float(attempt.quiz.pass_score),
            "questions": [
                {
                    "prompt": row["question"].prompt,
                    "correct": row["is_correct"],
                    "selected": row["selected"].label if row["selected"] else None,
                    "expected": row["correct"].label if row["correct"] else None,
                }
                for row in rows
            ],
        }
        try:
            data = _request_json(
                "Tu es un tuteur pédagogique. Réponds uniquement en JSON valide, "
                "sans Markdown, avec les clés summary (texte), strengths (liste), "
                "focus (liste), next_steps (liste). Sois bienveillant, précis et "
                "fidèle aux réponses de l'étudiant. N'invente aucun contenu.",
                "Analyse cette tentative de QCM et propose un feedback en français :\n%s"
                % payload,
            )
            feedback = {
                "source": "ia",
                "summary": " ".join(str(data.get("summary") or "").split())[:600],
                "strengths": _clean_list(data.get("strengths")),
                "focus": _clean_list(data.get("focus")),
                "next_steps": _clean_list(data.get("next_steps")),
            }
            if not feedback["summary"]:
                feedback = None
        except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Feedback IA indisponible : %s", exc)
    if feedback is None:
        feedback = _local_student_feedback(attempt, rows)

    attempt.ai_feedback = feedback
    attempt.ai_feedback_at = timezone.now()
    attempt.save(update_fields=["ai_feedback", "ai_feedback_at", "updated_at"])
    return feedback


def _question_stats(quiz, attempts):
    submitted = [attempt for attempt in attempts if attempt.is_submitted and not attempt.is_absent]
    answered = {
        answer.question_id: answer
        for attempt in submitted
        for answer in attempt.answers.select_related("selected_choice")
    }
    stats = []
    for question in quiz.questions.prefetch_related("choices").order_by("order", "pk"):
        attempt_ids = {attempt.pk for attempt in submitted}
        correct = sum(
            1 for attempt in submitted
            for answer in [attempt.answers.filter(question=question).first()]
            if answer and answer.selected_choice_id
            and answer.selected_choice.is_correct
        )
        stats.append({
            "question": question,
            "correct": correct,
            "total": len(attempt_ids),
            "rate": round(correct * 100 / len(attempt_ids)) if attempt_ids else 0,
        })
    return stats


def _local_quiz_analysis(quiz, attempts, stats):
    submitted = [attempt for attempt in attempts if attempt.is_submitted and not attempt.is_absent]
    absent = sum(1 for attempt in attempts if attempt.is_absent)
    scores = [attempt.score_20 for attempt in submitted if attempt.score_20 is not None]
    average = (sum(scores) / len(scores)) if scores else None
    passed = sum(1 for attempt in submitted if attempt.passed)
    issues = [
        "Q%d : seulement %s %% de réussite (%s/%s)."
        % (item["question"].order, item["rate"], item["correct"], item["total"])
        for item in stats if item["total"] and item["rate"] < 50
    ]
    if not issues and stats:
        issues = ["Aucune question ne descend sous 50 % de réussite."]
    recommendations = []
    if absent:
        recommendations.append(
            "Relancer ou accompagner les %s étudiant(s) absent(s)." % absent
        )
    if average is not None and average < quiz.pass_score:
        recommendations.append(
            "La moyenne est sous le seuil de validation : revoir les notions clés en cours."
        )
    if issues and stats:
        recommendations.append(
            "Retravailler en priorité les questions les moins réussies avant la prochaine évaluation."
        )
    if not recommendations:
        recommendations.append(
            "Les résultats sont homogènes : conserver ce niveau d'exigence."
        )
    return {
        "source": "local",
        "summary": (
            "Analyse de %s tentative(s) : moyenne %s/20, %s réussite(s), %s absent(s)."
            % (len(submitted), _format(average), passed, absent)
        ),
        "difficulty": "élevée" if average is not None and average < 10 else "maîtrisée",
        "issues": issues[:5],
        "recommendations": recommendations[:5],
    }


def _format(value):
    if value is None:
        return "—"
    return ("%.1f" % value).replace(".", ",")


def generate_quiz_analysis(quiz, attempts, *, force=False):
    """Produit et enregistre l'analyse pédagogique d'un QCM."""
    if quiz.ai_analysis and not force:
        return quiz.ai_analysis

    attempts = list(attempts)
    stats = _question_stats(quiz, attempts)
    analysis = None
    if ai_quiz_available():
        payload = {
            "quiz": quiz.session.title,
            "pass_score": float(quiz.pass_score),
            "attempts": [
                {
                    "score_20": float(attempt.score_20 or 0),
                    "passed": attempt.passed,
                    "absent": attempt.is_absent,
                }
                for attempt in attempts
            ],
            "questions": [
                {
                    "order": item["question"].order,
                    "prompt": item["question"].prompt,
                    "rate": item["rate"],
                    "correct": item["correct"],
                    "total": item["total"],
                }
                for item in stats
            ],
        }
        try:
            data = _request_json(
                "Tu es un ingénieur pédagogique. Réponds uniquement en JSON valide, "
                "sans Markdown, avec les clés summary (texte), difficulty (texte), "
                "issues (liste), recommendations (liste). Appuie-toi uniquement sur "
                "les statistiques fournies et reste concis.",
                "Analyse ce QCM et propose des actions concrètes en français :\n%s"
                % payload,
            )
            analysis = {
                "source": "ia",
                "summary": " ".join(str(data.get("summary") or "").split())[:700],
                "difficulty": " ".join(str(data.get("difficulty") or "").split())[:120],
                "issues": _clean_list(data.get("issues"), limit=5),
                "recommendations": _clean_list(data.get("recommendations"), limit=5),
            }
            if not analysis["summary"]:
                analysis = None
        except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Analyse IA indisponible : %s", exc)
    if analysis is None:
        analysis = _local_quiz_analysis(quiz, attempts, stats)

    quiz.ai_analysis = analysis
    quiz.ai_analysis_at = timezone.now()
    quiz.save(update_fields=["ai_analysis", "ai_analysis_at", "updated_at"])
    return analysis
