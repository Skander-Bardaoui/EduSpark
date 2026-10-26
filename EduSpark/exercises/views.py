"""
Vues du module Exercices.

Toutes les vues sont protégées par @role_required (ou @tenant_required pour
les vues multi-universités). Le design des templates est strictement préservé :
on passe uniquement des variables de contexte supplémentaires.
"""
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import Profil
from accounts.tenancy import Role, tenant_required

from .forms import (
    AIGenerateForm,
    AssignmentForm,
    CategoryForm,
    ExerciseForm,
    ExerciseSeriesForm,
    RubricForm,
    CriterionFormSet,
)
from .models import (
    Assignment,
    AssignmentExercise,
    Category,
    Exercise,
    ExerciseSeries,
    PracticeAttempt,
    Rubric,
    SeriesItem,
    StudentSubmission,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def _university(request):
    """Retourne l'université courante (depuis le tenant middleware)."""
    return getattr(request, "university", None)


# ---------------------------------------------------------------------------
# PORTAIL ÉTUDIANT
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_ETUDIANT)
def student_assignments(request):
    """Mes devoirs — liste des devoirs assignés à l'étudiant."""
    university = _university(request)
    user = request.user

    open_assignments = []
    past_with_sub = []
    submissions_by_assignment = {}

    if university:
        # All active assignments in this university
        assignments_qs = Assignment.objects.filter(
            university=university,
            status__in=["ouvert", "correction"],
        ).select_related("rubric").order_by("deadline")

        # All completed assignments
        past_qs = Assignment.objects.filter(
            university=university,
            status="termine",
        ).select_related("rubric").order_by("-deadline")

        # This student's submissions
        my_submissions = StudentSubmission.objects.filter(
            student=user,
            assignment__university=university,
        ).select_related("assignment")
        submissions_by_assignment = {s.assignment_id: s for s in my_submissions}

        now = timezone.now()
        for a in assignments_qs:
            sub = submissions_by_assignment.get(a.pk)
            days_left = (a.deadline - now).days if a.deadline else None
            open_assignments.append({
                "assignment": a,
                "submission": sub,
                "progress_pct": sub.progress_pct if sub else 0,
                "status_label": _student_status_label(a, sub),
                "is_urgent": days_left is not None and days_left <= 2,
                "days_left": days_left,
            })

        for a in past_qs:
            sub = submissions_by_assignment.get(a.pk)
            past_with_sub.append({"assignment": a, "submission": sub})

    # Metrics
    urgent_count = sum(1 for item in open_assignments if item["is_urgent"])
    in_progress_count = sum(
        1 for item in open_assignments
        if item["submission"] and item["submission"].status == "brouillon"
    )
    validated_count = StudentSubmission.objects.filter(
        student=user, status="corrige",
    ).count()
    grades = list(StudentSubmission.objects.filter(
        student=user, status="corrige", grade__isnull=False,
    ).values_list("grade", flat=True))
    avg_grade = round(float(sum(grades)) / len(grades), 1) if grades else None
    avg_grade_pct = int(avg_grade / 20 * 100) if avg_grade else 0

    context = {
        "open_assignments": open_assignments,
        "past_with_sub": past_with_sub,
        "urgent_count": urgent_count,
        "in_progress_count": in_progress_count,
        "validated_count": validated_count,
        "avg_grade": avg_grade,
        "avg_grade_pct": avg_grade_pct,
        "total_open": len(open_assignments),
    }
    return render(request, "exercises/student_assignments.html", context)


def _student_status_label(assignment, submission):
    if not submission:
        return "À commencer"
    if submission.status == "brouillon":
        return f"En cours ({submission.progress_pct}% complété)"
    if submission.status == "rendu":
        return "Rendu — En attente de correction"
    if submission.status == "corrige":
        return "Corrigé"
    return "—"


def _get_or_create_submission(assignment, student):
    """Get or create a draft submission for this student."""
    sub, _ = StudentSubmission.objects.get_or_create(
        assignment=assignment,
        student=student,
        defaults={"status": "brouillon", "progress_pct": 0},
    )
    return sub


@role_required(Profil.ROLE_ETUDIANT)
def student_assignment_detail(request, pk):
    """Open / work on a specific assignment."""
    university = _university(request)
    assignment = get_object_or_404(
        Assignment, pk=pk, university=university, status__in=["ouvert", "correction", "termine"]
    )
    submission = StudentSubmission.objects.filter(
        assignment=assignment, student=request.user
    ).first()

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "save_draft":
            sub = _get_or_create_submission(assignment, request.user)
            sub.content = request.POST.get("content", sub.content)
            pct = request.POST.get("progress_pct", "")
            if pct.isdigit():
                sub.progress_pct = min(100, int(pct))
            sub.status = "brouillon"
            sub.save()
            messages.success(request, "Brouillon sauvegardé.")
            return redirect("exercises:student_assignment_detail", pk=pk)

        elif action == "submit":
            sub = _get_or_create_submission(assignment, request.user)
            sub.content = request.POST.get("content", sub.content)
            sub.progress_pct = 100
            sub.submit()
            # Update assignment submission count
            Assignment.objects.filter(pk=assignment.pk).update(
                submissions_count=StudentSubmission.objects.filter(
                    assignment=assignment, status__in=["rendu", "corrige"]
                ).count()
            )
            messages.success(request, f"Devoir « {assignment.title} » soumis avec succès !")
            return redirect("exercises:student_assignments")

    context = {
        "assignment": assignment,
        "submission": submission,
    }
    return render(request, "exercises/student_assignment_detail.html", context)


