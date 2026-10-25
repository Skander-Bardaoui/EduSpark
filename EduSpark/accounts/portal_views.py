"""Portails professeur et étudiant : profil, classes, universités, paramètres."""

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import PasswordChangeStyledForm, ProfileForm, ProfessorProfileForm, StudentProfileForm
from .models import ProfessorProfile, StudentProfile
from .tenancy import Role, is_platform_admin, request_home_url, switch_tenant, tenant_required
from .view_mixins import redirect_next


@login_required
@require_http_methods(["GET", "POST"])
def university_switch(request):
    """Choix de l'université courante (tenant) pour la session."""
    if is_platform_admin(request.user):
        messages.info(request, "L'admin plateforme n'est rattaché à aucune université.")
        return redirect("portal:admin_universities")

    if getattr(request, "university_role", None) == Role.UNIVERSITY_ADMIN:
        messages.info(
            request,
            "Votre compte d'administration est rattaché à %s et ne peut pas changer d'université."
            % request.university,
        )
        return redirect(request_home_url(request))

    memberships = request.user.memberships.filter(
        is_active=True, university__is_active=True,
    ).select_related("university").order_by("university__name")

    choices = [
        {
            "university": membership.university,
            "role": membership.get_role_display(),
            "current": (
                request.university is not None
                and request.university.pk == membership.university_id
            ),
        }
        for membership in memberships
    ]

    if request.method == "POST":
        target = None
        if str(request.POST.get("university", "")).isdigit():
            wanted = int(request.POST["university"])
            target = next((row["university"] for row in choices if row["university"].pk == wanted), None)
        if target is None:
            messages.error(request, "Cette université ne vous est pas accessible.")
        else:
            switch_tenant(request, target)
            messages.success(request, "Vous travaillez maintenant dans : %s." % target)
            return redirect_next(request, request_home_url(request))

    return render(request, "accounts/university_switch.html", {
        "choices": choices,
        "pending_memberships": request.user.memberships.filter(
            is_active=False,
        ).select_related("university").order_by("university__name"),
    })


@tenant_required(Role.STUDENT)
def student_class(request):
    profile = None
    if request.membership is not None:
        profile = StudentProfile.objects.filter(membership=request.membership).first()
    groups = []
    if profile is not None:
        groups = list(profile.groups.select_related("school_class").prefetch_related(
            "school_class__professors__membership__user", "students__membership__user",
        ).order_by("school_class__name", "name"))
    primary_class = groups[0].school_class if groups else None
    class_groups = list(primary_class.groups.all()) if primary_class is not None else []
    classmates = []
    if groups:
        classmates = list(
            StudentProfile.objects.filter(
                university=request.university, groups__in=groups,
            ).exclude(pk=profile.pk).distinct().select_related(
                "membership__user",
            ).prefetch_related("groups__school_class").order_by(
                "membership__user__last_name", "membership__user__first_name",
            )
        )
    stats = {
        "groups": len(groups),
        "classmates": len(classmates),
        "classes": len({group.school_class_id for group in groups}),
    }
    return render(request, "accounts/student_class.html", {
        "profile": profile,
        "groups": groups,
        "classmates": classmates,
        "primary_class": primary_class,
        "class_groups": class_groups,
        "stats": stats,
    })


@tenant_required(Role.PROFESSOR)
def prof_universities(request):
    rows = []
    for membership in request.user.memberships.select_related("university").order_by("university__name"):
        profile = ProfessorProfile.objects.filter(membership=membership).first()
        classes = []
        if profile is not None and membership.is_active:
            classes = profile.classes.filter(university=membership.university).order_by("-academic_year", "name")
        rows.append({
            "membership": membership,
            "profile": profile,
            "classes": classes,
            "current": (
                request.university is not None
                and membership.university_id == request.university.pk
            ),
        })
    stats = {
        "universities": len(rows),
        "active": sum(1 for row in rows if row["membership"].is_active),
        "classes": sum(len(row["classes"]) for row in rows),
        "departments": len({
            row["profile"].department for row in rows
            if row["profile"] is not None and row["profile"].department
        }),
    }
    return render(request, "accounts/prof_universities.html", {"rows": rows, "stats": stats})


