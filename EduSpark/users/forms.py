from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm

from .models import (
    Invitation, Membership, ProfessorProfile, SchoolClass, StudentGroup, StudentProfile, University,
)
from .tenancy import MEMBERSHIP_ROLES, Role

User = get_user_model()

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
# Pages de gestion : même langage visuel que l'inscription, sans icône.
FIELD_CLASS = (
    "w-full px-4 py-2.5 bg-surface-container-low focus:bg-surface-container-lowest "
    "rounded-lg font-body-md text-body-md text-on-surface placeholder:text-outline "
    "outline-none transition-all focus:shadow-[0_0_0_2px_rgba(0,88,190,0.3)]"
)
CHECKBOX_CLASS = "w-4 h-4 rounded accent-primary cursor-pointer"


class StyledFormMixin:
    """Applique les classes Tailwind du design system à tous les widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.HiddenInput):
                continue
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                widget.attrs.setdefault("class", CHECKBOX_CLASS)
                continue
            widget.attrs.setdefault("class", FIELD_CLASS)
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 4)


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

class SignUpForm(UserCreationForm):
    """Inscription publique (maquette stitch eduspark_inscription).

    Crée le compte et une demande d'appartenance à l'université choisie.
    La demande est validée par l'admin université — sauf pour un étudiant
    dont l'e-mail correspond au domaine officiel de l'université.
    """

    ROLE_CHOICES = (
        (Role.STUDENT.value, "Apprenant"),
        (Role.PROFESSOR.value, "Enseignant"),
    )

    role = forms.ChoiceField(choices=ROLE_CHOICES, required=False, initial=Role.STUDENT.value)

    university = forms.ModelChoiceField(
        queryset=University.objects.filter(is_active=True),
        empty_label="Choisissez votre université",
        widget=forms.Select(attrs={"id": "university", "class": SIGNUP_INPUT_CLASS}),
        error_messages={"required": "Choisissez votre université."},
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
        role = self.cleaned_data.get("role") or Role.STUDENT.value
        # L'inscription publique ne peut pas créer de compte admin.
        if role not in (Role.STUDENT, Role.PROFESSOR):
            raise forms.ValidationError("Rôle invalide.")
        return role

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cet e-mail.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["email"]
        user.email = email
        user.username = email
        first, _, last = self.cleaned_data.get("full_name", "").strip().partition(" ")
        user.first_name, user.last_name = first, last
        user.save()
        university = self.cleaned_data["university"]
        role = self.cleaned_data.get("role") or Role.STUDENT.value
        domain = email.rsplit("@", 1)[-1]
        # Le domaine déclaré ne suffit pas : l'appartenance reste inactive tant
        # que la possession de l'adresse n'est pas prouvée (users.verification).
        official_domain = role == Role.STUDENT and bool(university.email_domain) and domain == university.email_domain
        membership = Membership.objects.create(
            user=user, university=university, role=role, is_active=False,
            awaiting_email_verification=official_domain,
        )
        membership.ensure_profile()
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

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


# ---------------------------------------------------------------------------
# Universités et comptes (admin plateforme)
# ---------------------------------------------------------------------------

class UniversityForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = University
        fields = ("name", "code", "city", "country", "email_domain", "website", "description", "is_active")


class UniversityAdminEditForm(UniversityForm):
    """Ce que l'admin université peut modifier dans sa propre université."""

    class Meta(UniversityForm.Meta):
        fields = ("code", "city", "country", "website", "description")