@role_required(Profil.ROLE_ETUDIANT)
def student_practice(request):
    """Séries d'entraînement pour l'étudiant."""
    university = _university(request)
    user = request.user

    if university:
        # Published series from teachers + AI-generated series by this student
        series_qs = list(ExerciseSeries.objects.filter(
            university=university,
            visibility="publiee",
        ).prefetch_related("items__exercise").order_by("-updated_at"))
    else:
        series_qs = []

    # Per-series progress: last attempt score
    attempt_map = {}
    if series_qs:
        series_ids = [s.pk for s in series_qs]
        # Get last attempt per series using a subquery approach
        from django.db.models import Max
        last_attempt_dates = PracticeAttempt.objects.filter(
            student=user, series_id__in=series_ids,
        ).values("series_id").annotate(last_date=Max("created_at"))
        for row in last_attempt_dates:
            attempt = PracticeAttempt.objects.filter(
                student=user,
                series_id=row["series_id"],
                created_at=row["last_date"],
            ).first()
            if attempt:
                attempt_map[row["series_id"]] = attempt

    series_with_progress = []
    for s in series_qs:
        total = s.items.count()
        last_attempt = attempt_map.get(s.pk)
        series_with_progress.append({
            "series": s,
            "total": total,
            "last_attempt": last_attempt,
        })

    # Recent attempts
    recent_attempts = PracticeAttempt.objects.filter(
        student=user,
    ).select_related("series").order_by("-created_at")[:10]

    # Metrics
    all_attempts = list(PracticeAttempt.objects.filter(student=user))
    total_resolved = len(all_attempts)
    success_rate = 0
    if total_resolved:
        good = sum(1 for a in all_attempts if a.result in ("reussi", "parfait"))
        success_rate = int(good / total_resolved * 100)

    # Streak: consecutive days with at least one attempt
    streak = _compute_streak(user)

    context = {
        "series_with_progress": series_with_progress,
        "series_list": series_qs,
        "recent_attempts": recent_attempts,
        "total_resolved": total_resolved,
        "success_rate": success_rate,
        "streak": streak,
    }
    return render(request, "exercises/student_practice.html", context)


def _compute_streak(user):
    """Compute consecutive-days streak of practice."""
    from datetime import date, timedelta
    dates = set(
        PracticeAttempt.objects.filter(student=user)
        .values_list("created_at__date", flat=True)
    )
    if not dates:
        return 0
    today = date.today()
    streak = 0
    day = today
    while day in dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


@role_required(Profil.ROLE_ETUDIANT)
def student_practice_session(request, pk):
    """Start / continue a practice session for a series."""
    university = _university(request)
    series = get_object_or_404(ExerciseSeries, pk=pk, university=university, visibility="publiee")
    exercises = list(
        Exercise.objects.filter(
            series_items__series=series, status="publie",
        ).prefetch_related("questions__choices").order_by("series_items__order")
    )

    if request.method == "POST":
        # Score calculation for QCM / vrai_faux
        score = 0
        max_score = 0
        for ex in exercises:
            for q in ex.questions.all():
                max_score += 1
                answer_key = f"q_{q.pk}"
                student_answer = request.POST.get(answer_key)
                correct = q.choices.filter(is_correct=True).first()
                if correct and student_answer and int(student_answer) == correct.pk:
                    score += 1

        # Determine result
        pct = (score / max_score * 100) if max_score else 0
        if pct >= 90:
            result = "parfait"
        elif pct >= 60:
            result = "reussi"
        else:
            result = "a_revoir"

        PracticeAttempt.objects.create(
            student=request.user,
            series=series,
            score=score,
            max_score=max_score,
            result=result,
        )
        messages.success(request, f"Session terminée : {score}/{max_score} — {series.get_visibility_display() if hasattr(series,'get_visibility_display') else ''}")
        return redirect("exercises:student_practice")

    context = {
        "series": series,
        "exercises": exercises,
    }
    return render(request, "exercises/student_practice_session.html", context)


