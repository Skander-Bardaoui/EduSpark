from datetime import timedelta

from django import forms
from django.apps import apps
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    Invitation, Membership, ProfessorProfile, SchoolClass, StudentGroup, StudentProfile, University,
    sync_user_profil,
)
from .tenancy import MEMBERSHIP_ROLES, Role

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
    """Applique les classes Tailwind du design system à tous les widgets.

    ``placeholders`` (attribut de classe facultatif) associe un exemple
    « ex. … » à chaque champ texte. Une aide de champ qui commence par « ex. »
    (sans tiret d'explication) sert automatiquement de placeholder.
    """

    placeholders = {}

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
            help_text = (field.help_text or "").strip()
            if help_text.lower().startswith("ex.") and "—" not in help_text:
                widget.attrs.setdefault("placeholder", help_text)
        for name, placeholder in self.placeholders.items():
            if name in self.fields:
                self.fields[name].widget.attrs["placeholder"] = placeholder


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

class SignUpForm(UserCreationForm):
    """Inscription publique : crée le compte et une appartenance à l'université.

    Un étudiant dont l'e-mail correspond au domaine officiel de l'université
    est validé automatiquement ; les autres inscriptions restent en attente
    de validation par l'admin université.
    """

    ROLE_CHOICES = (
        ("etudiant", "Apprenant"),
        ("prof", "Enseignant"),
    )

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        required=False,
        initial="etudiant",
    )

    university = forms.ModelChoiceField(
        queryset=University.objects.filter(is_active=True),
        empty_label="Choisissez votre université",
        label="Université",
        widget=forms.Select(attrs={"id": "university", "class": SIGNUP_INPUT_CLASS}),
        error_messages={"required": "Choisissez votre université."},
    )

    full_name = forms.CharField(
        max_length=150,
        required=True,
        label="Nom complet",
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
        label="Mot de passe",
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
    # synchronisé côté serveur pour satisfaire UserCreationForm.
    password2 = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "password2"}),
    )

    class Meta:
        model = User
        fields = ("full_name", "email", "password1", "password2")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("password2") and cleaned.get("password1"):
            cleaned["password2"] = cleaned["password1"]
        return cleaned

    def clean_role(self):
        role = self.cleaned_data.get("role") or "etudiant"
        if role not in ("etudiant", "prof"):
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
        first, _sep, last = self.cleaned_data.get("full_name", "").strip().partition(" ")
        user.first_name = first
        user.last_name = last
        user.save()

        university = self.cleaned_data["university"]
        role = Role.STUDENT if self.cleaned_data.get("role") == "etudiant" else Role.PROFESSOR
        domain = email.rsplit("@", 1)[-1]
        auto_validated = (
            role == Role.STUDENT
            and bool(university.email_domain)
            and domain == university.email_domain
        )
        membership = Membership.objects.create(
            user=user, university=university, role=role, is_active=auto_validated,
        )
        membership.ensure_profile()
        sync_user_profil(user)
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
    placeholders = {
        "name": "ex. Université Paris Cité",
        "code": "ex. UPC",
        "city": "ex. Paris",
        "country": "ex. France",
        "email_domain": "ex. u-paris.fr",
        "website": "ex. https://u-paris.fr",
        "description": "ex. Université pluridisciplinaire en sciences et santé…",
    }

    class Meta:
        model = University
        fields = ("name", "code", "city", "country", "email_domain", "website", "description", "is_active")


class UniversityAdminEditForm(StyledFormMixin, forms.ModelForm):
    """Champs qu'un admin université peut modifier sur sa propre université."""

    placeholders = {
        "code": "ex. UPC",
        "city": "ex. Paris",
        "country": "ex. France",
        "website": "ex. https://u-paris.fr",
        "description": "ex. Université pluridisciplinaire en sciences et santé…",
    }

    class Meta:
        model = University
        fields = ("code", "city", "country", "website", "description")


class AccountForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        "first_name": "ex. Marie",
        "last_name": "ex. Dupont",
        "email": "ex. marie.dupont@u-paris.fr",
    }

    is_platform_admin = forms.BooleanField(
        label="Admin plateforme", required=False,
        help_text="Donne accès à toutes les universités et au back-office.",
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "is_active")
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
        user.is_superuser = user.is_staff = self.cleaned_data["is_platform_admin"]
        if commit:
            user.save()
            sync_user_profil(user)
        return user


class ProfileForm(StyledFormMixin, forms.ModelForm):
    """Chacun édite son propre profil (informations de compte)."""

    placeholders = {
        "first_name": "ex. Marie",
        "last_name": "ex. Dupont",
        "email": "ex. marie.dupont@u-paris.fr",
    }

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "Prénom", "last_name": "Nom"}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Un autre compte utilise déjà cet e-mail.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email
        if commit:
            user.save()
        return user


# ---------------------------------------------------------------------------
# Professeurs et étudiants (admin université)
# ---------------------------------------------------------------------------

class _MemberCreateForm(StyledFormMixin, forms.Form):
    """Création d'un membre : réutilise le compte si l'e-mail existe déjà
    (un professeur peut enseigner dans plusieurs universités)."""

    placeholders = {
        "email": "ex. prenom.nom@universite.fr",
        "first_name": "ex. Awa",
        "last_name": "ex. Diallo",
    }

    email = forms.EmailField(label="E-mail")
    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)

    role = None
    profile_fields = ()

    def __init__(self, *args, university=None, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Membership.objects.filter(
            user__email__iexact=email, university=self.university,
        ).exists():
            raise forms.ValidationError("Cette personne est déjà membre de l'université.")
        return email

    def save_member(self):
        """Retourne (membership, compte_créé)."""
        email = self.cleaned_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            user = User(
                email=email, username=email,
                first_name=self.cleaned_data["first_name"],
                last_name=self.cleaned_data["last_name"],
            )
            user.set_unusable_password()
            user.save()
        membership, _created = Membership.objects.get_or_create(
            user=user, university=self.university,
            defaults={"role": self.role, "is_active": True},
        )
        if not _created:
            membership.role = self.role
            membership.is_active = True
            membership.save(update_fields=["role", "is_active"])
        profile = membership.ensure_profile()
        for name in self.profile_fields:
            setattr(profile, name, self.cleaned_data.get(name, ""))
        profile.save()
        return membership, created


class ProfessorCreateForm(_MemberCreateForm):
    role = Role.PROFESSOR
    profile_fields = ("department", "speciality", "grade")

    placeholders = {
        "email": "ex. prenom.nom@universite.fr",
        "first_name": "ex. Awa",
        "last_name": "ex. Diallo",
        "department": "ex. Informatique",
        "speciality": "ex. Réseaux et systèmes",
    }

    department = forms.CharField(label="Département", max_length=120, required=False)
    speciality = forms.CharField(label="Spécialité", max_length=120, required=False)
    grade = forms.ChoiceField(
        label="Grade", choices=(("", "—"),) + ProfessorProfile.GRADE_CHOICES, required=False,
    )


class StudentCreateForm(_MemberCreateForm):
    role = Role.STUDENT
    profile_fields = ("student_number", "program", "promotion")

    placeholders = {
        "email": "ex. prenom.nom@universite.fr",
        "first_name": "ex. Awa",
        "last_name": "ex. Diallo",
        "student_number": "ex. 2024-0123",
        "program": "ex. Informatique",
        "promotion": "ex. 2026",
    }

    student_number = forms.CharField(label="Matricule", max_length=40, required=False)
    program = forms.CharField(label="Filière", max_length=120, required=False)
    promotion = forms.CharField(label="Promotion", max_length=20, required=False)

    def clean_student_number(self):
        number = self.cleaned_data.get("student_number", "").strip()
        if number and StudentProfile.objects.filter(
            university=self.university, student_number=number,
        ).exists():
            raise forms.ValidationError("Ce matricule est déjà utilisé dans l'université.")
        return number


class _MemberProfileForm(StyledFormMixin, forms.ModelForm):
    """Modification d'un profil métier (+ statut pour l'admin)."""

    is_active = forms.BooleanField(
        label="Membre actif", required=False,
        help_text="Décochez pour suspendre l'accès à l'université.",
    )

    def __init__(self, *args, admin=True, **kwargs):
        self.admin = admin
        super().__init__(*args, **kwargs)
        if admin:
            self.fields["is_active"].initial = self.instance.membership.is_active
        else:
            self.fields.pop("is_active", None)

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if self.admin:
            membership = profile.membership
            membership.is_active = self.cleaned_data["is_active"]
            membership.save(update_fields=["is_active"])
        return profile


class ProfessorProfileForm(_MemberProfileForm):
    placeholders = {
        "department": "ex. Informatique",
        "speciality": "ex. Réseaux et systèmes",
    }

    class Meta:
        model = ProfessorProfile
        fields = ("department", "speciality", "grade")


class StudentProfileForm(_MemberProfileForm):
    placeholders = {
        "student_number": "ex. 2024-0123",
        "program": "ex. Informatique",
        "promotion": "ex. 2026",
    }

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

class ProfessorChipSelectMultiple(forms.CheckboxSelectMultiple):
    """Cases à cocher en cartes (nom + département) pour choisir les professeurs."""

    template_name = "portal/_chip_checkbox_select.html"
    option_template_name = "portal/_chip_checkbox_option.html"


class SchoolClassForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = (
            "name", "level", "section", "study_program", "program",
            "academic_year", "description", "professors",
        )
        widgets = {"professors": ProfessorChipSelectMultiple}

    def __init__(self, *args, university=None, **kwargs):
        self.university = university
        super().__init__(*args, **kwargs)
        placeholders = {
            "name": "ex. Informatique",
            "level": "ex. 3e année, Master 1",
            "section": "ex. A, B, Sciences, Littérature",
            "academic_year": "ex. 2025-2026",
            "description": "ex. Classe orientée systèmes et réseaux…",
            "program": "ex. Informatique",
        }
        for field_name, placeholder in placeholders.items():
            if field_name in self.fields:
                self.fields[field_name].widget.attrs["placeholder"] = placeholder
        self.fields["professors"].queryset = ProfessorProfile.objects.filter(
            university=university,
        ).select_related("membership__user")
        self.fields["professors"].label_from_instance = self._professor_label

        programs = apps.get_model("courses", "Program").objects.filter(
            university=university,
        ).select_related("department")
        if programs.exists():
            # Des filières existent dans le catalogue : on en choisit une dans la
            # liste, et le libellé texte de la classe la suit automatiquement.
            study_program = self.fields["study_program"]
            study_program.queryset = programs
            study_program.label = "Filière"
            study_program.help_text = "Filières créées dans « Départements & Filières »."
            study_program.label_from_instance = lambda program: "%s — %s" % (
                program.name, program.department.name,
            )
            self.fields.pop("program")
        else:
            self.fields.pop("study_program")

    @staticmethod
    def _professor_label(profile):
        name = profile.user.get_full_name() or profile.user.email
        if profile.department:
            return "%s — %s" % (name, profile.department)
        return name

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get("name")
        section = (cleaned.get("section") or "").strip()
        year = cleaned.get("academic_year", "")
        clash = SchoolClass.objects.filter(
            university=self.university, name=name, section=section, academic_year=year,
        )
        if name and clash.exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(
                "Une classe porte déjà ce nom, cette section et cette année universitaire."
            )
        if self.instance.pk:
            self._check_teaching_assignments(cleaned)
        return cleaned

    def _check_teaching_assignments(self, cleaned):
        """Les affectations du module cours doivent rester cohérentes avec la classe :
        mêmes filière et mêmes enseignants que ceux qu'on s'apprête à enregistrer."""
        assignments = list(
            self.instance.teaching_assignments.select_related("subject", "professor__membership__user")
        )
        study_program = cleaned.get("study_program")
        if study_program is not None:
            foreign = sorted({a.subject.code for a in assignments if a.subject.program_id != study_program.pk})
            if foreign:
                self.add_error("study_program", (
                    "Des matières affectées à cette classe n'appartiennent pas à la filière « %s » (%s) : "
                    "retirez d'abord ces affectations."
                ) % (study_program.name, ", ".join(foreign)))
        professors = cleaned.get("professors")
        if professors is not None:
            kept = {professor.pk for professor in professors}
            teaching = sorted({
                a.professor.user.get_full_name() or a.professor.user.email
                for a in assignments if a.professor_id not in kept
            })
            if teaching:
                self.add_error("professors", (
                    "Enseigne encore dans cette classe : %s. Retirez d'abord son affectation "
                    "(Cours & Catalogue, Affectations enseignants)."
                ) % ", ".join(teaching))


class StudentGroupForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        "name": "ex. Groupe A",
        "capacity": "ex. 24",
    }

    class Meta:
        model = StudentGroup
        fields = ("name", "capacity", "students")
        widgets = {"students": forms.CheckboxSelectMultiple}

    def __init__(self, *args, school_class=None, **kwargs):
        self.school_class = school_class
        super().__init__(*args, **kwargs)
        self.fields["students"].queryset = StudentProfile.objects.filter(
            university=school_class.university,
        ).select_related("membership__user")

    def clean_name(self):
        name = self.cleaned_data["name"]
        if StudentGroup.objects.filter(
            school_class=self.school_class, name=name,
        ).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ce groupe existe déjà dans la classe.")
        return name

    def clean(self):
        cleaned = super().clean()
        capacity, students = cleaned.get("capacity"), cleaned.get("students")
        if capacity and students is not None and len(students) > capacity:
            raise forms.ValidationError(
                "Le groupe dépasse sa capacité (%s / %s)." % (len(students), capacity)
            )
        return cleaned


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

