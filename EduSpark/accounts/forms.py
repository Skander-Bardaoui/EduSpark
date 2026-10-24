from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

# Classes exactes extraites des maquettes stitch (dossier stitch/).
# Connexion : inputs sur fond transparent dans un wrapper bg-surface-container-low.
LOGIN_INPUT_CLASS = (
    "w-full pl-11 pr-4 py-3 bg-transparent rounded-lg font-body-md text-body-md "
    "text-on-surface placeholder:text-outline outline-none"
)
LOGIN_PASSWORD_CLASS = (
    "w-full pl-11 pr-11 py-3 bg-transparent rounded-lg font-body-md text-body-md "
    "text-on-surface placeholder:text-outline outline-none"
)
# Inscription : inputs bg-surface-container-low.
SIGNUP_INPUT_CLASS = (
    "w-full pl-10 pr-4 py-2.5 bg-surface-container-low focus:bg-surface-container-lowest "
    "rounded-lg font-body-md text-body-md text-on-surface placeholder:text-outline "
    "outline-none transition-all focus:shadow-[0_0_0_2px_rgba(0,88,190,0.3)]"
)
SIGNUP_PASSWORD_CLASS = (
    "w-full pl-10 pr-10 py-2.5 bg-surface-container-low focus:bg-surface-container-lowest "
    "rounded-lg font-body-md text-body-md text-on-surface placeholder:text-outline "
    "outline-none transition-all focus:shadow-[0_0_0_2px_rgba(0,88,190,0.3)]"
)


class SignUpForm(UserCreationForm):
    """Sign-up form fidèle à la maquette stitch eduspark_inscription."""

    ROLE_CHOICES = (
        ("etudiant", "Apprenant"),
        ("prof", "Enseignant"),
    )

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        required=False,
        initial="etudiant",
    )

    full_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={
                "id": "fullName",
                "placeholder": "ex. Alexandre Dumas",
                "autocomplete": "name",
                "class": SIGNUP_INPUT_CLASS,
            }
        ),
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "id": "email",
                "placeholder": "ex. alexandre@universite.fr",
                "autocomplete": "email",
                "class": SIGNUP_INPUT_CLASS,
            }
        ),
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "id": "password",
                "placeholder": "••••••••••••",
                "autocomplete": "new-password",
                "class": SIGNUP_PASSWORD_CLASS,
            }
        )
    )

    # Maquette stitch : un seul champ mot de passe visible. password2 est
    # synchronisé en JS (champ caché) pour satisfaire UserCreationForm.
    password2 = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "password2"}),
    )

    class Meta:
        model = User
        fields = ("full_name", "email", "password1", "password2")

    def clean(self):
        cleaned = super().clean()
        # La maquette n'affiche qu'un seul champ mot de passe : si password2
        # (caché) est vide, on le remplit avec password1 avant validation.
        if not cleaned.get("password2") and cleaned.get("password1"):
            cleaned["password2"] = cleaned["password1"]
        return cleaned

    def clean_role(self):
        role = self.cleaned_data.get("role") or "etudiant"
        # L'inscription publique ne peut pas créer de compte admin.
        if role not in ("etudiant", "prof"):
            raise forms.ValidationError("Rôle invalide.")
        return role

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cet e-mail.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["email"]
        user.email = email
        user.username = email
        user.first_name = self.cleaned_data.get("full_name", "")
        if commit:
            user.save()
        # Le signal post_save crée le profil : on y applique le rôle choisi.
        from .models import Profil
        role = self.cleaned_data.get("role") or "etudiant"
        if role not in ("etudiant", "prof"):
            role = "etudiant"
        profil, _created = Profil.objects.get_or_create(user=user)
        if profil.role != role:
            profil.role = role
            profil.save()
        else:
            profil.sync_group()
        return user


class SignInForm(AuthenticationForm):
    """Sign-in form calqué sur la maquette stitch eduspark_connexion."""

    username = forms.EmailField(
        label="Identifiant étudiant ou adresse e-mail",
        widget=forms.EmailInput(
            attrs={
                "id": "login-email",
                "placeholder": "nom@universite.fr ou nom@domaine.com",
                "autofocus": True,
                "autocomplete": "email",
                "class": LOGIN_INPUT_CLASS,
            }
        ),
    )

    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "id": "login-password",
                "placeholder": "••••••••••••",
                "autocomplete": "current-password",
                "class": LOGIN_PASSWORD_CLASS,
            }
        )
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Aucun compte ne correspond à cet e-mail et ce mot de passe.",
    }
