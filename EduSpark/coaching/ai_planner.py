"""Génération de plannings d'étude avec Groq."""

import json
import os
from datetime import datetime

import requests
from django.conf import settings
from django.utils import timezone

from .services import next_exam, student_week_hours
from .utils import fr_date_cap, week_bounds

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"


class AIPlanError(Exception):
    """Erreur de génération du plan d'étude."""


def _api_key():
    return (getattr(settings, "GROQ_API_KEY", "") or os.environ.get("GROQ_API_KEY", "")).strip()


def _model():
    return (
        getattr(settings, "GROQ_MODEL", "")
        or os.environ.get("GROQ_MODEL", "")
        or DEFAULT_MODEL
    ).strip()


def ai_planner_available():
    """Indique si le plan d'étude IA peut réellement appeler Groq."""
    return bool(_api_key())


def _student_context(student, goal_id=None, weekly_hours=15, priority="deadlines"):
    goals = list(student.goals.all())
    selected_goal = None
    if goal_id:
        selected_goal = next((goal for goal in goals if goal.pk == goal_id), None)

    goal_rows = [
        {
            "id": goal.pk,
            "titre": goal.title,
            "progression": goal.progress,
            "statut": goal.get_status_display(),
            "echeance": goal.target_date.isoformat() if goal.target_date else None,
            "competences": "%d/%d" % (goal.skills_acquired, goal.skills_total),
        }
        for goal in goals
        if goal.status != goal.STATUS_ACHIEVED
    ]
    if selected_goal:
        goal_rows = [row for row in goal_rows if row["id"] == selected_goal.pk]
    task_rows = [
        {
            "titre": task.title,
            "contexte": task.context_label,
            "horizon": task.get_horizon_display(),
            "priorite": task.get_priority_display(),
            "echeance": task.due_at.isoformat() if task.due_at else None,
        }
        for task in student.tasks.filter(is_done=False)[:20]
    ]
    exam = next_exam(student)
    completed, planned, sessions = student_week_hours(student)
    session_rows = [
        {
            "titre": session.title,
            "debut": timezone.localtime(session.starts_at).isoformat()
            if timezone.is_aware(session.starts_at) else session.starts_at.isoformat(),
            "duree_minutes": session.duration_minutes,
        }
        for session in sessions[:10]
    ]
    start, end = week_bounds()
    return {
        "etudiant": student.membership.user.get_full_name()
        or student.membership.user.email,
        "filiere": student.program,
        "semaine": {"debut": start.isoformat(), "fin": end.isoformat()},
        "aujourd_hui": timezone.localdate().isoformat(),
        "heure_actuelle": timezone.localtime().strftime("%H:%M"),
        "objectif_selectionne": (
            selected_goal.title if selected_goal else "Tous les objectifs actifs"
        ),
        "objectifs": goal_rows,
        "taches": task_rows,
        "examen": (
            {
                "titre": exam.title,
                "date": timezone.localtime(exam.starts_at).isoformat()
                if timezone.is_aware(exam.starts_at) else exam.starts_at.isoformat(),
                "code": exam.course_code,
            }
            if exam else None
        ),
        "sessions_existantes": session_rows,
        "heures_completees": round(completed / 60, 1),
        "heures_planifiees": round(planned / 60, 1),
        "disponibilite_hebdo": weekly_hours,
        "strategie": priority,
    }


def generate_study_plan(student, goal_id=None, weekly_hours=15, priority="deadlines"):
    api_key = _api_key()
    if not api_key:
        raise AIPlanError(
            "La clé GROQ_API_KEY n'est pas configurée. Ajoutez-la dans EduSpark/.env "
            "(voir .env.example) puis redémarrez le serveur."
        )

    context = _student_context(
        student, goal_id=goal_id, weekly_hours=weekly_hours, priority=priority,
    )
    start, end = week_bounds()
    today = timezone.localdate()
    planning_start = max(start, today)
    system_prompt = (
        "Tu es un coach pédagogique expert. Tu construis un planning de révision "
        "réaliste, personnalisé et sans surcharge. Réponds UNIQUEMENT avec un objet "
        "JSON valide, sans texte ni balises Markdown, au format exact :\n"
        "{\n"
        '  "resume": "2 phrases maximum",\n'
        '  "viabilite": 0-100,\n'
        '  "blocs": [\n'
        '    {"jour": "AAAA-MM-JJ", "debut": "HH:MM", "duree_minutes": 30-180, '
        '"titre": "action concrète", "code_ue": "optionnel", "raison": "pourquoi"}\n'
        "  ]\n"
        "}\n"
        f"Place les blocs entre le {planning_start.isoformat()} et le {end.isoformat()}. "
        f"Il est actuellement {context['heure_actuelle']} : pour aujourd'hui, ne propose "
        "que des horaires postérieurs à cette heure. "
        "Ne dépasse pas la disponibilité hebdomadaire indiquée. Évite de dupliquer "
        "les sessions déjà planifiées. Maximum 8 blocs. Utilise des titres en français."
    )
    user_prompt = "Contexte de l'étudiant :\n" + json.dumps(
        context, ensure_ascii=False, indent=2,
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
                "temperature": 0.35,
                "max_tokens": 3200,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        raise AIPlanError("Impossible de joindre Groq. Réessayez dans un instant.") from exc

    if response.status_code == 401:
        raise AIPlanError("La clé Groq est invalide ou a expiré.")
    if response.status_code == 429:
        raise AIPlanError("Le service IA est saturé. Réessayez dans quelques secondes.")
    if response.status_code != 200:
        raise AIPlanError("Le service IA n'a pas pu générer de planning.")

    try:
        content = response.json()["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIPlanError("La réponse de l'IA est illisible.") from exc

    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
    if not content.startswith("{"):
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            content = content[first_brace:last_brace + 1]
    try:
        plan = json.loads(content)
    except ValueError as exc:
        raise AIPlanError("L'IA a renvoyé une réponse invalide.") from exc

    blocks = plan.get("blocs")
    if not isinstance(blocks, list) or not blocks:
        raise AIPlanError("L'IA n'a proposé aucun bloc de travail.")

    clean_blocks = []
    for block in blocks[:8]:
        if not isinstance(block, dict):
            continue
        try:
            day = datetime.strptime(str(block.get("jour", "")), "%Y-%m-%d").date()
            clock = datetime.strptime(str(block.get("debut", "")), "%H:%M").time()
            duration = max(30, min(180, int(block.get("duree_minutes", 60))))
        except (TypeError, ValueError):
            continue
        if day < planning_start or day > end:
            continue
        clean_blocks.append({
            "jour": day.isoformat(),
            "debut": clock.strftime("%H:%M"),
            "duree_minutes": duration,
            "titre": str(block.get("titre") or "Session de révision")[:200],
            "code_ue": str(block.get("code_ue") or "")[:20],
            "raison": str(block.get("raison") or "")[:300],
        })

    if not clean_blocks:
        raise AIPlanError("Aucun bloc valide n'a été proposé. Réessayez.")

    try:
        viability = max(0, min(100, int(plan.get("viabilite", 85))))
    except (TypeError, ValueError):
        viability = 85

    return {
        "resume": str(plan.get("resume") or "Planning adapté à votre semaine.")[:500],
        "viabilite": viability,
        "blocs": clean_blocks,
        "semaine": {
            "debut": fr_date_cap(start),
            "fin": fr_date_cap(end),
        },
    }
