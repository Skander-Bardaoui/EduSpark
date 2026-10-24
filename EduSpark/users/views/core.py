from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ..forms import ProfileForm
from ..models import Invitation, Membership, ProfessorProfile, SchoolClass, StudentProfile, University
from ..services.ai import AIUnavailable, generate_profile_bio
from ..tenancy import Role, has_role, is_platform_admin, switch_tenant
from .mixins import redirect_next

User = get_user_model()


@login_required
def dashboard(request):
    user, university = request.user, request.university
    context = {"pending_memberships": user.memberships.filter(is_active=False).select_related("university")}

    if is_platform_admin(user):
        context["platform"] = {
            "universities": University.objects.count(),
            "active_universities": University.objects.filter(is_active=True).count(),
            "accounts": User.objects.count(),
            "pending_invitations": Invitation.objects.filter(status=Invitation.STATUS_PENDING).count(),
        }
        context["latest_universities"] = University.objects.order_by("-created_at")[:5]

    if university is not None:
        members = Membership.objects.filter(university=university)
        context["stats"] = {
            "professors": members.filter(role=Role.PROFESSOR, is_active=True).count(),
            "students": members.filter(role=Role.STUDENT, is_active=True).count(),
            "classes": SchoolClass.objects.filter(university=university).count(),
            "pending": members.filter(is_active=False).count(),
            "invitations": Invitation.objects.filter(university=university, status=Invitation.STATUS_PENDING).count(),
        }
        if has_role(request, Role.UNIVERSITY_ADMIN):
            context["to_validate"] = (
                members.filter(is_active=False).select_related("user").order_by("-created_at")[:8]
            )
        membership = request.membership
        if membership is not None and membership.role == Role.PROFESSOR:
            profile = ProfessorProfile.objects.filter(membership=membership).first()
            context["my_classes"] = profile.classes.all() if profile else []
        elif membership is not None and membership.role == Role.STUDENT:
            profile = StudentProfile.objects.filter(membership=membership).first()
            context["my_groups"] = profile.groups.select_related("school_class") if profile else []
    return render(request, "users/dashboard.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def university_switch(request):
    """Choix de l'université courante (tenant) pour la session."""
    if is_platform_admin(request.user):
        choices = University.objects.all()
    else:
        choices = University.objects.filter(
            is_active=True,
            pk__in=request.user.memberships.filter(is_active=True).values("university"),
        )
    if request.method == "POST":
        university = choices.filter(pk=request.POST.get("university")).first()
        if university is None:
            raise Http404("Université inaccessible.")
        switch_tenant(request, university)
        messages.success(request, f"Vous travaillez maintenant dans : {university}.")
        return redirect_next(request, "users:dashboard")
    return render(request, "users/university_switch.html", {"choices": choices})


def _profile_facts(request):
    """Faits du profil métier courant, transmis à l'IA."""
    membership = request.membership
    if membership is None:
        return "", {}
    if membership.role == Role.PROFESSOR:
        p = ProfessorProfile.objects.filter(membership=membership).first()
        if p:
            return membership.get_role_display(), {
                "Département": p.department, "Spécialité": p.speciality, "Grade": p.get_grade_display(),
            }
    if membership.role == Role.STUDENT:
        p = StudentProfile.objects.filter(membership=membership).first()
        if p:
            return membership.get_role_display(), {"Filière": p.program, "Promotion": p.promotion}
    return membership.get_role_display(), {}


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    """« Mon profil » + bouton IA : la suggestion n'est jamais enregistrée
    automatiquement — l'utilisateur la garde, la modifie ou la refuse."""
    user = request.user
    suggestion, ai_error = "", ""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=user)
        if request.POST.get("action") == "ai_bio":
            role_label, extra = _profile_facts(request)
            try:
                suggestion = generate_profile_bio(
                    user, university=request.university, role_label=role_label,
                    extra=extra, draft=request.POST.get("bio", ""),
                )
            except AIUnavailable as exc:
                ai_error = str(exc)
            # Le formulaire reste lié aux données saisies : rien n'est perdu.
        elif form.is_valid():
            form.save()
            messages.success(request, "Profil enregistré.")
            return redirect("users:profile")
    else:
        form = ProfileForm(instance=user)
    memberships = user.memberships.select_related("university").order_by("university__name")
    return render(request, "users/profile.html", {
        "form": form, "suggestion": suggestion, "ai_error": ai_error, "memberships": memberships,
    })
