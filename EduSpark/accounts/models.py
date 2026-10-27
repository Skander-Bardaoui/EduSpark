import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify

from .tenancy import MEMBERSHIP_ROLES, Role

# Effectif maximal d'une classe. La capacité est vérifiée à l'affectation
# automatique (validation d'une inscription) et dans la gestion des groupes.
MAX_STUDENTS_PER_CLASS = 30


class Profil(models.Model):
    """Profil étendu de l'utilisateur avec son rôle fonctionnel global.

    Le rôle global sert à choisir le portail (admin / prof / étudiant) ;
    le rôle réellement exercé dans chaque université est porté par
    ``Membership``. ``sync_user_profil`` maintient ce rôle global à jour.
    """

    ROLE_ADMIN = "admin"
    ROLE_PROF = "prof"
    ROLE_ETUDIANT = "etudiant"

    ROLE_CHOICES = (
        (ROLE_ETUDIANT, "Étudiant"),
        (ROLE_PROF, "Prof"),
        (ROLE_ADMIN, "Admin"),
    )

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profil",
        verbose_name="Utilisateur",
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default=ROLE_ETUDIANT,
        verbose_name="Rôle",
    )
    # Préférences du menu Accessibilité (voir accounts/accessibility.py).
    accessibility = models.JSONField(default=dict, blank=True, verbose_name="Accessibilité")

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profils"

    def __str__(self):
        return "%s (%s)" % (self.user.email or self.user.username, self.role)

    def sync_group(self):
        """Aligne les groupes Django sur le rôle (un seul groupe de rôle)."""
        for name, _label in self.ROLE_CHOICES:
            group, _created = Group.objects.get_or_create(name=name)
            if name == self.role:
                self.user.groups.add(group)
            else:
                self.user.groups.remove(group)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            self.sync_group()
        except Exception:
            # Base pas encore migrée (ex. première migration) : on ignore.
            pass


@receiver(post_save, sender=User)
def setup_user_profil(sender, instance, created, **kwargs):
    """Crée le profil et force le rôle admin pour le staff / superuser."""
    profil, _created = Profil.objects.get_or_create(user=instance)
    cached = instance._state.fields_cache.get("profil")
    target = cached if cached is not None and cached.pk == profil.pk else profil
    if instance.is_superuser or instance.is_staff:
        if target.role != Profil.ROLE_ADMIN:
            target.role = Profil.ROLE_ADMIN
            target.save()


class University(models.Model):
    """Université = tenant. Créée par l'admin plateforme."""

    name = models.CharField("Nom", max_length=150, unique=True)
    slug = models.SlugField("Identifiant", max_length=160, unique=True, blank=True)
    code = models.CharField("Sigle", max_length=20, blank=True)
    city = models.CharField("Ville", max_length=100, blank=True)
    country = models.CharField("Pays", max_length=100, blank=True)
    email_domain = models.CharField(
        "Domaine e-mail", max_length=100, blank=True,
        help_text="Domaine officiel de l'université (information, n'active plus les comptes automatiquement).",
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
                slug, n = "%s-%s" % (base, n), n + 1
            self.slug = slug
        self.email_domain = self.email_domain.strip().lower().lstrip("@")
        super().save(*args, **kwargs)


class Membership(models.Model):
    """Rôle d'un utilisateur dans une université (un prof peut en avoir plusieurs)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="memberships", verbose_name="Utilisateur",
    )
    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="memberships", verbose_name="Université",
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
            models.UniqueConstraint(
                fields=("user", "university"), name="unique_membership_per_university",
            ),
        ]

    def __str__(self):
        return "%s — %s @ %s" % (self.user, self.get_role_display(), self.university)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        sync_user_profil(self.user)

    def ensure_profile(self):
        """Crée le profil métier correspondant au rôle s'il n'existe pas."""
        if self.role == Role.PROFESSOR:
            return ProfessorProfile.objects.get_or_create(
                membership=self, defaults={"university": self.university},
            )[0]
        if self.role == Role.STUDENT:
            return StudentProfile.objects.get_or_create(
                membership=self, defaults={"university": self.university},
            )[0]
        return None


def sync_user_profil(user):
    """Aligne ``Profil.role`` sur les appartenances de l'utilisateur.

    Priorité : admin université > professeur > étudiant. Sans appartenance,
    le rôle existant est conservé. Le superuser / staff reste admin.
    """
    if user is None:
        return
    if user.is_superuser or user.is_staff:
        role = Profil.ROLE_ADMIN
    else:
        roles = set(user.memberships.values_list("role", flat=True))
        if Role.UNIVERSITY_ADMIN in roles:
            role = Profil.ROLE_ADMIN
        elif Role.PROFESSOR in roles:
            role = Profil.ROLE_PROF
        elif Role.STUDENT in roles:
            role = Profil.ROLE_ETUDIANT
        else:
            return
    profil, _created = Profil.objects.get_or_create(user=user)
    if profil.role != role:
        profil.role = role
        profil.save(update_fields=["role"])


@receiver(post_delete, sender=Membership)
def membership_deleted(sender, instance, **kwargs):
    user = User.objects.filter(pk=instance.user_id).first()
    if user is not None:
        sync_user_profil(user)


class _MembershipProfile(models.Model):
    """Base commune des profils métier liés à une appartenance."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE, related_name="+", verbose_name="Université",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        abstract = True

    @property
    def user(self):
        return self.membership.user

    def clean(self):
        if self.membership_id and self.university_id and self.membership.university_id != self.university_id:
            raise ValidationError("Le profil et l'appartenance doivent être dans la même université.")

    def save(self, *args, **kwargs):
        if self.membership_id:
            self.university_id = self.membership.university_id
        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.membership.user)


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
        Membership, on_delete=models.CASCADE,
        related_name="professor_profile", verbose_name="Appartenance",
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
        Membership, on_delete=models.CASCADE,
        related_name="student_profile", verbose_name="Appartenance",
    )
    student_number = models.CharField("Matricule", max_length=40, blank=True)
    program = models.CharField("Filière", max_length=120, blank=True)
    promotion = models.CharField("Promotion", max_length=20, blank=True, help_text="ex. 2026")
    level = models.CharField(
        "Niveau", max_length=60, blank=True,
        help_text="Niveau choisi à l'inscription, ex. 3e année, Master 1.",
    )
    section = models.CharField(
        "Section", max_length=60, blank=True,
        help_text="Section choisie à l'inscription, ex. A, B, Sciences.",
    )

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

    @property
    def current_class(self):
        """Classe de l'étudiant (celle de son premier groupe)."""
        group = (
            self.groups.select_related("school_class")
            .order_by("-school_class__academic_year", "school_class__name")
            .first()
        )
        return group.school_class if group else None