class InvitationForm(StyledFormMixin, forms.ModelForm):
    placeholders = {
        "email": "ex. prenom.nom@universite.fr",
        "message": "ex. Bienvenue ! Voici votre accès à la plateforme.",
    }

    class Meta:
        model = Invitation
        fields = ("email", "role", "message", "expires_at")
        widgets = {
            "expires_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, university=None, can_invite_admins=False, **kwargs):
        self.university = university
        self.can_invite_admins = can_invite_admins
        super().__init__(*args, **kwargs)
        if not can_invite_admins:
            self.fields["role"].choices = [
                choice for choice in MEMBERSHIP_ROLES if choice[0] != Role.UNIVERSITY_ADMIN
            ]
        if not self.instance.pk:
            self.fields["expires_at"].initial = (
                timezone.now() + timedelta(days=7)
            ).strftime("%Y-%m-%dT%H:%M")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        pending = Invitation.objects.filter(
            university=self.university, email__iexact=email, status=Invitation.STATUS_PENDING,
        ).exclude(pk=self.instance.pk)
        if pending.exists():
            raise forms.ValidationError("Une invitation est déjà en attente pour cet e-mail.")
        if Membership.objects.filter(
            university=self.university, user__email__iexact=email, is_active=True,
        ).exists():
            raise forms.ValidationError("Cette personne est déjà membre active de l'université.")
        return email


class InvitationSignupForm(StyledFormMixin, SetPasswordForm):
    """Création du compte depuis une invitation (e-mail imposé)."""

    placeholders = {
        "first_name": "ex. Awa",
        "last_name": "ex. Diallo",
    }

    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)

    field_order = ("first_name", "last_name", "new_password1", "new_password2")


class PasswordChangeStyledForm(StyledFormMixin, PasswordChangeForm):
    pass