class AccountForm(StyledFormMixin, forms.ModelForm):
    is_platform_admin = forms.BooleanField(
        label="Admin plateforme", required=False,
        help_text="Donne accès à toutes les universités et au back-office.",
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone", "bio", "is_active")
        labels = {"first_name": "Prénom", "last_name": "Nom", "is_active": "Compte actif"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_platform_admin"].initial = self.instance.is_superuser

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Un autre compte utilise déjà cet e-mail.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email
        if "email" in self.changed_data:
            user.email_verified = False
        user.is_superuser = user.is_staff = self.cleaned_data["is_platform_admin"]
        if commit:
            user.save()
        return user


class ProfileForm(StyledFormMixin, forms.ModelForm):
    """Chacun édite son propre profil."""

    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone", "bio")
        labels = {"first_name": "Prénom", "last_name": "Nom"}
        widgets = {"bio": forms.Textarea(attrs={"rows": 6, "id": "id_bio"})}
        help_texts = {"bio": "Quelques phrases visibles par les membres de vos universités."}


class ProfessorSelfForm(StyledFormMixin, forms.ModelForm):
    """Le professeur édite son profil dans l'université courante."""

    class Meta:
        model = ProfessorProfile
        fields = ("department", "speciality", "grade")


class StudentSelfForm(StyledFormMixin, forms.ModelForm):
    """L'étudiant édite filière et promotion (le matricule reste géré par l'administration)."""

    class Meta:
        model = StudentProfile
        fields = ("program", "promotion")


class UniversitySwitchForm(forms.Form):
    """Valide l'université demandée parmi celles accessibles (id invalide → erreur de formulaire)."""

    university = forms.ModelChoiceField(queryset=University.objects.none())

    def __init__(self, *args, queryset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["university"].queryset = queryset


# ---------------------------------------------------------------------------
# Professeurs et étudiants (admin université)
# ---------------------------------------------------------------------------

class _MemberCreateForm(StyledFormMixin, forms.Form):
    """Création d'un membre : réutilise le compte si l'e-mail existe déjà
    (un professeur peut enseigner dans plusieurs universités)."""

    email = forms.EmailField(label="E-mail")
    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)

    role = None  # défini par les sous-classes

    def __init__(self, *args, university=None, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Membership.objects.filter(user__email__iexact=email, university=self.university).exists():
            raise forms.ValidationError("Cette personne est déjà membre de l'université.")
        return email

    def save_member(self):
        """Retourne (membership, account_created)."""
        email = self.cleaned_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            user = User(
                email=email, username=email,
                first_name=self.cleaned_data["first_name"], last_name=self.cleaned_data["last_name"],
            )
            user.set_unusable_password()
            user.save()
        membership = Membership.objects.create(user=user, university=self.university, role=self.role)
        profile = membership.ensure_profile()
        for name in self.profile_fields:
            setattr(profile, name, self.cleaned_data.get(name, ""))
        profile.save()
        return membership, created


class ProfessorCreateForm(_MemberCreateForm):
    role = Role.PROFESSOR
    profile_fields = ("department", "speciality", "grade")

    department = forms.CharField(label="Département", max_length=120, required=False)
    speciality = forms.CharField(label="Spécialité", max_length=120, required=False)
    grade = forms.ChoiceField(label="Grade", choices=(("", "—"),) + ProfessorProfile.GRADE_CHOICES, required=False)


class StudentCreateForm(_MemberCreateForm):
    role = Role.STUDENT
    profile_fields = ("student_number", "program", "promotion")

    student_number = forms.CharField(label="Matricule", max_length=40, required=False)
    program = forms.CharField(label="Filière", max_length=120, required=False)
    promotion = forms.CharField(label="Promotion", max_length=20, required=False)

    def clean_student_number(self):
        number = self.cleaned_data.get("student_number", "").strip()
        if number and StudentProfile.objects.filter(university=self.university, student_number=number).exists():
            raise forms.ValidationError("Ce matricule est déjà utilisé dans l'université.")
        return number


class _MemberProfileForm(StyledFormMixin, forms.ModelForm):
    """Modification d'un profil + statut de l'appartenance."""

    is_active = forms.BooleanField(
        label="Membre actif", required=False,
        help_text="Décochez pour suspendre l'accès à l'université (ou laisser en attente).",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].initial = self.instance.membership.is_active

    def save(self, commit=True):
        profile = super().save(commit=commit)
        membership = profile.membership
        membership.is_active = self.cleaned_data["is_active"]
        # Décision explicite de l'admin : elle prime sur l'activation automatique.
        membership.awaiting_email_verification = False
        membership.save(update_fields=["is_active", "awaiting_email_verification"])
        return profile


class ProfessorProfileForm(_MemberProfileForm):
    class Meta:
        model = ProfessorProfile
        fields = ("department", "speciality", "grade")


class StudentProfileForm(_MemberProfileForm):
    class Meta:
        model = StudentProfile
        fields = ("student_number", "program", "promotion")

    def clean_student_number(self):
        number = self.cleaned_data.get("student_number", "").strip()
        clash = StudentProfile.objects.filter(university=self.instance.university, student_number=number)
        if number and clash.exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ce matricule est déjà utilisé dans l'université.")
        return number


# ---------------------------------------------------------------------------
# Classes et groupes
# ---------------------------------------------------------------------------

class SchoolClassForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ("name", "level", "program", "academic_year", "description", "professors")
        widgets = {"professors": forms.CheckboxSelectMultiple}

    def __init__(self, *args, university=None, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)
        self.fields["professors"].queryset = (
            ProfessorProfile.objects.filter(university=university).select_related("membership__user")
        )

    def clean(self):
        cleaned = super().clean()
        name, year = cleaned.get("name"), cleaned.get("academic_year", "")
        clash = SchoolClass.objects.filter(university=self.university, name=name, academic_year=year)
        if name and clash.exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Une classe porte déjà ce nom pour cette année universitaire.")
        return cleaned


class StudentGroupForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = StudentGroup
        fields = ("name", "capacity", "students")
        widgets = {"students": forms.CheckboxSelectMultiple}

    def __init__(self, *args, school_class=None, **kwargs):
        self.school_class = school_class
        super().__init__(*args, **kwargs)
        self.fields["students"].queryset = (
            StudentProfile.objects.filter(university=school_class.university).select_related("membership__user")
        )

    def clean_name(self):
        name = self.cleaned_data["name"]
        if StudentGroup.objects.filter(school_class=self.school_class, name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ce groupe existe déjà dans la classe.")
        return name

    def clean(self):
        cleaned = super().clean()
        capacity, students = cleaned.get("capacity"), cleaned.get("students")
        if capacity and students is not None and len(students) > capacity:
            raise forms.ValidationError(f"Le groupe dépasse sa capacité ({len(students)} / {capacity}).")
        return cleaned


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

class InvitationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ("email", "role", "message", "expires_at")
        widgets = {"expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, university=None, can_invite_admins=False, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)
        if not can_invite_admins:
            self.fields["role"].choices = [c for c in MEMBERSHIP_ROLES if c[0] != Role.UNIVERSITY_ADMIN]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        pending = Invitation.objects.filter(
            university=self.university, email__iexact=email, status=Invitation.STATUS_PENDING,
        ).exclude(pk=self.instance.pk)
        if pending.exists():
            raise forms.ValidationError("Une invitation est déjà en attente pour cet e-mail.")
        if Membership.objects.filter(university=self.university, user__email__iexact=email, is_active=True).exists():
            raise forms.ValidationError("Cette personne est déjà membre active de l'université.")
        return email


class InvitationSignupForm(StyledFormMixin, SetPasswordForm):
    """Création du compte depuis une invitation (e-mail imposé par l'invitation)."""

    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)

    field_order = ("first_name", "last_name", "new_password1", "new_password2")