class SchoolClass(models.Model):
    """Classe d'une université pour une année universitaire."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="school_classes", verbose_name="Université",
    )
    name = models.CharField("Nom", max_length=120)
    level = models.CharField("Niveau", max_length=60, blank=True, help_text="ex. 3e année, Master 1")
    section = models.CharField(
        "Section", max_length=60, blank=True,
        help_text="ex. A, B, Sciences, Littérature",
    )
    program = models.CharField("Filière", max_length=120, blank=True)
    study_program = models.ForeignKey(
        "courses.Program", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="school_classes", verbose_name="Filière du catalogue",
        help_text="Filière créée dans « Départements & Filières » ; le libellé ci-dessus la suit.",
    )
    academic_year = models.CharField(
        "Année universitaire", max_length=9, blank=True, help_text="ex. 2025-2026",
    )
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
            models.UniqueConstraint(
                fields=("university", "name", "section", "academic_year"),
                name="unique_class_per_year",
            ),
        ]

    def __str__(self):
        return "%s (%s)" % (self.name, self.academic_year) if self.academic_year else self.name

    def clean(self):
        if (
            self.study_program_id and self.university_id
            and self.study_program.university_id != self.university_id
        ):
            raise ValidationError({"study_program": "La filière doit appartenir à la même université."})

    def save(self, *args, **kwargs):
        if self.study_program_id:
            # Le libellé texte historique suit la filière du catalogue.
            self.program = self.study_program.name
        super().save(*args, **kwargs)

    def student_queryset(self):
        """Étudiants affectés à la classe (via ses groupes)."""
        return StudentProfile.objects.filter(
            university_id=self.university_id, groups__school_class=self,
        ).distinct()

    @property
    def enrolled_count(self):
        return self.student_queryset().count()

    @property
    def seats_left(self):
        return max(MAX_STUDENTS_PER_CLASS - self.enrolled_count, 0)

    @property
    def is_full(self):
        return self.enrolled_count >= MAX_STUDENTS_PER_CLASS


class StudentGroup(models.Model):
    """Groupe (TD / TP…) rattaché à une classe."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="student_groups", verbose_name="Université",
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE,
        related_name="groups", verbose_name="Classe",
    )
    name = models.CharField("Nom", max_length=60)
    capacity = models.PositiveSmallIntegerField(
        "Capacité", null=True, blank=True,
        validators=[MaxValueValidator(MAX_STUDENTS_PER_CLASS)],
        help_text="Ne peut pas dépasser l'effectif maximal d'une classe (30).",
    )
    students = models.ManyToManyField(
        StudentProfile, blank=True, related_name="groups", verbose_name="Étudiants",
    )

    class Meta:
        ordering = ("school_class__name", "name")
        verbose_name = "Groupe"
        verbose_name_plural = "Groupes"
        constraints = [
            models.UniqueConstraint(
                fields=("school_class", "name"), name="unique_group_per_class",
            ),
        ]

    def __str__(self):
        return "%s — %s" % (self.school_class.name, self.name)

    def save(self, *args, **kwargs):
        if self.school_class_id:
            self.university_id = self.school_class.university_id
        super().save(*args, **kwargs)


def default_invitation_expiry():
    return timezone.now() + timedelta(days=7)


class Invitation(models.Model):
    """Invitation par e-mail à rejoindre une université avec un rôle."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = (
        (STATUS_PENDING, "En attente"),
        (STATUS_ACCEPTED, "Acceptée"),
        (STATUS_REVOKED, "Révoquée"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="invitations", verbose_name="Université",
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
        constraints = [
            models.UniqueConstraint(
                fields=("university", "email"),
                condition=models.Q(status="pending"),
                name="unique_pending_invitation_per_university",
            ),
        ]

    def __str__(self):
        return "%s → %s (%s)" % (self.email, self.university, self.get_role_display())

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
        """Crée (ou réactive) l'appartenance de l'utilisateur et marque l'invitation acceptée."""
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