@login_required
@require_POST
def api_ai_generate_student(request):
    """
    POST /exercises/api/generer-etudiant/
    Génère des questions IA ET les sauvegarde directement en base comme une série
    privée pour l'étudiant. Retourne l'ID de la série créée.
    """
    university = _university(request)
    if not university:
        return JsonResponse({"error": "Aucune université sélectionnée."}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON invalide."}, status=400)

    form = AIGenerateForm(data)
    if not form.is_valid():
        return JsonResponse({"error": "Paramètres invalides.", "details": form.errors}, status=400)

    groq_key = getattr(settings, "GROQ_API_KEY", "")
    if not groq_key:
        return JsonResponse({"error": "Service IA non configuré."}, status=503)

    try:
        result = _call_groq_generate(
            groq_key,
            form.cleaned_data["subject"],
            form.cleaned_data["topic"],
            form.cleaned_data["difficulty"],
            form.cleaned_data["exercise_type"],
            form.cleaned_data["count"],
        )
    except Exception as exc:
        logger.exception("Erreur génération IA étudiant : %s", exc)
        return JsonResponse({"error": str(exc)}, status=500)

    # --- Save to database ---
    subject = form.cleaned_data["subject"]
    difficulty = form.cleaned_data["difficulty"]
    exercise_type = form.cleaned_data["exercise_type"]

    with transaction.atomic():
        # 1. Create the exercise
        from .models import Question as Q, Choice as C
        exercise = Exercise.objects.create(
            university=university,
            author=request.user,
            title=result.get("title", f"Exercice IA — {subject}"),
            subject=subject,
            exercise_type=exercise_type,
            difficulty=difficulty,
            statement=result.get("statement", ""),
            correction="",
            status="publie",
            ai_generated=True,
            ai_validated=True,
            level="",
        )

        # 2. Create questions and choices
        for i, q_data in enumerate(result.get("questions", []), start=1):
            question = Q.objects.create(
                exercise=exercise,
                order=i,
                question_type=exercise_type if exercise_type in ("qcm", "vrai_faux") else "qcm",
                text=q_data.get("text", ""),
                points=1,
                explanation=q_data.get("explanation", ""),
            )
            choices = q_data.get("choices", [])
            correct_idx = q_data.get("correct_index", 0)
            for j, choice_text in enumerate(choices):
                C.objects.create(
                    question=question,
                    text=choice_text,
                    is_correct=(j == correct_idx),
                    order=j + 1,
                )

        # 3. Create a private series for this student
        series_name = result.get("title", f"Série IA — {subject}")
        series = ExerciseSeries.objects.create(
            university=university,
            author=request.user,
            name=series_name,
            subject=subject,
            description=f"Série générée par IA le {timezone.now().strftime('%d/%m/%Y à %Hh%M')}. Difficulté : {difficulty}.",
            visibility="publiee",   # visible to all in this university
        )
        SeriesItem.objects.create(series=series, exercise=exercise, order=1)

    result["series_id"] = series.pk
    result["series_name"] = series_name
    result["exercise_id"] = exercise.pk
    result["saved"] = True
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# PORTAIL PROFESSEUR
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_PROF)
def prof_exercise_bank(request):
    """Banque d'exercices du professeur."""
    university = _university(request)
    user = request.user

    if university:
        exercises = Exercise.objects.filter(
            university=university,
            author=user,
        ).select_related("category").order_by("-updated_at")
    else:
        exercises = Exercise.objects.none()

    # Métriques
    total = exercises.count()
    usages = sum(e.usage_count for e in exercises)
    qcm_count = exercises.filter(exercise_type__in=["qcm", "vrai_faux"]).count()
    code_count = exercises.filter(exercise_type="code").count()

    # Formulaire de création
    form = ExerciseForm(university=university)
    ai_form = AIGenerateForm()

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "create":
            form = ExerciseForm(request.POST, request.FILES, university=university)
            if form.is_valid():
                exercise = form.save(commit=False)
                exercise.university = university
                exercise.author = user
                exercise.save()
                messages.success(request, f"Exercice « {exercise.title} » créé avec succès.")
                return redirect("exercises:prof_exercise_bank")
            else:
                messages.error(request, "Veuillez corriger les erreurs du formulaire.")

        elif action == "delete":
            ex_id = request.POST.get("exercise_id")
            ex = get_object_or_404(Exercise, pk=ex_id, university=university, author=user)
            ex.delete()
            messages.success(request, "Exercice supprimé.")
            return redirect("exercises:prof_exercise_bank")

    context = {
        "exercises": exercises,
        "total": total,
        "usages": usages,
        "qcm_count": qcm_count,
        "code_count": code_count,
        "form": form,
        "ai_form": ai_form,
        "groq_enabled": bool(getattr(settings, "GROQ_API_KEY", "")),
    }
    return render(request, "exercises/prof_exercise_bank.html", context)


@role_required(Profil.ROLE_PROF)
def prof_exercise_create(request):
    """Création d'un exercice (page dédiée)."""
    university = _university(request)
    if request.method == "POST":
        form = ExerciseForm(request.POST, request.FILES, university=university)
        if form.is_valid():
            exercise = form.save(commit=False)
            exercise.university = university
            exercise.author = request.user
            exercise.save()
            messages.success(request, f"Exercice « {exercise.title} » créé.")
            return redirect("exercises:prof_exercise_bank")
    else:
        form = ExerciseForm(university=university)
    return render(request, "exercises/prof_exercise_form.html", {
        "form": form, "action": "Créer",
    })