@tenant_required(Role.PROFESSOR)
def prof_classes(request):
    profile = None
    if request.membership is not None:
        profile = ProfessorProfile.objects.filter(membership=request.membership).first()
    classes = []
    groups = []
    if profile is not None:
        classes = list(profile.classes.filter(university=request.university).annotate(
            student_total=Count("groups__students", distinct=True),
        ).prefetch_related(
            "groups__students__membership__user",
        ).order_by("-academic_year", "name"))
        for school_class in classes:
            groups.extend(school_class.groups.all())
    stats = {
        "classes": len(classes),
        "students": StudentProfile.objects.filter(
            university=request.university, groups__school_class__in=classes,
        ).distinct().count() if classes else 0,
        "groups": len(groups),
    }
    return render(request, "accounts/prof_classes.html", {
        "profile": profile, "classes": classes, "groups": groups, "stats": stats,
    })


def _save_profile_forms(request, account_form, profile_form, success_url):
    valid = account_form.is_valid()
    if profile_form is not None:
        valid = profile_form.is_valid() and valid
    if valid:
        account_form.save()
        if profile_form is not None:
            profile_form.save()
        messages.success(request, "Profil enregistré.")
        return redirect(success_url)
    return None


@tenant_required(Role.PROFESSOR)
@require_http_methods(["GET", "POST"])
def prof_profile(request):
    user = request.user
    profile = (
        ProfessorProfile.objects.filter(membership=request.membership).first()
        if request.membership is not None else None
    )
    if request.method == "POST":
        account_form = ProfileForm(request.POST, instance=user)
        profile_form = (
            ProfessorProfileForm(request.POST, instance=profile, admin=False)
            if profile is not None else None
        )
        response = _save_profile_forms(request, account_form, profile_form, "portal:prof_profile")
        if response is not None:
            return response
    else:
        account_form = ProfileForm(instance=user)
        profile_form = (
            ProfessorProfileForm(instance=profile, admin=False) if profile is not None else None
        )
    return render(request, "accounts/prof_profile.html", {
        "account_form": account_form,
        "profile_form": profile_form,
        "profile": profile,
        "memberships": user.memberships.select_related("university").order_by("university__name"),
    })


@tenant_required(Role.STUDENT)
@require_http_methods(["GET", "POST"])
def student_profile(request):
    user = request.user
    profile = (
        StudentProfile.objects.filter(membership=request.membership).first()
        if request.membership is not None else None
    )
    if request.method == "POST":
        account_form = ProfileForm(request.POST, instance=user)
        profile_form = (
            StudentProfileForm(request.POST, instance=profile, admin=False)
            if profile is not None else None
        )
        response = _save_profile_forms(request, account_form, profile_form, "portal:student_profile")
        if response is not None:
            return response
    else:
        account_form = ProfileForm(instance=user)
        profile_form = (
            StudentProfileForm(instance=profile, admin=False) if profile is not None else None
        )
    return render(request, "accounts/student_profile.html", {
        "account_form": account_form,
        "profile_form": profile_form,
        "profile": profile,
        "memberships": user.memberships.select_related("university").order_by("university__name"),
        "groups": (
            profile.groups.select_related("school_class").order_by("school_class__name", "name")
            if profile is not None else []
        ),
    })


@tenant_required(Role.PROFESSOR)
@require_http_methods(["GET", "POST"])
def prof_settings(request):
    profile = (
        ProfessorProfile.objects.filter(membership=request.membership).first()
        if request.membership is not None else None
    )
    form = PasswordChangeStyledForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)
        messages.success(request, "Mot de passe mis à jour.")
        return redirect("portal:prof_settings")
    return render(request, "accounts/prof_settings.html", {
        "form": form,
        "profile": profile,
        "memberships": request.user.memberships.select_related("university").order_by("university__name"),
    })
