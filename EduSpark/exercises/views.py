"""Vues du module Exercices — CRUD complet.

Enseignant (prof) :
  - Banque d'exercices  : liste, créer, modifier, supprimer, générer IA
  - Devoirs             : liste, créer, modifier, supprimer
  - Barèmes & Séries    : liste, créer, modifier, supprimer

Étudiant :
  - Devoirs             : liste recommandée, détail, brouillon, soumettre, PDF
  - Entraînement        : séries filtrées, tentatives récentes

Admin université :
  - Banques agrégées, Catégories CRUD
"""
import logging

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required, etudiant_required, prof_required

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
    Category,
    Exercise,
    ExerciseSeries,
    PracticeAttempt,
    Rubric,
    StudentSubmission,
)

logger = logging.getLogger(__name__)


def _uni(request):
    return request.university


# ===========================================================================
# ENSEIGNANT — Banque d'exercices
# ===========================================================================

@prof_required
def prof_exercise_bank(request):
    uni = _uni(request)
    qs = Exercise.objects.filter(university=uni, author=request.user).select_related("category")

    q = request.GET.get("q", "").strip()
    ex_type = request.GET.get("type", "")
    diff = request.GET.get("difficulty", "")
    status = request.GET.get("status", "")

    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(title__icontains=q) | Q(subject__icontains=q) |
            Q(tags__icontains=q) | Q(category__name__icontains=q)
        )
    if ex_type:
        qs = qs.filter(exercise_type=ex_type)
    if diff:
        qs = qs.filter(difficulty=diff)
    if status:
        qs = qs.filter(status=status)

    base_qs = Exercise.objects.filter(university=uni, author=request.user)
    return render(request, "exercises/prof_exercise_bank.html", {
        "exercises": qs.order_by("-updated_at"),
        "total": base_qs.count(),
        "qcm_count": base_qs.filter(exercise_type="qcm").count(),
        "published": base_qs.filter(status="publie").count(),
        "ai_count": base_qs.filter(ai_generated=True).count(),
        "q": q, "filter_type": ex_type, "filter_difficulty": diff, "filter_status": status,
        "ai_form": AIGenerateForm(),
    })


@prof_required
def prof_exercise_create(request):
    uni = _uni(request)
    if request.method == "POST":
        form = ExerciseForm(request.POST, request.FILES, university=uni)
        if form.is_valid():
            ex = form.save(commit=False)
            ex.university = uni
            ex.author = request.user
            ex.save()
            messages.success(request, "Exercice « %s » créé." % ex.title)
            return redirect("exercises:prof_exercise_bank")
    else:
        form = ExerciseForm(university=uni)
    return render(request, "exercises/prof_exercise_form.html", {"form": form, "action": "Créer"})


@prof_required
def prof_exercise_update(request, pk):
    uni = _uni(request)
    ex = get_object_or_404(Exercise, pk=pk, university=uni, author=request.user)
    if request.method == "POST":
        form = ExerciseForm(request.POST, request.FILES, instance=ex, university=uni)
        if form.is_valid():
            form.save()
            messages.success(request, "Exercice mis à jour.")
            return redirect("exercises:prof_exercise_bank")
    else:
        form = ExerciseForm(instance=ex, university=uni)
    return render(request, "exercises/prof_exercise_form.html", {
        "form": form, "action": "Modifier", "exercise": ex,
    })


@prof_required
@require_POST
def prof_exercise_delete(request, pk):
    uni = _uni(request)
    ex = get_object_or_404(Exercise, pk=pk, university=uni, author=request.user)
    title = ex.title
    ex.delete()
    messages.success(request, "Exercice « %s » supprimé." % title)
    return redirect("exercises:prof_exercise_bank")


# ===========================================================================
# ENSEIGNANT — Génération IA
# ===========================================================================

