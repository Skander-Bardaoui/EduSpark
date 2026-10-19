import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .tenancy import MEMBERSHIP_ROLES, Role, TenantModel


class University(models.Model):
    """Université = tenant (settings.TENANT_MODEL). Créée par l'admin plateforme."""

    name = models.CharField("Nom", max_length=150, unique=True)
    slug = models.SlugField("Identifiant", max_length=160, unique=True, blank=True)
    code = models.CharField("Sigle", max_length=20, blank=True)
    city = models.CharField("Ville", max_length=100, blank=True)
    country = models.CharField("Pays", max_length=100, blank=True)
    email_domain = models.CharField(
        "Domaine e-mail", max_length=100, blank=True,
        help_text="ex. esprit.tn — les étudiants inscrits avec ce domaine sont validés automatiquement.",
    )
    website = models.URLField("Site web", blank=True)
    description = models.TextField("Description", blank=True)
    is_active = models.BooleanField("Active", default=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Université"
        verbose_name_plural = "Universités"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:150] or "universite"
            slug, n = base, 2
            while University.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        self.email_domain = self.email_domain.strip().lower().lstrip("@")
        super().save(*args, **kwargs)


class User(AbstractUser):
    """Modèle utilisateur du projet (settings.AUTH_USER_MODEL).

    Un compte est global : il appartient à une ou plusieurs universités via
    Membership (un professeur peut enseigner dans plusieurs universités).
    Convention : username == email.
    """

    email = models.EmailField("Adresse e-mail", unique=True)
    phone = models.CharField("Téléphone", max_length=30, blank=True)
    bio = models.TextField("Présentation", blank=True)

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering = ("last_name", "first_name", "email")

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.get_full_name() or self.email or self.username

    @property
    def is_platform_admin(self):
        return self.is_superuser

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
            if not self.username:
                self.username = self.email
        super().save(*args, **kwargs)


