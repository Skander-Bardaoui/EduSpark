from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import SchoolClass, University

# Liens avec les autres modules : champs simples uniquement (cours = texte libre),
# aucune ForeignKey vers courses / exercises / exams / coaching.


class Announcement(models.Model):
    """Annonce publiée par un professeur ou l'administration."""

    AUDIENCE_ALL = "tous"
    AUDIENCE_CLASS = "classe"
    AUDIENCE_CHOICES = (
        (AUDIENCE_ALL, "Toute l'université"),
        (AUDIENCE_CLASS, "Une classe"),
    )
    PRIORITY_NORMAL = "normale"
    PRIORITY_IMPORTANT = "importante"
    PRIORITY_CHOICES = (
        (PRIORITY_NORMAL, "Normale"),
        (PRIORITY_IMPORTANT, "Importante"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="announcements", verbose_name="Université",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="announcements", verbose_name="Auteur",
    )
    title = models.CharField("Titre", max_length=200)
    body = models.TextField("Message")
    audience = models.CharField("Destinataires", max_length=10, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL)
    school_class = models.ForeignKey(
        SchoolClass, null=True, blank=True, on_delete=models.CASCADE,
        related_name="announcements", verbose_name="Classe",
    )
    course_ref = models.CharField("Cours / matière", max_length=120, blank=True)
    priority = models.CharField("Priorité", max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    is_pinned = models.BooleanField("Épinglée", default=False)
    published_at = models.DateTimeField("Publiée le", default=timezone.now)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("-is_pinned", "-published_at")
        verbose_name = "Annonce"
        verbose_name_plural = "Annonces"

    def __str__(self):
        return self.title

    def clean(self):
        if self.audience == self.AUDIENCE_CLASS and not self.school_class_id:
            raise ValidationError({"school_class": "Choisissez la classe destinataire."})

    def save(self, *args, **kwargs):
        if self.audience == self.AUDIENCE_ALL:
            self.school_class = None
        elif self.school_class_id:
            self.university_id = self.school_class.university_id
        super().save(*args, **kwargs)


class Forum(models.Model):
    """Forum d'une classe ou d'un cours (ou forum général si aucune classe)."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="forums", verbose_name="Université",
    )
    title = models.CharField("Titre", max_length=150)
    description = models.TextField("Description", blank=True)
    school_class = models.ForeignKey(
        SchoolClass, null=True, blank=True, on_delete=models.CASCADE,
        related_name="forums", verbose_name="Classe",
        help_text="Vide = forum ouvert à toute l'université.",
    )
    course_ref = models.CharField("Cours / matière", max_length=120, blank=True)
    is_locked = models.BooleanField("Verrouillé", default=False, help_text="Plus de nouvelles questions ni réponses.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="forums_created", verbose_name="Créé par",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ("title",)
        verbose_name = "Forum"
        verbose_name_plural = "Forums"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.school_class_id:
            self.university_id = self.school_class.university_id
        super().save(*args, **kwargs)


class Thread(models.Model):
    """Question posée dans un forum."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="threads", verbose_name="Université", editable=False,
    )
    forum = models.ForeignKey(Forum, on_delete=models.CASCADE, related_name="threads", verbose_name="Forum")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="threads", verbose_name="Auteur",
    )
    title = models.CharField("Sujet", max_length=200)
    body = models.TextField("Question")
    is_resolved = models.BooleanField("Résolue", default=False)
    is_pinned = models.BooleanField("Épinglée", default=False)
    is_hidden = models.BooleanField("Masquée par la modération", default=False)
    created_at = models.DateTimeField("Posée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("-is_pinned", "-created_at")
        verbose_name = "Question"
        verbose_name_plural = "Questions"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.university_id = self.forum.university_id
        super().save(*args, **kwargs)


class Reply(models.Model):
    """Réponse à une question."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="replies", verbose_name="Université", editable=False,
    )
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="replies", verbose_name="Question")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="replies", verbose_name="Auteur",
    )
    body = models.TextField("Réponse")
    is_solution = models.BooleanField("Solution", default=False)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="solutions_validated", verbose_name="Solution validée par",
    )
    validated_at = models.DateTimeField("Solution validée le", null=True, blank=True)
    is_hidden = models.BooleanField("Masquée par la modération", default=False)
    ai_assisted = models.BooleanField(
        "Brouillon suggéré par l'IA", default=False,
        help_text="La réponse a démarré d'une suggestion de l'assistant, relue par son auteur.",
    )
    created_at = models.DateTimeField("Postée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ("-is_solution", "created_at")
        verbose_name = "Réponse"
        verbose_name_plural = "Réponses"

    def __str__(self):
        return "Réponse à « %s »" % self.thread.title

    @property
    def validator_name(self):
        user = self.validated_by
        return (user.get_full_name().strip() or user.email) if user else ""

    def save(self, *args, **kwargs):
        self.university_id = self.thread.university_id
        super().save(*args, **kwargs)


class Message(models.Model):
    """Message privé entre deux membres d'une même université."""

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="private_messages", verbose_name="Université",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="messages_sent", verbose_name="Expéditeur",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="messages_received", verbose_name="Destinataire",
    )
    subject = models.CharField("Objet", max_length=200)
    body = models.TextField("Message")
    read_at = models.DateTimeField("Lu le", null=True, blank=True)
    sender_deleted = models.BooleanField(default=False)
    recipient_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField("Envoyé le", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Message"
        verbose_name_plural = "Messages"

    def __str__(self):
        return self.subject


class Report(models.Model):
    """Signalement d'une question ou d'une réponse, traité par la modération."""

    REASON_SPAM = "spam"
    REASON_OFFTOPIC = "hors_sujet"
    REASON_DISRESPECT = "irrespectueux"
    REASON_CHEATING = "triche"
    REASON_OTHER = "autre"
    REASON_CHOICES = (
        (REASON_SPAM, "Spam ou publicité"),
        (REASON_OFFTOPIC, "Hors sujet"),
        (REASON_DISRESPECT, "Propos irrespectueux"),
        (REASON_CHEATING, "Triche / partage de corrigé d'examen"),
        (REASON_OTHER, "Autre"),
    )
    STATUS_OPEN = "ouvert"
    STATUS_ACTIONED = "traite"
    STATUS_DISMISSED = "rejete"
    STATUS_CHOICES = (
        (STATUS_OPEN, "À traiter"),
        (STATUS_ACTIONED, "Contenu masqué"),
        (STATUS_DISMISSED, "Sans suite"),
    )

    university = models.ForeignKey(
        University, on_delete=models.CASCADE,
        related_name="reports", verbose_name="Université", editable=False,
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="reports_made", verbose_name="Signalé par",
    )
    thread = models.ForeignKey(Thread, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    reply = models.ForeignKey(Reply, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField("Motif", max_length=20, choices=REASON_CHOICES)
    details = models.TextField("Précisions", blank=True)
    status = models.CharField("Statut", max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reports_handled", verbose_name="Traité par",
    )
    handled_at = models.DateTimeField("Traité le", null=True, blank=True)
    created_at = models.DateTimeField("Signalé le", auto_now_add=True)

    class Meta:
        ordering = ("status", "-created_at")
        verbose_name = "Signalement"
        verbose_name_plural = "Signalements"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(thread__isnull=False, reply__isnull=True)
                    | models.Q(thread__isnull=True, reply__isnull=False)
                ),
                name="report_targets_thread_xor_reply",
            ),
        ]

    def __str__(self):
        return "Signalement : %s" % self.get_reason_display()

    @property
    def target(self):
        return self.reply or self.thread

    @property
    def forum(self):
        return self.reply.thread.forum if self.reply_id else self.thread.forum

    def save(self, *args, **kwargs):
        target = self.reply.thread if self.reply_id else self.thread
        self.university_id = target.university_id
        super().save(*args, **kwargs)
