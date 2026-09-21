from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

# Shared classes for the glass-style inputs. The wrapper div in the template
# supplies the glass frame; the input itself stays transparent.
INPUT_CLASS = (
    "auth-input bg-transparent text-sm text-white placeholder:text-white/30 "
    "focus:outline-none w-full"
)


class SignUpForm(UserCreationForm):
    """Sign-up form styled for the liquid-glass auth card."""

    full_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "Elena Rostova", "autocomplete": "name", "class": INPUT_CLASS}
        ),
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "placeholder": "elena@studio.design",
                "autocomplete": "email",
                "class": INPUT_CLASS,
            }
        ),
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "At least 8 characters",
                "autocomplete": "new-password",
                "class": INPUT_CLASS,
            }
        )
    )

    password2 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Repeat your password",
                "autocomplete": "new-password",
                "class": INPUT_CLASS,
            }
        )
    )

    class Meta:
        model = User
        fields = ("full_name", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["email"]
        user.email = email
        user.username = email
        user.first_name = self.cleaned_data.get("full_name", "")
        if commit:
            user.save()
        return user


class SignInForm(AuthenticationForm):
    """Sign-in form keyed on email instead of username."""

    username = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(
            attrs={
                "placeholder": "name@company.com",
                "autofocus": True,
                "class": INPUT_CLASS,
            }
        ),
    )

    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022",
                "autocomplete": "current-password",
                "class": INPUT_CLASS,
            }
        )
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "No account matches that email and password.",
    }