@role_required(Profil.ROLE_PROF)
def prof_exercise_edit(request, pk):
    """Modification d'un exercice."""
    university = _university(request)
    exercise = get_object_or_404(Exercise, pk=pk, university=university, author=request.user)
    if request.method == "POST":
        form = ExerciseForm(request.POST, request.FILES, instance=exercise, university=university)
        if form.is_valid():
            form.save()
            messages.success(request, "Exercice mis à jour.")
            return redirect("exercises:prof_exercise_bank")
    else:
        form = ExerciseForm(instance=exercise, university=university)
    return render(request, "exercises/prof_exercise_form.html", {
        "form": form, "exercise": exercise, "action": "Modifier",
    })


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_exercise_delete(request, pk):
    """Suppression d'un exercice."""
    university = _university(request)
    exercise = get_object_or_404(Exercise, pk=pk, university=university, author=request.user)
    exercise.delete()
    messages.success(request, f"Exercice « {exercise.title} » supprimé.")
    return redirect("exercises:prof_exercise_bank")


# --- Devoirs ----------------------------------------------------------------

@role_required(Profil.ROLE_PROF)
def prof_assignments(request):
    """Liste des devoirs créés par le professeur."""
    university = _university(request)
    user = request.user

    if university:
        assignments = Assignment.objects.filter(
            university=university,
            author=user,
        ).select_related("rubric").order_by("-updated_at")
    else:
        assignments = Assignment.objects.none()

    # Métriques
    active_count = assignments.filter(status__in=["ouvert", "brouillon"]).count()
    total_submissions = sum(a.submissions_count for a in assignments)
    to_correct = assignments.filter(status="correction").count()
    rates = [a.submission_rate for a in assignments if a.expected_count]
    avg_rate = int(sum(rates) / len(rates)) if rates else 0

    # Formulaire création rapide
    form = AssignmentForm(university=university)
    if request.method == "POST":
        form = AssignmentForm(request.POST, university=university)
        if form.is_valid():
            a = form.save(commit=False)
            a.university = university
            a.author = user
            a.save()
            messages.success(request, f"Devoir « {a.title} » créé.")
            return redirect("exercises:prof_assignments")

    context = {
        "assignments": assignments,
        "active_count": active_count,
        "total_submissions": total_submissions,
        "to_correct": to_correct,
        "avg_rate": avg_rate,
        "form": form,
    }
    return render(request, "exercises/prof_assignments.html", context)


@role_required(Profil.ROLE_PROF)
def prof_assignment_create(request):
    university = _university(request)
    if request.method == "POST":
        form = AssignmentForm(request.POST, university=university)
        if form.is_valid():
            a = form.save(commit=False)
            a.university = university
            a.author = request.user
            a.save()
            messages.success(request, f"Devoir « {a.title} » créé.")
            return redirect("exercises:prof_assignments")
    else:
        form = AssignmentForm(university=university)
    return render(request, "exercises/prof_assignment_form.html", {
        "form": form, "action": "Créer",
    })


@role_required(Profil.ROLE_PROF)
def prof_assignment_edit(request, pk):
    university = _university(request)
    assignment = get_object_or_404(Assignment, pk=pk, university=university, author=request.user)
    if request.method == "POST":
        form = AssignmentForm(request.POST, instance=assignment, university=university)
        if form.is_valid():
            form.save()
            messages.success(request, "Devoir mis à jour.")
            return redirect("exercises:prof_assignments")
    else:
        form = AssignmentForm(instance=assignment, university=university)
    return render(request, "exercises/prof_assignment_form.html", {
        "form": form, "assignment": assignment, "action": "Modifier",
    })


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_assignment_delete(request, pk):
    university = _university(request)
    assignment = get_object_or_404(Assignment, pk=pk, university=university, author=request.user)
    assignment.delete()
    messages.success(request, f"Devoir « {assignment.title} » supprimé.")
    return redirect("exercises:prof_assignments")


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_assignment_status(request, pk):
    """Change le statut d'un devoir (ouvert → correction → termine)."""
    university = _university(request)
    assignment = get_object_or_404(Assignment, pk=pk, university=university, author=request.user)
    new_status = request.POST.get("status")
    valid = dict(Assignment._meta.get_field("status").choices)
    if new_status in valid:
        assignment.status = new_status
        assignment.save(update_fields=["status"])
        messages.success(request, f"Statut du devoir mis à jour : {valid[new_status]}.")
    return redirect("exercises:prof_assignments")


# --- Séries & Barèmes -------------------------------------------------------

