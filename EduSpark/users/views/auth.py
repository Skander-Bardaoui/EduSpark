from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from ..forms import InvitationSignupForm, SignInForm, SignUpForm
from ..models import Invitation
from ..tenancy import switch_tenant
from .mixins import redirect_next

User = get_user_model()


def home_url(user):
    """Accueil après connexion / inscription : le tableau de bord."""
    return reverse("users:dashboard")


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Page Connexion — maquette stitch eduspark_connexion."""
    if request.user.is_authenticated:
        return redirect("users:dashboard")
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
            messages.success(request, f"Bon retour parmi nous, {user.first_name or user.email} !")
            return redirect_next(request, home_url(user))
    else:
        form = SignInForm()
    return render(request, "users/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_http_methods(["GET", "POST"])
def signup_view(request):
    """Page Inscription — maquette stitch eduspark_inscription."""
    if request.user.is_authenticated:
        return redirect("users:dashboard")
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
            membership = user.memberships.first()
            if membership and membership.is_active:
                messages.success(request, f"Bienvenue sur EduSpark ! Vous avez rejoint {membership.university}.")
            else:
                messages.info(
                    request,
                    "Votre compte est créé. Votre inscription doit maintenant être validée "
                    "par l'administration de votre université.",
                )
            return redirect(home_url(user))
    else:
        initial = {}
        # Pré-remplissage depuis la landing (hero email -> ?email=...)
        if request.GET.get("email"):
            initial["email"] = request.GET.get("email")
        form = SignUpForm(initial=initial)
    return render(request, "users/signup.html", {"form": form})


@require_http_methods(["GET", "POST"])
def auth_view(request):
    """Ancienne route combinée : redirige vers login ou signup selon ?mode=."""
    if request.GET.get("mode") == "signup":
        return redirect("users:signup")
    return redirect("users:login")


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
        return render(request, "users/invitation_accept.html", context)

    user = request.user
    if user.is_authenticated:
        if user.email.lower() != invitation.email:
            context["state"] = "wrong_account"
            return render(request, "users/invitation_accept.html", context)
        if request.method == "POST":
            invitation.accept(user)
            switch_tenant(request, invitation.university)
            messages.success(request, f"Vous avez rejoint {invitation.university} ({invitation.get_role_display()}).")
            return redirect("users:dashboard")
        context["state"] = "confirm"
        return render(request, "users/invitation_accept.html", context)

    if User.objects.filter(email__iexact=invitation.email).exists():
        context["state"] = "login"
        context["login_url"] = f"{reverse('users:login')}?next={request.path}"
        return render(request, "users/invitation_accept.html", context)

    new_user = User(email=invitation.email, username=invitation.email)
    form = InvitationSignupForm(new_user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        new_user.first_name = form.cleaned_data["first_name"]
        new_user.last_name = form.cleaned_data["last_name"]
        form.save()
        invitation.accept(new_user)
        login(request, new_user, backend="django.contrib.auth.backends.ModelBackend")
        switch_tenant(request, invitation.university)
        messages.success(request, f"Bienvenue ! Vous avez rejoint {invitation.university}.")
        return redirect("users:dashboard")
    context.update({"state": "signup", "form": form})
    return render(request, "users/invitation_accept.html", context)
