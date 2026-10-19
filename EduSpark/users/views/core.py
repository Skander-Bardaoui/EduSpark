from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ..forms import ProfessorSelfForm, ProfileForm, StudentSelfForm, UniversitySwitchForm
from ..models import Invitation, Membership, ProfessorProfile, SchoolClass, StudentProfile, University
from ..services.ai import AIUnavailable, generate_profile_bio
from ..tenancy import Role, has_role, is_platform_admin, switch_tenant
from .mixins import redirect_next

User = get_user_model()


@login_required
def dashboard(request):
    user, university = request.user, request.university
    pending = user.memberships.filter(is_active=False).select_related("university")
    context = {
        "pending_memberships": pending,
        "awaiting_verification": not user.email_verified and any(m.awaiting_email_verification for m in pending),
    }

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
        # Les relations sont refiltrées sur l'université courante : même un lien
        # incohérent (import, back-office) n'expose rien d'une autre université.
        membership = request.membership
        if membership is not None and membership.role == Role.PROFESSOR:
            profile = ProfessorProfile.objects.filter(membership=membership).first()
            context["my_classes"] = profile.classes.filter(university=university) if profile else []
        elif membership is not None and membership.role == Role.STUDENT:
            profile = StudentProfile.objects.filter(membership=membership).first()
            context["my_groups"] = (
                profile.groups.filter(university=university).select_related("school_class") if profile else []
            )
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
        form = UniversitySwitchForm(request.POST, queryset=choices)
        if form.is_valid():
            university = form.cleaned_data["university"]
            switch_tenant(request, university)
            messages.success(request, f"Vous travaillez maintenant dans : {university}.")
            return redirect_next(request, "users:dashboard")
        messages.error(request, "Université invalide ou inaccessible.")
        return render(request, "users/university_switch.html", {"choices": choices}, status=400)
    return render(request, "users/university_switch.html", {"choices": choices})


def _academic_form(request, data=None):
    """Formulaire du profil métier de l'université courante (ou None)."""
    membership = request.membership
    if membership is None:
        return None
    if membership.role == Role.PROFESSOR:
        profile = ProfessorProfile.objects.filter(membership=membership).first()
        return ProfessorSelfForm(data, instance=profile, prefix="academic") if profile else None
    if membership.role == Role.STUDENT:
        profile = StudentProfile.objects.filter(membership=membership).first()
        return StudentSelfForm(data, instance=profile, prefix="academic") if profile else None
    return None


def _profile_facts(request, academic_form):
    """Faits transmis à l'IA : ceux saisis à l'écran s'ils sont valides, sinon ceux enregistrés."""
    membership = request.membership
    if membership is None:
        return "", {}
    extra = {}
    if academic_form is not None:
        if academic_form.is_bound:
            academic_form.is_valid()  # copie les valeurs valides sur l'instance (non enregistrée)
        p = academic_form.instance
        if isinstance(p, ProfessorProfile):
            extra = {"Département": p.department, "Spécialité": p.speciality, "Grade": p.get_grade_display()}
        else:
            extra = {"Filière": p.program, "Promotion": p.promotion}
    return membership.get_role_display(), extra


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    """« Mon profil » : compte + profil académique de l'université courante,
    et le bouton IA — la suggestion n'est jamais enregistrée automatiquement."""
    user = request.user
    suggestion, ai_error = "", ""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=user)
        academic_form = _academic_form(request, request.POST)
        if request.POST.get("action") == "ai_bio":
            role_label, extra = _profile_facts(request, academic_form)
            try:
                suggestion = generate_profile_bio(
                    user, university=request.university, role_label=role_label,
                    extra=extra, draft=request.POST.get("bio", ""),
                )
            except AIUnavailable as exc:
                ai_error = str(exc)
            # Les formulaires restent liés aux données saisies : rien n'est perdu.
        elif form.is_valid() and (academic_form is None or academic_form.is_valid()):
            form.save()
            if academic_form is not None:
                academic_form.save()
            messages.success(request, "Profil enregistré.")
            return redirect("users:profile")
    else:
        form = ProfileForm(instance=user)
        academic_form = _academic_form(request)
    memberships = user.memberships.select_related("university").order_by("university__name")
    return render(request, "users/profile.html", {
        "form": form, "academic_form": academic_form, "suggestion": suggestion,
        "ai_error": ai_error, "memberships": memberships,
    })
