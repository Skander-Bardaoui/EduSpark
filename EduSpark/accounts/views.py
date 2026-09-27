from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .decorators import role_home_url
from .forms import SignInForm, SignUpForm


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Page Connexion — maquette stitch eduspark_connexion."""
    if request.user.is_authenticated:
        return redirect("landing:index")
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
            return redirect(role_home_url(user))
    else:
        form = SignInForm()
    return render(request, "accounts/login.html", {"form": form})


@require_http_methods(["GET", "POST"])
def signup_view(request):
    """Page Inscription — maquette stitch eduspark_inscription."""
    if request.user.is_authenticated:
        return redirect("landing:index")
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
            messages.success(request, "Bienvenue sur EduSpark ! Votre compte a été créé.")
            return redirect(role_home_url(user))
    else:
        initial = {}
        # Pré-remplissage depuis la landing (hero email -> ?email=...)
        if request.GET.get("email"):
            initial["email"] = request.GET.get("email")
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