class Membership(TenantModel):
    """Rôle d'un utilisateur dans une université."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="memberships", verbose_name="Utilisateur",
    )
    role = models.CharField("Rôle", max_length=20, choices=MEMBERSHIP_ROLES)
    is_active = models.BooleanField(
        "Actif", default=True,
        help_text="Décoché : en attente de validation par l'admin université.",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ("university__name", "user__last_name")
        verbose_name = "Appartenance"
        verbose_name_plural = "Appartenances"
        constraints = [
            models.UniqueConstraint(fields=("user", "university"), name="unique_membership_per_university"),
        ]

    def __str__(self):
        return f"{self.user} — {self.get_role_display()} @ {self.university}"

    def ensure_profile(self):
        """Crée le profil métier correspondant au rôle s'il n'existe pas."""
        if self.role == Role.PROFESSOR:
            return ProfessorProfile.objects.get_or_create(membership=self, defaults={"university": self.university})[0]
        if self.role == Role.STUDENT:
            return StudentProfile.objects.get_or_create(membership=self, defaults={"university": self.university})[0]
        return None


class _MembershipProfile(TenantModel):
    """Base commune des profils : liés à une appartenance (champ `membership`
    défini dans chaque sous-classe), toujours dans la même université."""

    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return str(self.membership.user)

    @property
    def user(self):
        return self.membership.user

    def clean(self):
        if self.membership_id and self.university_id and self.membership.university_id != self.university_id:
            raise ValidationError("Le profil et l'appartenance doivent être dans la même université.")

    def save(self, *args, **kwargs):
        self.university_id = self.membership.university_id
        super().save(*args, **kwargs)


class ProfessorProfile(_MembershipProfile):
    GRADE_CHOICES = (
        ("assistant", "Assistant"),
        ("maitre_assistant", "Maître-assistant"),
        ("maitre_conferences", "Maître de conférences"),
        ("professeur", "Professeur"),
        ("vacataire", "Vacataire"),
        ("autre", "Autre"),
    )

    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="professor_profile", verbose_name="Appartenance",
    )
    department = models.CharField("Département", max_length=120, blank=True)
    speciality = models.CharField("Spécialité", max_length=120, blank=True)
    grade = models.CharField("Grade", max_length=30, choices=GRADE_CHOICES, blank=True)

    class Meta:
        ordering = ("membership__user__last_name", "membership__user__first_name")
        verbose_name = "Profil professeur"
        verbose_name_plural = "Profils professeurs"


class StudentProfile(_MembershipProfile):
    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="student_profile", verbose_name="Appartenance",
    )
    student_number = models.CharField("Matricule", max_length=40, blank=True)
    program = models.CharField("Filière", max_length=120, blank=True)
    promotion = models.CharField("Promotion", max_length=20, blank=True, help_text="ex. 2026")

    class Meta:
        ordering = ("membership__user__last_name", "membership__user__first_name")
        verbose_name = "Profil étudiant"
        verbose_name_plural = "Profils étudiants"
        constraints = [
            models.UniqueConstraint(
                fields=("university", "student_number"),
                condition=~models.Q(student_number=""),
                name="unique_student_number_per_university",
            ),
        ]


class SchoolClass(TenantModel):
    """Classe (ex. « 3A – Génie logiciel ») d'une année universitaire."""

    name = models.CharField("Nom", max_length=120)
    level = models.CharField("Niveau", max_length=60, blank=True, help_text="ex. 3e année, Master 1")
    program = models.CharField("Filière", max_length=120, blank=True)
    academic_year = models.CharField("Année universitaire", max_length=9, blank=True, help_text="ex. 2025-2026")
    description = models.TextField("Description", blank=True)
    professors = models.ManyToManyField(
        ProfessorProfile, blank=True, related_name="classes", verbose_name="Professeurs",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("-academic_year", "name")
        verbose_name = "Classe"
        verbose_name_plural = "Classes"
        constraints = [
            models.UniqueConstraint(fields=("university", "name", "academic_year"), name="unique_class_per_year"),
        ]

    def __str__(self):
        return f"{self.name} ({self.academic_year})" if self.academic_year else self.name


class StudentGroup(TenantModel):
    """Groupe (TD / TP…) à l'intérieur d'une classe."""

    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE, related_name="groups", verbose_name="Classe",
    )
    name = models.CharField("Nom", max_length=60)
    capacity = models.PositiveSmallIntegerField("Capacité", null=True, blank=True)
    students = models.ManyToManyField(
        StudentProfile, blank=True, related_name="groups", verbose_name="Étudiants",
    )

    class Meta:
        ordering = ("school_class__name", "name")
        verbose_name = "Groupe"
        verbose_name_plural = "Groupes"
        constraints = [
            models.UniqueConstraint(fields=("school_class", "name"), name="unique_group_per_class"),
        ]

    def __str__(self):
        return f"{self.school_class.name} — {self.name}"

    def save(self, *args, **kwargs):
        self.university_id = self.school_class.university_id
        super().save(*args, **kwargs)


def default_invitation_expiry():
    return timezone.now() + timedelta(days=7)


class Invitation(TenantModel):
    """Invitation par e-mail à rejoindre une université avec un rôle."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = (
        (STATUS_PENDING, "En attente"),
        (STATUS_ACCEPTED, "Acceptée"),
        (STATUS_REVOKED, "Révoquée"),
    )

    email = models.EmailField("E-mail invité")
    role = models.CharField("Rôle", max_length=20, choices=MEMBERSHIP_ROLES)
    message = models.TextField("Message personnalisé", blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField("Statut", max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sent_invitations", verbose_name="Invité par",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="accepted_invitations", verbose_name="Acceptée par",
    )
    expires_at = models.DateTimeField("Expire le", default=default_invitation_expiry)
    accepted_at = models.DateTimeField("Acceptée le", null=True, blank=True)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Invitation"
        verbose_name_plural = "Invitations"

    def __str__(self):
        return f"{self.email} → {self.university} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    @property
    def is_usable(self):
        return self.status == self.STATUS_PENDING and not self.is_expired and self.university.is_active

    @property
    def display_status(self):
        if self.status == self.STATUS_PENDING and self.is_expired:
            return "Expirée"
        return self.get_status_display()

    def accept(self, user):
        """Crée (ou met à jour) l'appartenance de user et marque l'invitation acceptée."""
        membership, created = Membership.objects.get_or_create(
            user=user, university=self.university,
            defaults={"role": self.role, "is_active": True},
        )
        if not created:
            membership.role = self.role
            membership.is_active = True
            membership.save(update_fields=["role", "is_active"])
        membership.ensure_profile()
        self.status = self.STATUS_ACCEPTED
        self.accepted_by = user
        self.accepted_at = timezone.now()
        self.save(update_fields=["status", "accepted_by", "accepted_at"])
        return membership
