from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import InvitationSignupForm, SignInForm, SignUpForm
from .models import Invitation, University
from .tenancy import request_home_url, resolve_tenant, switch_tenant
from .view_mixins import redirect_next

User = get_user_model()


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Page Connexion — maquette stitch eduspark_connexion."""
    if request.user.is_authenticated:
        return redirect(request_home_url(request))
    if request.method == "POST":
        form = SignInForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # "Se souvenir de moi" : session persistante (2 semaines) ou
            # expiration a la fermeture du navigateur.
            if request.POST.get("remember"):
                request.session.set_expiry(1209600)
            else:
                request.session.set_expiry(0)
            resolve_tenant(request)
            messages.success(request, f"Bon retour parmi nous, {user.first_name or user.email} !")
            return redirect_next(request, request_home_url(request))
    else:
        form = SignInForm()
    return render(request, "accounts/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_http_methods(["GET", "POST"])
def signup_view(request):
    """Page Inscription — maquette stitch eduspark_inscription."""
    if request.user.is_authenticated:
        return redirect(request_home_url(request))
    if request.method == "POST":
        data = request.POST.copy()
        # La maquette n'a qu'un seul champ password visible : on synchronise
        # password2 côté serveur aussi (en plus du JS) pour UserCreationForm.
        if data.get("password1") and not data.get("password2"):
            data["password2"] = data["password1"]
        form = SignUpForm(data)
        if form.is_valid():
            user = form.save()
            login(request, user)
            resolve_tenant(request)
            membership = user.memberships.select_related("university").first()
            if membership and membership.is_active:
                messages.success(
                    request,
                    "Bienvenue sur EduSpark ! Vous avez rejoint %s." % membership.university,
                )
            elif membership:
                messages.info(
                    request,
                    "Votre compte est créé. Votre inscription à %s doit maintenant être "
                    "validée par l'administration de l'université." % membership.university,
                )
            else:
                messages.success(request, "Bienvenue sur EduSpark ! Votre compte a été créé.")
            return redirect(request_home_url(request))
    else:
        initial = {}
        # Pré-remplissage depuis la landing (hero email -> ?email=...) et
        # depuis la page de choix d'université (?university=<slug>).
        if request.GET.get("email"):
            initial["email"] = request.GET.get("email")
        wanted = request.GET.get("university", "").strip()
        if wanted:
            university = None
            if wanted.isdigit():
                university = University.objects.filter(is_active=True, pk=wanted).first()
            if university is None:
                university = University.objects.filter(is_active=True, slug=wanted).first()
            if university is not None:
                initial["university"] = university.pk
        form = SignUpForm(initial=initial)
    return render(request, "accounts/signup.html", {"form": form})


@require_http_methods(["GET", "POST"])
def auth_view(request):
    """Ancienne route combinée : redirige vers login ou signup selon ?mode=."""
    if request.GET.get("mode") == "signup":
        return redirect("accounts:signup")
    return redirect("accounts:login")


def logout_view(request):
    logout(request)
    messages.success(request, "Vous êtes déconnecté. À bientôt !")
    return redirect("landing:index")


@require_http_methods(["GET", "POST"])
def invitation_accept(request, token):
    """Lien reçu par e-mail : rejoindre l'université avec le rôle prévu.

    - invitation expirée / révoquée / déjà utilisée : message ;
    - connecté avec le bon e-mail : confirmation puis appartenance créée ;
    - pas de compte : formulaire de création (e-mail imposé) ;
    - compte existant mais non connecté : invitation à se connecter.
    """
    invitation = get_object_or_404(Invitation.objects.select_related("university"), token=token)
    context = {"invitation": invitation}
    if not invitation.is_usable:
        context["state"] = "invalid"
        return render(request, "accounts/invitation_accept.html", context)

    user = request.user
    if user.is_authenticated:
        if user.email.lower() != invitation.email:
            context["state"] = "wrong_account"
            return render(request, "accounts/invitation_accept.html", context)
        if request.method == "POST":
            invitation.accept(user)
            switch_tenant(request, invitation.university)
            messages.success(
                request,
                "Vous avez rejoint %s (%s)." % (invitation.university, invitation.get_role_display()),
            )
            return redirect(request_home_url(request))
        context["state"] = "confirm"
        return render(request, "accounts/invitation_accept.html", context)

    if User.objects.filter(email__iexact=invitation.email).exists():
        context["state"] = "login"
        context["login_url"] = "%s?next=%s" % (reverse("accounts:login"), request.path)
        return render(request, "accounts/invitation_accept.html", context)

    new_user = User(email=invitation.email, username=invitation.email)
    form = InvitationSignupForm(new_user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        new_user.first_name = form.cleaned_data["first_name"]
        new_user.last_name = form.cleaned_data["last_name"]
        form.save()
        invitation.accept(new_user)
        login(request, new_user, backend="django.contrib.auth.backends.ModelBackend")
        switch_tenant(request, invitation.university)
        messages.success(
            request,
            "Bienvenue ! Vous avez rejoint %s." % invitation.university,
        )
        return redirect(request_home_url(request))
    context.update({"state": "signup", "form": form})
    return render(request, "accounts/invitation_accept.html", context)
