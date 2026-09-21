from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import SignInForm, SignUpForm


@require_http_methods(["GET", "POST"])
def auth_view(request):
    """
    Combined Sign In / Create Account page.

    Shows the sign-in panel by default; when the visitor arrives from the
    "Sign Up" button on the landing page (?mode=signup) the create-account
    panel is shown instead. Both forms post back to this same URL.
    """
    mode = "signup" if request.GET.get("mode") == "signup" else "login"

    if request.method == "POST":
        mode = request.POST.get("mode", "login")

        if mode == "signup":
            signup_form = SignUpForm(request.POST)
            signin_form = SignInForm()
            if signup_form.is_valid():
                user = signup_form.save()
                login(request, user)
                messages.success(request, "Welcome to EduSpark! Your account has been created.")
                return redirect("landing:index")
        else:
            signin_form = SignInForm(request, data=request.POST)
            signup_form = SignUpForm()
            if signin_form.is_valid():
                user = signin_form.get_user()
                login(request, user)
                messages.success(request, f"Welcome back, {user.get_full_name() or user.email}!")
                return redirect("landing:index")
    else:
        signin_form = SignInForm()
        signup_form = SignUpForm()

    return render(
        request,
        "accounts/auth.html",
        {
            "signin_form": signin_form,
            "signup_form": signup_form,
            "mode": mode,
        },
    )