@prof_required
def prof_exercise_ai_generate(request):
    """Génère un exercice via l'IA (Groq) et le sauvegarde en brouillon.
    Réponse JSON pour la requête AJAX du drawer.
    """
    from .services.ai_exercise import (
        ExerciseGenerationError, ai_exercise_available,
        generate_exercise_questions, save_generated_questions,
    )

    if not ai_exercise_available():
        return JsonResponse({"ok": False, "error": "GROQ_API_KEY non configurée."}, status=503)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST requis."}, status=405)

    form = AIGenerateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": str(form.errors)}, status=400)

    cd = form.cleaned_data
    uni = _uni(request)

    try:
        questions, meta = generate_exercise_questions(
            subject=cd["subject"], topic=cd["topic"],
            exercise_type=cd["exercise_type"], difficulty=cd["difficulty"],
            count=cd["count"],
        )
    except ExerciseGenerationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    ex = Exercise.objects.create(
        university=uni, author=request.user,
        title="%s — %s" % (cd["topic"], cd["subject"]),
        subject=cd["subject"],
        exercise_type=cd["exercise_type"],
        difficulty=cd["difficulty"],
        statement="Exercice généré par IA sur le thème : %s" % cd["topic"],
        status="brouillon", ai_generated=True,
    )
    save_generated_questions(ex, questions)

    messages.success(request, "%d questions générées. Relisez avant de publier." % len(questions))
    return JsonResponse({
        "ok": True,
        "exercise_id": ex.pk,
        "edit_url": "/prof/exercices/%d/modifier/" % ex.pk,
        "questions_count": len(questions),
    })


# ===========================================================================
# ENSEIGNANT — Devoirs
# ===========================================================================

@prof_required
def prof_assignments(request):
    uni = _uni(request)
    qs = Assignment.objects.filter(university=uni, author=request.user)

    sf = request.GET.get("status", "")
    if sf:
        qs = qs.filter(status=sf)

    qs = qs.order_by("-updated_at")
    total_sub = sum(a.submissions_count for a in qs)
    total_exp = sum(a.expected_count for a in qs)

    base = Assignment.objects.filter(university=uni, author=request.user)
    return render(request, "exercises/prof_assignments.html", {
        "assignments": qs,
        "active": base.filter(status="ouvert").count(),
        "total_sub": total_sub, "total_exp": total_exp,
        "to_correct": base.filter(status="correction").count(),
        "avg_rate": int(total_sub / total_exp * 100) if total_exp else 0,
        "filter_status": sf,
    })


@prof_required
def prof_assignment_create(request):
    uni = _uni(request)
    if request.method == "POST":
        form = AssignmentForm(request.POST, university=uni)
        if form.is_valid():
            a = form.save(commit=False)
            a.university = uni
            a.author = request.user
            a.save()
            messages.success(request, "Devoir « %s » créé." % a.title)
            return redirect("exercises:prof_assignments")
    else:
        form = AssignmentForm(university=uni)
    return render(request, "exercises/prof_assignment_form.html", {"form": form, "action": "Créer"})


@prof_required
def prof_assignment_update(request, pk):
    uni = _uni(request)
    a = get_object_or_404(Assignment, pk=pk, university=uni, author=request.user)
    if request.method == "POST":
        form = AssignmentForm(request.POST, instance=a, university=uni)
        if form.is_valid():
            form.save()
            messages.success(request, "Devoir mis à jour.")
            return redirect("exercises:prof_assignments")
    else:
        form = AssignmentForm(instance=a, university=uni)
    return render(request, "exercises/prof_assignment_form.html", {
        "form": form, "action": "Modifier", "assignment": a,
    })


@prof_required
@require_POST
def prof_assignment_delete(request, pk):
    uni = _uni(request)
    a = get_object_or_404(Assignment, pk=pk, university=uni, author=request.user)
    title = a.title
    a.delete()
    messages.success(request, "Devoir « %s » supprimé." % title)
    return redirect("exercises:prof_assignments")


# ===========================================================================
# ENSEIGNANT — Barèmes & Séries
# ===========================================================================

@prof_required
def prof_rubrics(request):
    uni = _uni(request)
    rubrics = Rubric.objects.filter(university=uni).prefetch_related("criteria")
    series = ExerciseSeries.objects.filter(university=uni, author=request.user).select_related("rubric")
    return render(request, "exercises/prof_rubrics.html", {
        "rubrics": rubrics.order_by("-updated_at"),
        "series_list": series.order_by("-updated_at"),
        "active_count": rubrics.filter(status="actif").count(),
        "criteria_count": sum(r.criteria.count() for r in rubrics),
        "series_count": series.count(),
    })


