"""Données de démonstration de la classe virtuelle (à lancer après seed_demo).

    python manage.py seed_community

Idempotent : relancer la commande ne duplique rien.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Membership, SchoolClass, University
from accounts.tenancy import Role
from community.models import Announcement, Forum, Message, Reply, Report, Thread

QUESTIONS = (
    ("Différence entre une pile et une file ?",
     "Je confonds toujours les deux structures. Pouvez-vous rappeler quand utiliser l'une ou l'autre ?",
     "Une pile est LIFO (dernier entré, premier sorti) : pensez à l'historique « annuler ». "
     "Une file est FIFO (premier entré, premier sorti) : pensez à une file d'attente d'impression."),
    ("Comment démontrer une convergence par récurrence ?",
     "Je bloque sur l'étape d'hérédité de l'exercice 3 du TD. Quelqu'un a une piste ?",
     "Écris d'abord l'hypothèse de récurrence au rang n, puis exprime le terme n+1 en fonction du terme n."),
    ("Sujet du prochain TP ?",
     "Est-ce que le TP de la semaine prochaine porte bien sur le chapitre 4 ?",
     None),
)


class Command(BaseCommand):
    help = "Crée forums, questions, annonces, messages et un signalement de démonstration."

    @transaction.atomic
    def handle(self, *args, **options):
        universities = list(University.objects.filter(is_active=True))
        if not universities:
            raise CommandError("Aucune université : lancez d'abord « python manage.py seed_demo ».")
        for university in universities:
            self.seed_university(university)
        self.stdout.write(self.style.SUCCESS(
            "Classe virtuelle : %d forums, %d questions, %d réponses, %d annonces, %d messages, %d signalements."
            % (Forum.objects.count(), Thread.objects.count(), Reply.objects.count(),
               Announcement.objects.count(), Message.objects.count(), Report.objects.count())
        ))

    def seed_university(self, university):
        members = Membership.objects.filter(university=university, is_active=True).select_related("user")
        admin = members.filter(role=Role.UNIVERSITY_ADMIN).first()
        professors = [m.user for m in members.filter(role=Role.PROFESSOR)]
        students = [m.user for m in members.filter(role=Role.STUDENT)]
        if not (admin and professors and students):
            self.stdout.write("%s : il manque un admin, un professeur ou un étudiant, ignorée." % university.name)
            return

        general, _ = Forum.objects.get_or_create(
            university=university, title="Vie du campus",
            defaults={"description": "Questions pratiques et échanges entre tous les membres.", "created_by": admin.user},
        )
        Announcement.objects.get_or_create(
            university=university, title="Rentrée : calendrier et accès aux salles",
            defaults={
                "author": admin.user, "priority": Announcement.PRIORITY_IMPORTANT, "is_pinned": True,
                "body": "Le calendrier du semestre est disponible. Merci de vérifier vos salles avant le premier cours.",
            },
        )
        self.add_thread(general, students[0], professors[0], *QUESTIONS[2])

        for index, school_class in enumerate(SchoolClass.objects.filter(university=university)):
            professor = (school_class.professors.first().membership.user
                         if school_class.professors.exists() else professors[0])
            forum, _ = Forum.objects.get_or_create(
                university=university, school_class=school_class, title="Forum %s" % school_class.name,
                defaults={"description": "Questions sur les cours de la classe.", "created_by": professor,
                          "course_ref": school_class.program},
            )
            Announcement.objects.get_or_create(
                university=university, school_class=school_class, title="Consignes pour %s" % school_class.name,
                defaults={"author": professor, "audience": Announcement.AUDIENCE_CLASS,
                          "body": "Pensez à poser vos questions dans le forum de la classe plutôt que par e-mail."},
            )
            asker = students[index % len(students)]
            for title, body, answer in QUESTIONS[:2]:
                self.add_thread(forum, asker, professor, title, body, answer)

        # Un message privé et un signalement pour tester la messagerie et la modération.
        Message.objects.get_or_create(
            university=university, sender=students[0], recipient=professors[0], subject="Question sur le TP",
            defaults={"body": "Bonjour, pouvez-vous confirmer l'horaire du TP de jeudi ?"},
        )
        # Un signalement sur le forum général (traité par l'administration) et un sur un forum de classe
        # (traité par le professeur de la classe).
        if len(students) > 1:
            class_thread = Thread.objects.filter(
                university=university, forum__school_class__isnull=False, title=QUESTIONS[1][0],
            ).first()
            for thread, reason, details in (
                (Thread.objects.filter(university=university, forum=general).first(), Report.REASON_OFFTOPIC,
                 "Cette question concerne plutôt le secrétariat."),
                (class_thread, Report.REASON_OTHER, "Je ne comprends pas le rapport avec le cours."),
            ):
                if thread:
                    Report.objects.get_or_create(
                        thread=thread, reporter=students[1], reason=reason, defaults={"details": details},
                    )

    def add_thread(self, forum, asker, answerer, title, body, answer):
        thread, created = Thread.objects.get_or_create(
            forum=forum, title=title, defaults={"author": asker, "body": body},
        )
        if answer and created:
            Reply.objects.create(
                thread=thread, author=answerer, body=answer, is_solution=True,
                validated_by=answerer, validated_at=timezone.now(),
            )
            thread.is_resolved = True
            thread.save(update_fields=["is_resolved"])