@role_required(Profil.ROLE_PROF)
def prof_rubrics(request):
    """Séries & Barèmes du professeur."""
    university = _university(request)
    user = request.user

    if university:
        rubrics = Rubric.objects.filter(
            university=university, author=user,
        ).prefetch_related("criteria").order_by("-updated_at")
        series = ExerciseSeries.objects.filter(
            university=university, author=user,
        ).select_related("rubric").order_by("-updated_at")
    else:
        rubrics = Rubric.objects.none()
        series = ExerciseSeries.objects.none()

    # Métriques
    active_rubrics = rubrics.filter(status="actif").count()
    total_criteria = sum(r.criteria.count() for r in rubrics)
    series_count = series.count()

    # Formulaire barème
    rubric_form = RubricForm()
    series_form = ExerciseSeriesForm(university=university)

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "create_rubric":
            rubric_form = RubricForm(request.POST)
            if rubric_form.is_valid():
                r = rubric_form.save(commit=False)
                r.university = university
                r.author = user
                r.save()
                messages.success(request, f"Barème « {r.name} » créé.")
                return redirect("exercises:prof_rubrics")

        elif action == "create_series":
            series_form = ExerciseSeriesForm(request.POST, university=university)
            if series_form.is_valid():
                s = series_form.save(commit=False)
                s.university = university
                s.author = user
                s.save()
                messages.success(request, f"Série « {s.name} » créée.")
                return redirect("exercises:prof_rubrics")

        elif action == "delete_rubric":
            r_id = request.POST.get("rubric_id")
            r = get_object_or_404(Rubric, pk=r_id, university=university, author=user)
            r.delete()
            messages.success(request, "Barème supprimé.")
            return redirect("exercises:prof_rubrics")

        elif action == "delete_series":
            s_id = request.POST.get("series_id")
            s = get_object_or_404(ExerciseSeries, pk=s_id, university=university, author=user)
            s.delete()
            messages.success(request, "Série supprimée.")
            return redirect("exercises:prof_rubrics")

    context = {
        "rubrics": rubrics,
        "series": series,
        "active_rubrics": active_rubrics,
        "total_criteria": total_criteria,
        "series_count": series_count,
        "rubric_form": rubric_form,
        "series_form": series_form,
    }
    return render(request, "exercises/prof_rubrics.html", context)


@role_required(Profil.ROLE_PROF)
def prof_rubric_edit(request, pk):
    university = _university(request)
    rubric = get_object_or_404(Rubric, pk=pk, university=university, author=request.user)
    if request.method == "POST":
        form = RubricForm(request.POST, instance=rubric)
        formset = CriterionFormSet(request.POST, instance=rubric)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "Barème mis à jour.")
            return redirect("exercises:prof_rubrics")
    else:
        form = RubricForm(instance=rubric)
        formset = CriterionFormSet(instance=rubric)
    return render(request, "exercises/prof_rubric_form.html", {
        "form": form, "formset": formset, "rubric": rubric,
    })


# ---------------------------------------------------------------------------
# ADMINISTRATION
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_ADMIN)
def admin_exercise_banks(request):
    """Supervision des banques d'exercices (admin université)."""
    university = _university(request)

    if university:
        # Stats agrégées par catégorie (= "banque")
        categories = Category.objects.filter(university=university).order_by("name")
        total_exercises = Exercise.objects.filter(university=university).count()
        published = Exercise.objects.filter(university=university, status="publie").count()
        pending = Exercise.objects.filter(university=university, status="brouillon").count()
        active_cat = categories.filter(is_active=True).count()
        inactive_cat = categories.filter(is_active=False).count()

        # Données par banque/catégorie pour le tableau
        banks = []
        for cat in categories:
            exs = Exercise.objects.filter(university=university, category=cat)
            banks.append({
                "category": cat,
                "count": exs.count(),
                "published": exs.filter(status="publie").count(),
                "usages": sum(e.usage_count for e in exs),
                "last_updated": exs.order_by("-updated_at").values_list("updated_at", flat=True).first(),
            })

        # Sans catégorie
        no_cat_count = Exercise.objects.filter(university=university, category__isnull=True).count()
    else:
        categories = Category.objects.none()
        total_exercises = published = pending = active_cat = inactive_cat = 0
        banks = []
        no_cat_count = 0

    # Formulaire création catégorie (modal)
    cat_form = CategoryForm()
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create_category":
            cat_form = CategoryForm(request.POST)
            if cat_form.is_valid():
                cat = cat_form.save(commit=False)
                cat.university = university
                cat.save()
                messages.success(request, f"Banque/catégorie « {cat.name} » créée.")
                return redirect("exercises:admin_exercise_banks")
        elif action == "toggle_category":
            cat_id = request.POST.get("category_id")
            cat = get_object_or_404(Category, pk=cat_id, university=university)
            cat.is_active = not cat.is_active
            cat.save(update_fields=["is_active"])
            messages.success(request, f"Catégorie « {cat.name} » {'activée' if cat.is_active else 'suspendue'}.")
            return redirect("exercises:admin_exercise_banks")

    context = {
        "categories": categories,
        "banks": banks,
        "total_exercises": total_exercises,
        "published": published,
        "pending": pending,
        "active_cat": active_cat,
        "inactive_cat": inactive_cat,
        "no_cat_count": no_cat_count,
        "cat_form": cat_form,
    }
    return render(request, "exercises/admin_exercise_banks.html", context)


