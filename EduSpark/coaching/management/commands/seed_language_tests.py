"""Résultats de démonstration du test de langue orale (idempotent)."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Membership, University
from accounts.tenancy import Role

from coaching.models import LanguageTestFeedback, LanguageTestSession, TutorAssignment

PARIS = "Université Paris Cité"
LYON = "Université de Lyon"
SEED_NAMESPACE = uuid.UUID("9f2f5a41-6a3e-4c8b-9a7c-2d4b6e8f0a1c")

RESULTS = (
    {
        "email": "test.ui@example.com",
        "key": "camille-ielts-b2",
        "exam_type": "ielts",
        "level": "b2",
        "exercise_type": "topic_discussion",
        "language": "en",
        "duration_seconds": 840,
        "days_ago": 12,
        "status": "completed",
        "transcript": (
            ("assistant", "Good afternoon. Let's talk about technology and communication. How has technology changed the way you keep in touch with friends and family?"),
            ("user", "I think technology has changed communication a lot. For example, I use video calls to speak with my family who live in another city, and it feels much closer than just sending messages."),
            ("assistant", "That's interesting. Do you think these tools make conversations deeper or more superficial?"),
            ("user", "That is a difficult question. I suppose it depends on how we use them. A video call can be very meaningful, but when people only send short messages, the relationship can become a bit superficial."),
            ("assistant", "Could you give an example of a time when technology helped you communicate better?"),
            ("user", "Last year I prepared a group project with students in another university. We met online every week, shared documents and organised our work, so technology really helped us collaborate."),
        ),
        "feedback": {
            "overall_level": "B2",
            "overall_verdict": "Needs Work",
            "fluency_score": 6,
            "vocabulary_score": 6,
            "grammar_score": 5,
            "task_achievement_score": 6,
            "fluency_notes": (
                "Réponses développées avec peu d'hésitations bloquantes.",
                "Quelques pauses pour rechercher le mot juste, mais le fil reste clair.",
            ),
            "vocabulary_notes": (
                "Bon usage de « meaningful », « superficial » et « collaborate ».",
                "Quelques répétitions de « technology » et « communication ».",
            ),
            "grammar_notes": (
                "Structures simples majoritairement correctes.",
                "Accord à surveiller : « if we use them » / « a bit superficial ».",
            ),
            "task_achievement_notes": (
                "Toutes les questions ont reçu une réponse complète.",
                "Les exemples personnels sont pertinents mais pourraient être plus détaillés.",
            ),
            "pronunciation_flags": (
                {"word": "superficial", "timestamp": 0},
                {"word": "collaborate", "timestamp": 0},
            ),
            "recommendations": (
                "Travaillez l'accent tonique sur les mots de plus de trois syllabes.",
                "Préparez des exemples chiffrés pour appuyer vos arguments.",
                "Entraînez-vous à reformuler une idée avec deux structures différentes.",
            ),
        },
    },
    {
        "email": "yanis.leroy@u-paris.fr",
        "key": "yanis-cambridge-b1",
        "exam_type": "cambridge_b2",
        "level": "b1",
        "exercise_type": "debate",
        "language": "en",
        "duration_seconds": 900,
        "days_ago": 5,
        "status": "completed",
        "transcript": (
            ("assistant", "Hello. Today's proposition is: remote work is better than working in an office. Do you agree or disagree?"),
            ("user", "I agree with this idea, because I think people can save time. When you work at home, you don't need to travel, so you can start earlier and you are less tired."),
            ("assistant", "Some people say that working from home makes it harder to separate work from personal life. What do you think about that?"),
            ("user", "Yes, it is a problem. For me, I like to have a small office in my room and I stop working at six o'clock. But I understand that some people cannot do this."),
            ("assistant", "Would you accept a job that requires you to be in the office every day?"),
            ("user", "Maybe not every day. I think two or three days in the office is good, because we can speak with the team and learn from them."),
        ),
        "feedback": {
            "overall_level": "B1",
            "overall_verdict": "Needs Work",
            "fluency_score": 5,
            "vocabulary_score": 5,
            "grammar_score": 4,
            "task_achievement_score": 5,
            "fluency_notes": (
                "Le candidat répond à toutes les questions mais avec des phrases courtes.",
                "Quelques hésitations et répétitions de « work » et « office ».",
            ),
            "vocabulary_notes": (
                "Vocabulaire fonctionnel pour défendre une opinion simple.",
                "Manque de termes précis pour nuancer le propos.",
            ),
            "grammar_notes": (
                "Temps simples globalement maîtrisés.",
                "Accords et structures conditionnelles à consolider.",
            ),
            "task_achievement_notes": (
                "Position claire et contre-argument reconnu.",
                "Les justifications restent générales et peu développées.",
            ),
            "pronunciation_flags": (
                {"word": "office", "timestamp": 0},
                {"word": "earlier", "timestamp": 0},
            ),
            "recommendations": (
                "Développez chaque argument avec un exemple concret.",
                "Révisez les structures « I think… because… » et le conditionnel.",
                "Enregistrez-vous pour corriger les hésitations récurrentes.",
            ),
        },
    },
    {
        "email": "lucas.moreau@univ-lyon.fr",
        "key": "lucas-ielts-c1",
        "exam_type": "ielts",
        "level": "c1",
        "exercise_type": "debate",
        "language": "fr",
        "duration_seconds": 840,
        "days_ago": 21,
        "status": "completed",
        "transcript": (
            ("assistant", "Bonsoir. La proposition du jour est la suivante : l'intelligence artificielle fera plus de mal que de bien. Êtes-vous d'accord ?"),
            ("user", "Je comprends la crainte, mais je ne suis pas entièrement d'accord. L'intelligence artificielle peut automatiser des tâches répétitives et libérer du temps pour des activités à plus forte valeur ajoutée."),
            ("assistant", "Certains estiment que cette automatisation détruit des emplois et creuse les inégalités. Comment répondez-vous à cet argument ?"),
            ("user", "C'est un risque réel, notamment pour les métiers peu qualifiés. Cependant, l'histoire montre que les révolutions technologiques créent aussi de nouveaux métiers. Le vrai enjeu, c'est d'accompagner la transition par la formation."),
            ("assistant", "Vous parlez de formation. Qui devrait en supporter le coût selon vous ?"),
            ("user", "Je pense que la responsabilité est partagée. Les entreprises bénéficient de ces gains de productivité, donc elles devraient contribuer. L'État a aussi un rôle à jouer pour garantir l'égalité d'accès à la reconversion."),
        ),
        "feedback": {
            "overall_level": "C1",
            "overall_verdict": "Ready",
            "fluency_score": 7,
            "vocabulary_score": 7,
            "grammar_score": 6,
            "task_achievement_score": 7,
            "fluency_notes": (
                "Discours fluide avec des connecteurs logiques variés.",
                "Le candidat reformule et nuance ses réponses sans effort visible.",
            ),
            "vocabulary_notes": (
                "Lexique précis : « valeur ajoutée », « reconversion », « gains de productivité ».",
                "Quelques imprécisions mineures dans les collocations.",
            ),
            "grammar_notes": (
                "Bon contrôle des structures complexes.",
                "Quelques accords du participe à surveiller à l'oral.",
            ),
            "task_achievement_notes": (
                "Position nuancée et contre-argument intégré avec pertinence.",
                "Réponse à la question sur le coût de la formation bien structurée.",
            ),
            "pronunciation_flags": (
                {"word": "productivité", "timestamp": 0},
            ),
            "recommendations": (
                "Maintenez ce niveau d'argumentation en variant les registres.",
                "Continuez à travailler la prononciation des mots longs.",
                "Préparez des exemples de politiques publiques pour enrichir le débat.",
            ),
        },
    },
)


class Command(BaseCommand):
    help = "Crée des résultats de test de langue pour la démonstration (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Exécuter même quand DEBUG=False.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "seed_language_tests est réservé au développement (DEBUG=False). "
                "Relancez avec --force pour l'exécuter malgré tout."
            )

        universities = {}
        for name in (PARIS, LYON):
            university = University.objects.filter(name=name).first()
            if university is None:
                raise CommandError(
                    "Université « %s » introuvable. Lancez d'abord "
                    "`python manage.py seed_demo`." % name
                )
            universities[name] = university

        with transaction.atomic():
            for item in RESULTS:
                self.seed_result(universities, item)

        self.stdout.write(self.style.SUCCESS(
            "Seed tests de langue terminé : %s session(s), %s bilan(s)." % (
                LanguageTestSession.objects.count(),
                LanguageTestFeedback.objects.count(),
            )
        ))

    def resolve_student(self, universities, email):
        for university in universities.values():
            membership = Membership.objects.filter(
                university=university,
                user__email__iexact=email,
                role=Role.STUDENT,
                is_active=True,
            ).first()
            if membership is None:
                continue
            student = membership.ensure_profile()
            if not TutorAssignment.objects.filter(
                student=student, status=TutorAssignment.STATUS_ACTIVE,
            ).exists():
                raise CommandError(
                    "Aucune affectation référent active pour %s. Lancez d'abord "
                    "`python manage.py seed_coaching`." % email
                )
            return student
        raise CommandError(
            "Étudiant %s introuvable. Lancez d'abord `python manage.py seed_demo`." % email
        )

    def seed_result(self, universities, data):
        student = self.resolve_student(universities, data["email"])
        session_id = uuid.uuid5(SEED_NAMESPACE, data["key"])
        ended_at = timezone.now() - timedelta(days=data["days_ago"])
        started_at = ended_at - timedelta(seconds=data["duration_seconds"])
        transcript = [
            {"speaker": speaker, "text": text, "timestamp": None, "confidence": None}
            for speaker, text in data["transcript"]
        ]

        session, _ = LanguageTestSession.objects.update_or_create(
            id=session_id,
            defaults={
                "university": student.university,
                "student": student,
                "exam_type": data["exam_type"],
                "level": data["level"],
                "exercise_type": data["exercise_type"],
                "language": data["language"],
                "duration_seconds": data["duration_seconds"],
                "transcript": transcript,
                "status": data["status"],
                "ended_at": ended_at,
            },
        )
        LanguageTestSession.objects.filter(pk=session.pk).update(
            started_at=started_at, ended_at=ended_at,
        )

        feedback_data = data["feedback"]
        feedback, _ = LanguageTestFeedback.objects.update_or_create(
            session=session,
            defaults={
                "student": student,
                "university": student.university,
                "overall_level": feedback_data["overall_level"],
                "overall_verdict": feedback_data["overall_verdict"],
                "fluency_score": feedback_data["fluency_score"],
                "vocabulary_score": feedback_data["vocabulary_score"],
                "grammar_score": feedback_data["grammar_score"],
                "task_achievement_score": feedback_data["task_achievement_score"],
                "fluency_notes": list(feedback_data["fluency_notes"]),
                "vocabulary_notes": list(feedback_data["vocabulary_notes"]),
                "grammar_notes": list(feedback_data["grammar_notes"]),
                "task_achievement_notes": list(feedback_data["task_achievement_notes"]),
                "pronunciation_flags": list(feedback_data["pronunciation_flags"]),
                "recommendations": list(feedback_data["recommendations"]),
            },
        )
        LanguageTestFeedback.objects.filter(pk=feedback.pk).update(
            created_at=ended_at,
        )