@prof_required
def prof_rubric_create(request):
    uni = _uni(request)
    if request.method == "POST":
        form = RubricForm(request.POST)
        formset = CriterionFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            rubric = form.save(commit=False)
            rubric.university = uni
            rubric.author = request.user
            rubric.save()
            formset.instance = rubric
            formset.save()
            messages.success(request, "Barème « %s » créé." % rubric.name)
            return redirect("exercises:prof_rubrics")
    else:
        form = RubricForm()
        formset = CriterionFormSet()
    return render(request, "exercises/prof_rubric_form.html", {
        "form": form, "formset": formset, "action": "Créer",
    })


@prof_required
def prof_rubric_update(request, pk):
    uni = _uni(request)
    rubric = get_object_or_404(Rubric, pk=pk, university=uni)
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
        "form": form, "formset": formset, "rubric": rubric, "action": "Modifier",
    })


@prof_required
@require_POST
def prof_rubric_delete(request, pk):
    uni = _uni(request)
    rubric = get_object_or_404(Rubric, pk=pk, university=uni)
    name = rubric.name
    rubric.delete()
    messages.success(request, "Barème « %s » supprimé." % name)
    return redirect("exercises:prof_rubrics")


# ===========================================================================
# ÉTUDIANT — Devoirs (avec recommandations)
# ===========================================================================

@etudiant_required
def student_assignments(request):
    uni = _uni(request)

    # Devoirs visibles : créés par les profs (groupe "prof") + devoirs IA
    # personnels générés par l'étudiant lui-même.
    from django.db.models import Q
    assignments = (
        Assignment.objects.filter(
            university=uni, status__in=["ouvert", "correction", "termine"]
        ).filter(
            Q(author=request.user) | Q(author__groups__name="prof") | Q(author__is_superuser=True)
        ).distinct().order_by("deadline", "-updated_at")
    )

    submission_map = {
        s.assignment_id: s
        for s in StudentSubmission.objects.filter(student=request.user, assignment__in=assignments)
    }

    # Séries recommandées (publiées)
    series_qs = (
        ExerciseSeries.objects.filter(university=uni, visibility="publiee")
        .prefetch_related("items").order_by("-updated_at")[:12]
    )

    recent_attempts = (
        PracticeAttempt.objects.filter(student=request.user)
        .select_related("series").order_by("-created_at")[:5]
    )

    # Stats rapides
    urgent = sum(
        1 for a in assignments
        if a.status == "ouvert" and submission_map.get(a.pk) is None
    )
    in_draft = sum(1 for s in submission_map.values() if s.status == "brouillon")
    graded = sum(1 for s in submission_map.values() if s.status == "corrige")

    assignments_with_sub = [(a, submission_map.get(a.pk)) for a in assignments]

    return render(request, "exercises/student_assignments.html", {
        "assignments_with_sub": assignments_with_sub,
        "series_list": series_qs,
        "recent_attempts": recent_attempts,
        "urgent_count": urgent,
        "in_draft_count": in_draft,
        "graded_count": graded,
        "total_assignments": assignments.count(),
        "ai_form": AIGenerateForm(),
    })


@etudiant_required
def student_assignment_detail(request, pk):
    uni = _uni(request)
    assignment = get_object_or_404(
        Assignment, pk=pk, university=uni, status__in=["ouvert", "correction", "termine"]
    )
    submission, _ = StudentSubmission.objects.get_or_create(
        assignment=assignment, student=request.user,
    )

    if request.method == "POST":
        action = request.POST.get("action")
        content = request.POST.get("content", "").strip()

        if action == "save_draft" and submission.status == "brouillon":
            try:
                progress = min(100, max(0, int(request.POST.get("progress_pct") or 0)))
            except ValueError:
                progress = 0
            submission.content = content
            submission.progress_pct = progress
            submission.save(update_fields=["content", "progress_pct", "updated_at"])
            messages.success(request, "Brouillon sauvegardé.")

        elif action == "submit" and submission.status != "rendu":
            submission.content = content
            submission.save(update_fields=["content"])
            submission.submit()
            messages.success(request, "Devoir soumis avec succès !")

        return redirect("exercises:student_assignment_detail", pk=pk)

    return render(request, "exercises/student_assignment_detail.html", {
        "assignment": assignment,
        "submission": submission,
        "exercises": assignment.items.select_related("exercise").order_by("order"),
    })