@role_required(Profil.ROLE_ADMIN)
def admin_categories(request):
    """Catégories & Niveaux de difficulté."""
    university = _university(request)

    if university:
        categories = Category.objects.filter(university=university).order_by("name")
        active_count = categories.filter(is_active=True).count()
        archived_count = categories.filter(is_active=False).count()
        total_exercises = Exercise.objects.filter(university=university).count()
    else:
        categories = Category.objects.none()
        active_count = archived_count = total_exercises = 0

    cat_form = CategoryForm()

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "create":
            cat_form = CategoryForm(request.POST)
            if cat_form.is_valid():
                cat = cat_form.save(commit=False)
                cat.university = university
                cat.save()
                messages.success(request, f"Catégorie « {cat.name} » créée.")
                return redirect("exercises:admin_categories")

        elif action == "toggle":
            cat_id = request.POST.get("category_id")
            cat = get_object_or_404(Category, pk=cat_id, university=university)
            cat.is_active = not cat.is_active
            cat.save(update_fields=["is_active"])
            msg = f"Catégorie « {cat.name} » {'restaurée' if cat.is_active else 'archivée'}."
            messages.success(request, msg)
            return redirect("exercises:admin_categories")

        elif action == "delete":
            cat_id = request.POST.get("category_id")
            cat = get_object_or_404(Category, pk=cat_id, university=university)
            cat.delete()
            messages.success(request, "Catégorie supprimée.")
            return redirect("exercises:admin_categories")

    # Niveaux de difficulté (données statiques enrichies par les vrais comptes)
    if university:
        difficulty_stats = []
        for key, label in [
            ("facile", "Facile"), ("moyen", "Moyen"),
            ("difficile", "Difficile"), ("expert", "Expert"),
        ]:
            count = Exercise.objects.filter(university=university, difficulty=key).count()
            difficulty_stats.append({"key": key, "label": label, "count": count})
    else:
        difficulty_stats = []

    context = {
        "categories": categories,
        "active_count": active_count,
        "archived_count": archived_count,
        "total_exercises": total_exercises,
        "cat_form": cat_form,
        "difficulty_stats": difficulty_stats,
    }
    return render(request, "exercises/admin_categories.html", context)


# ---------------------------------------------------------------------------
# API JSON — Génération IA
# ---------------------------------------------------------------------------

@login_required
def api_ai_generate(request):
    """
    POST /exercises/api/generer/
    Corps JSON : { subject, topic, difficulty, exercise_type, count }
    Retourne : { title, statement, questions: [...] }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON invalide."}, status=400)

    form = AIGenerateForm(data)
    if not form.is_valid():
        return JsonResponse({"error": "Paramètres invalides.", "details": form.errors}, status=400)

    subject = form.cleaned_data["subject"]
    topic = form.cleaned_data["topic"]
    difficulty = form.cleaned_data["difficulty"]
    exercise_type = form.cleaned_data["exercise_type"]
    count = form.cleaned_data["count"]

    groq_key = getattr(settings, "GROQ_API_KEY", "")
    if not groq_key:
        return JsonResponse({"error": "Clé GROQ non configurée."}, status=503)

    try:
        result = _call_groq_generate(groq_key, subject, topic, difficulty, exercise_type, count)
        return JsonResponse(result)
    except Exception as exc:
        logger.exception("Erreur génération IA exercice : %s", exc)
        return JsonResponse({"error": "Erreur lors de la génération IA.", "detail": str(exc)}, status=500)


def _call_groq_generate(api_key, subject, topic, difficulty, exercise_type, count):
    """Appelle l'API GROQ pour générer des questions."""
    import requests as req_lib

    type_labels = {
        "qcm": "QCM (choix multiples, 4 choix dont 1 correct)",
        "vrai_faux": "Vrai/Faux",
        "trou": "Texte à trous",
        "probleme": "Problème ouvert",
    }
    type_label = type_labels.get(exercise_type, exercise_type)

    system_prompt = (
        "Tu es un générateur d'exercices pédagogiques universitaires. "
        "Réponds UNIQUEMENT en JSON valide, sans markdown, sans commentaires."
    )
    user_prompt = f"""Génère {count} questions de type « {type_label} » sur le sujet « {topic} » 
(matière : {subject}, niveau de difficulté : {difficulty}).

Retourne un objet JSON avec cette structure EXACTE :
{{
  "title": "Titre de l'exercice",
  "statement": "Contexte/introduction de l'exercice",
  "questions": [
    {{
      "text": "Texte de la question",
      "type": "{exercise_type}",
      "choices": ["Choix A", "Choix B", "Choix C", "Choix D"],
      "correct_index": 0,
      "explanation": "Explication de la bonne réponse"
    }}
  ]
}}
Pour vrai_faux, choices = ["Vrai", "Faux"].
Pour trou, choices = [] et ajoute "blank_answer" avec la réponse attendue.
Pour probleme, choices = [].
"""

    model = getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    # Try configured model first, then reliable fallbacks
    models_to_try = []
    if model and model not in ("llama-3.3-70b-versatile", "llama3-8b-8192"):
        models_to_try.append(model)
    models_to_try.extend(["llama-3.3-70b-versatile", "llama3-70b-8192", "llama3-8b-8192"])

    last_error = None
    for attempt_model in models_to_try:
        try:
            response = req_lib.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": attempt_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2048,
                },
                timeout=30,
            )
            if response.status_code == 200:
                break
            if response.status_code in (404, 400):
                last_error = f"Model {attempt_model} not available (HTTP {response.status_code})"
                continue
            response.raise_for_status()
        except req_lib.exceptions.Timeout:
            last_error = f"Timeout for model {attempt_model}"
            continue
    else:
        raise RuntimeError(f"All models failed. Last error: {last_error}")

    content = response.json()["choices"][0]["message"]["content"]
    # Nettoyage éventuel du markdown
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()
    result = json.loads(content)
    result["ai_model"] = attempt_model
    return result