@etudiant_required
def student_assignment_generate_ia(request):
    """L'étudiant génère un devoir d'entraînement personnalisé via l'IA.

    Crée un Exercise (IA) + un Assignment (ouvert, personnel) + lie
    l'exercice au devoir + crée une StudentSubmission (brouillon).
    Le devoir apparaît alors dans « Mes Devoirs » et l'étudiant peut
    y travailler et le rendre.
    """
    from .services.ai_exercise import (
        ExerciseGenerationError, ai_exercise_available,
        generate_exercise_questions, save_generated_questions,
    )
    from .models import AssignmentExercise

    if not ai_exercise_available():
        return JsonResponse(
            {"ok": False, "error": "GROQ_API_KEY non configurée."}, status=503,
        )
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST requis."}, status=405)

    form = AIGenerateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "error": str(form.errors)}, status=400)

    cd = form.cleaned_data
    uni = _uni(request)

    try:
        questions, _meta = generate_exercise_questions(
            subject=cd["subject"], topic=cd["topic"],
            exercise_type=cd["exercise_type"], difficulty=cd["difficulty"],
            count=cd["count"],
        )
    except ExerciseGenerationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    # 1) Exercice IA publié (utilisable par l'étudiant)
    exercise = Exercise.objects.create(
        university=uni, author=request.user,
        title="%s — %s" % (cd["topic"], cd["subject"]),
        subject=cd["subject"],
        exercise_type=cd["exercise_type"],
        difficulty=cd["difficulty"],
        statement="Exercice d'entraînement généré par IA sur le thème : %s" % cd["topic"],
        status="publie", ai_generated=True, ai_validated=False,
    )
    save_generated_questions(exercise, questions)

    # 2) Devoir personnel ouvert pour l'étudiant
    assignment = Assignment.objects.create(
        university=uni, author=request.user,
        title="Entraînement IA — %s" % cd["topic"],
        subject=cd["subject"],
        school_class="Entraînement personnel IA",
        instructions=(
            "Devoir d'entraînement généré automatiquement par l'IA sur le "
            "thème « %s » (%s, %s). Répondez aux questions ci-dessous puis "
            "soumettez votre copie. Vous pouvez télécharger le sujet en PDF."
            % (cd["topic"], cd["subject"], cd["difficulty"])
        ),
        coefficient=1,
        status="ouvert",
        expected_count=1,
    )

    # 3) Lie l'exercice au devoir
    AssignmentExercise.objects.create(
        assignment=assignment, exercise=exercise, order=1,
    )

    # 4) Crée une soumission-brouillon pour l'étudiant (recommendation)
    StudentSubmission.objects.create(
        assignment=assignment, student=request.user,
        status="brouillon", progress_pct=0,
    )

    messages.success(
        request,
        "Devoir IA créé avec %d questions. Bon courage !" % len(questions),
    )
    return JsonResponse({
        "ok": True,
        "assignment_id": assignment.pk,
        "detail_url": "/etudiant/devoirs/%d/" % assignment.pk,
        "questions_count": len(questions),
    })


@etudiant_required
def student_assignment_pdf(request, pk):
    """Génère le PDF de l'énoncé du devoir."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, HRFlowable
    except ImportError:
        return HttpResponse(
            "reportlab non installé. Ajoutez-le dans requirements.txt.",
            content_type="text/plain", status=500,
        )

    uni = _uni(request)
    assignment = get_object_or_404(Assignment, pk=pk, university=uni)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        'attachment; filename="devoir_%s.pdf"' % assignment.pk
    )

    doc = SimpleDocTemplate(
        response, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
    )
    styles = getSampleStyleSheet()
    story = []

    # En-tête université
    story.append(Paragraph("<b>%s</b>" % uni.name, styles["Heading2"]))
    if assignment.subject:
        story.append(Paragraph("Matière : %s" % assignment.subject, styles["Normal"]))
    if assignment.school_class:
        story.append(Paragraph("Classe : %s" % assignment.school_class, styles["Normal"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color="grey"))
    story.append(Spacer(1, 0.3 * cm))

    # Titre
    story.append(Paragraph(assignment.title, styles["Heading1"]))

    # Métadonnées
    if assignment.deadline:
        story.append(Paragraph(
            "Échéance : <b>%s</b>" % assignment.deadline.strftime("%d/%m/%Y %H:%M"),
            styles["Normal"],
        ))
    story.append(Paragraph("Coefficient : <b>%s</b>" % assignment.coefficient, styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    # Consignes
    if assignment.instructions:
        story.append(Paragraph("<b>Consignes</b>", styles["Heading2"]))
        story.append(Spacer(1, 0.2 * cm))
        for line in assignment.instructions.split("\n"):
            if line.strip():
                story.append(Paragraph(line.strip(), styles["Normal"]))
                story.append(Spacer(1, 0.15 * cm))

    # Barème
    if assignment.rubric:
        story.append(Spacer(1, 0.4 * cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color="lightgrey"))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("<b>Barème : %s</b>" % assignment.rubric.name, styles["Heading2"]))
        for crit in assignment.rubric.criteria.all():
            story.append(Paragraph(
                "• %s : <b>%s pts</b>%s" % (
                    crit.name, crit.points,
                    (" — %s" % crit.description) if crit.description else "",
                ),
                styles["Normal"],
            ))
        story.append(Paragraph(
            "Total : <b>%s pts</b>" % assignment.rubric.total_points,
            styles["Normal"],
        ))

    doc.build(story)
    return response


# ===========================================================================
# ÉTUDIANT — Entraînement (séries recommandées)
# ===========================================================================

@etudiant_required
def student_practice(request):
    uni = _uni(request)

    series_qs = (
        ExerciseSeries.objects.filter(university=uni, visibility="publiee")
        .prefetch_related("items").select_related("rubric")
        .order_by("-updated_at")
    )

    subject_filter = request.GET.get("subject", "").strip()
    if subject_filter:
        series_qs = series_qs.filter(subject__icontains=subject_filter)

    recent_attempts = (
        PracticeAttempt.objects.filter(student=request.user)
        .select_related("series").order_by("-created_at")[:5]
    )

    solved = PracticeAttempt.objects.filter(student=request.user).count()
    good = PracticeAttempt.objects.filter(
        student=request.user, result__in=["reussi", "parfait"]
    ).count()

    subjects = list(
        ExerciseSeries.objects.filter(university=uni, visibility="publiee")
        .exclude(subject="").values_list("subject", flat=True)
        .distinct().order_by("subject")
    )

    return render(request, "exercises/student_practice.html", {
        "series_list": series_qs,
        "recent_attempts": recent_attempts,
        "solved_count": solved,
        "success_rate": int(good / solved * 100) if solved else 0,
        "subjects": subjects,
        "filter_subject": subject_filter,
    })


# ===========================================================================
# ADMIN — Banques & Catégories
# ===========================================================================

@admin_required
def admin_exercise_banks(request):
    uni = _uni(request)
    qs = Exercise.objects.filter(university=uni).select_related("author", "category")
    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(title__icontains=q) | Q(subject__icontains=q) | Q(author__last_name__icontains=q)
        )
    return render(request, "exercises/admin_exercise_banks.html", {
        "exercises": qs.order_by("-updated_at"),
        "total": qs.count(),
        "published": qs.filter(status="publie").count(),
        "ai_count": qs.filter(ai_generated=True).count(),
        "q": q,
    })


@admin_required
def admin_categories(request):
    uni = _uni(request)
    cats = Category.objects.filter(university=uni)
    return render(request, "exercises/admin_categories.html", {
        "categories": cats,
        "total": cats.count(),
        "active_count": cats.filter(is_active=True).count(),
    })


@admin_required
def admin_category_create(request):
    uni = _uni(request)
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            cat = form.save(commit=False)
            cat.university = uni
            cat.save()
            messages.success(request, "Catégorie « %s » créée." % cat.name)
            return redirect("exercises:admin_categories")
    else:
        form = CategoryForm()
    return render(request, "exercises/admin_category_form.html", {"form": form, "action": "Créer"})


@admin_required
def admin_category_update(request, pk):
    uni = _uni(request)
    cat = get_object_or_404(Category, pk=pk, university=uni)
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=cat)
        if form.is_valid():
            form.save()
            messages.success(request, "Catégorie mise à jour.")
            return redirect("exercises:admin_categories")
    else:
        form = CategoryForm(instance=cat)
    return render(request, "exercises/admin_category_form.html", {
        "form": form, "action": "Modifier", "category": cat,
    })


@admin_required
@require_POST
def admin_category_delete(request, pk):
    uni = _uni(request)
    cat = get_object_or_404(Category, pk=pk, university=uni)
    name = cat.name
    cat.delete()
    messages.success(request, "Catégorie « %s » supprimée." % name)
    return redirect("exercises:admin_categories")