@login_required
@require_POST
def api_exercise_save_ai(request):
    """
    Sauvegarde un exercice généré par IA après validation du prof.
    POST JSON : { title, statement, questions, subject, difficulty, exercise_type }
    """
    university = _university(request)
    if not university:
        return JsonResponse({"error": "Aucune université sélectionnée."}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON invalide."}, status=400)

    with transaction.atomic():
        exercise = Exercise.objects.create(
            university=university,
            author=request.user,
            title=data.get("title", "Exercice IA"),
            subject=data.get("subject", ""),
            exercise_type=data.get("exercise_type", "qcm"),
            difficulty=data.get("difficulty", "moyen"),
            statement=data.get("statement", ""),
            ai_generated=True,
            ai_validated=True,
            status="brouillon",
        )
        for i, q_data in enumerate(data.get("questions", []), start=1):
            from .models import Question, Choice
            question = Question.objects.create(
                exercise=exercise,
                order=i,
                question_type=data.get("exercise_type", "qcm"),
                text=q_data.get("text", ""),
                explanation=q_data.get("explanation", ""),
            )
            choices = q_data.get("choices", [])
            correct_idx = q_data.get("correct_index", 0)
            for j, choice_text in enumerate(choices):
                Choice.objects.create(
                    question=question,
                    text=choice_text,
                    is_correct=(j == correct_idx),
                    order=j + 1,
                )

    return JsonResponse({
        "success": True,
        "exercise_id": exercise.pk,
        "title": exercise.title,
        "redirect": "/prof/banque-exercices/",
    })

# ---------------------------------------------------------------------------
# PDF — Génération devoir (étudiant + prof)
# ---------------------------------------------------------------------------

@role_required(Profil.ROLE_ETUDIANT)
def student_assignment_pdf(request, pk):
    """Génère le PDF du sujet d'un devoir pour l'étudiant."""
    university = _university(request)
    assignment = get_object_or_404(
        Assignment, pk=pk, university=university,
        status__in=["ouvert", "correction", "termine"],
    )
    return _generate_assignment_pdf(assignment, request)


@role_required(Profil.ROLE_PROF)
def prof_assignment_pdf(request, pk):
    """Génère le PDF du devoir (vue prof)."""
    university = _university(request)
    assignment = get_object_or_404(Assignment, pk=pk, university=university)
    return _generate_assignment_pdf(assignment, request)


def _generate_assignment_pdf(assignment, request):
    """Build and return a PDF HttpResponse for an assignment."""
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
        Table, TableStyle, KeepTogether,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    import io

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    # Custom styles
    title_style = ParagraphStyle("DocTitle", parent=styles["Title"],
        fontSize=18, spaceAfter=6, textColor=colors.HexColor("#1a237e"))
    subtitle_style = ParagraphStyle("SubTitle", parent=styles["Normal"],
        fontSize=11, spaceAfter=4, textColor=colors.HexColor("#455a64"))
    heading_style = ParagraphStyle("SectionHead", parent=styles["Heading2"],
        fontSize=13, spaceBefore=14, spaceAfter=6,
        textColor=colors.HexColor("#1a237e"), borderPad=4)
    body_style = ParagraphStyle("Body", parent=styles["Normal"],
        fontSize=10, spaceAfter=4, leading=15, alignment=TA_JUSTIFY)
    q_style = ParagraphStyle("Question", parent=styles["Normal"],
        fontSize=10, spaceAfter=4, leading=14, leftIndent=0,
        textColor=colors.HexColor("#212121"), fontName="Helvetica-Bold")
    choice_style = ParagraphStyle("Choice", parent=styles["Normal"],
        fontSize=10, leading=14, leftIndent=20, spaceAfter=2)
    label_style = ParagraphStyle("Label", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#607d8b"), spaceAfter=2)

    story = []
    univ = assignment.university

    # ---- Header band ----
    header_data = [[
        Paragraph(f"<b>{univ.name}</b>", ParagraphStyle("H", fontSize=9,
            textColor=colors.white, fontName="Helvetica-Bold")),
        Paragraph(f"<b>{univ.code or ''}</b>", ParagraphStyle("H2", fontSize=9,
            textColor=colors.white, alignment=TA_CENTER)),
        Paragraph(
            f"<b>Année : {assignment.created_at.year if assignment.created_at else '—'}</b>",
            ParagraphStyle("H3", fontSize=9, textColor=colors.white, alignment=TA_LEFT)),
    ]]
    header_table = Table(header_data, colWidths=[9*cm, 4*cm, 4*cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1a237e")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, -1), 10),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 10),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.5 * cm))

    # ---- Title ----
    story.append(Paragraph(assignment.title, title_style))
    if assignment.subject:
        story.append(Paragraph(f"Matière : {assignment.subject}", subtitle_style))
    if assignment.school_class:
        story.append(Paragraph(f"Classe : {assignment.school_class}", subtitle_style))
    if assignment.deadline:
        from django.utils.formats import date_format
        deadline_str = assignment.deadline.strftime("%d/%m/%Y à %Hh%M")
        story.append(Paragraph(f"Échéance : {deadline_str}", subtitle_style))

    meta_data = []
    if assignment.coefficient:
        meta_data.append(f"Coefficient : {assignment.coefficient}")
    if assignment.rubric:
        meta_data.append(f"Barème : {assignment.rubric.name}")
    if meta_data:
        story.append(Paragraph("  |  ".join(meta_data), label_style))

    story.append(HRFlowable(width="100%", thickness=2,
                            color=colors.HexColor("#1a237e"), spaceAfter=10))

    # ---- Instructions ----
    if assignment.instructions:
        story.append(Paragraph("CONSIGNES", heading_style))
        for line in assignment.instructions.split("\n"):
            line = line.strip()
            if line:
                story.append(Paragraph(line, body_style))
        story.append(Spacer(1, 0.3 * cm))

    # ---- Exercises and Questions ----
    items = assignment.items.select_related("exercise").prefetch_related(
        "exercise__questions__choices"
    ).order_by("order")

    if items.exists():
        story.append(Paragraph("EXERCICES", heading_style))

    q_global = 0
    for idx, item in enumerate(items, start=1):
        ex = item.exercise
        ex_elements = []

        ex_title = f"Exercice {idx} — {ex.title}"
        meta = []
        if ex.subject:
            meta.append(ex.subject)
        if ex.get_difficulty_display():
            meta.append(ex.get_difficulty_display())
        if ex.duration_minutes:
            meta.append(f"{ex.duration_minutes} min")
        if meta:
            ex_title += f"  ({' · '.join(meta)})"

        ex_elements.append(Paragraph(ex_title, ParagraphStyle("ExHead",
            parent=styles["Heading3"], fontSize=11, spaceBefore=10, spaceAfter=4,
            textColor=colors.HexColor("#283593"))))

        if ex.statement:
            for line in ex.statement.split("\n"):
                line = line.strip()
                if line:
                    ex_elements.append(Paragraph(line, body_style))

        ex_elements.append(Spacer(1, 0.2 * cm))

        # Questions
        questions = ex.questions.all().order_by("order")
        for q in questions:
            q_global += 1
            q_text = f"Q{q_global}. {q.text}"
            if float(q.points) != 1.0:
                q_text += f"  <font size='8' color='#607d8b'>({q.points} pt{'s' if float(q.points) > 1 else ''})</font>"
            ex_elements.append(Paragraph(q_text, q_style))

            choices = q.choices.all().order_by("order")
            letters = ["A", "B", "C", "D", "E", "F"]
            for ci, choice in enumerate(choices):
                letter = letters[ci] if ci < len(letters) else str(ci + 1)
                ex_elements.append(Paragraph(
                    f"○  {letter}. {choice.text}", choice_style))
            ex_elements.append(Spacer(1, 0.15 * cm))

        story.append(KeepTogether(ex_elements))

    # ---- Rubric ----
    if assignment.rubric:
        story.append(Spacer(1, 0.3 * cm))
        story.append(HRFlowable(width="100%", thickness=1,
                                color=colors.HexColor("#cfd8dc"), spaceBefore=4, spaceAfter=6))
        story.append(Paragraph("BARÈME DE NOTATION", heading_style))
        rubric_data = [["Critère", "Points"]]
        for criterion in assignment.rubric.criteria.all().order_by("order"):
            rubric_data.append([criterion.name, f"{criterion.points} pts"])
        rubric_data.append(["TOTAL", f"{assignment.rubric.total_points} pts"])
        rubric_table = Table(rubric_data, colWidths=[13 * cm, 4 * cm])
        rubric_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eaf6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e3f2fd")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2),
             [colors.white, colors.HexColor("#fafafa")]),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdbdbd")),
        ]))
        story.append(rubric_table)

    # ---- Footer ----
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5,
                            color=colors.HexColor("#bdbdbd"), spaceAfter=4))
    story.append(Paragraph(
        f"Document généré par EduSpark — {univ.name} — "
        f"{assignment.title}",
        ParagraphStyle("Footer", parent=styles["Normal"],
                       fontSize=7, textColor=colors.HexColor("#9e9e9e"), alignment=TA_CENTER),
    ))

    doc.build(story)
    buffer.seek(0)
    filename = f"devoir-{assignment.pk}-{assignment.title[:40].replace(' ', '_')}.pdf"
    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# API IA — Génération étudiant (alias déjà défini ci-dessus)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# (api_ai_generate_student is defined earlier in the student section)
# ---------------------------------------------------------------------------
