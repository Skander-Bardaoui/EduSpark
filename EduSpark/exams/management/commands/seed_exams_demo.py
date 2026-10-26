"""Jeu de données de démonstration pour le module Examens.

Le commandement remplit les trois parcours (QCM, projet, oral), les notes,
les relevés et les tableaux de bord. Il est prévu pour le développement.
"""

from datetime import timedelta
from decimal import Decimal
from io import BytesIO
import zipfile

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import ProfessorProfile, SchoolClass, StudentProfile, University
from courses.models import Course, Subject
from exams.models import (
    ExamSession, GradeRecord, OralAttempt, OralTopic, ProjectCriterion,
    ProjectSubmission, Quiz, QuizAnswer, QuizAttempt, QuizChoice, QuizQuestion,
    StudentGrade, semester_for,
)
from exams.views import _refresh_record_stats, _sync_exam_grade, _sync_quiz_grade


PARIS_EMAIL = "admin.paris@u-paris.fr"
LYON_EMAIL = "admin.lyon@univ-lyon.fr"
PROF_EMAIL = "prof.test@eduspark.local"


def _student_feedback(score_20):
    if score_20 >= 16:
        summary = "Très bon résultat : les notions principales sont maîtrisées."
        strengths = ["Les réponses montrent une bonne compréhension du cours."]
    elif score_20 >= 10:
        summary = "Résultat correct : les bases sont acquises, quelques points restent à consolider."
        strengths = ["Le seuil de validation est atteint."]
    else:
        summary = "Les bases doivent être retravaillées avant la prochaine évaluation."
        strengths = ["La tentative a bien été enregistrée."]
    return {
        "source": "local",
        "summary": summary,
        "strengths": strengths,
        "focus": ["Revoir les notions du cours et refaire les exercices d'application."],
        "next_steps": ["Planifier une séance de révision et solliciter l'enseignant."],
    }


class Command(BaseCommand):
    help = "Vide puis remplit les tables du module Examens avec un jeu de démonstration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Supprime toutes les données du module Examens avant le seed.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Exécuter même quand DEBUG=False.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "seed_exams_demo est réservé au développement. "
                "Relancez avec --force pour l'exécuter malgré tout."
            )

        with transaction.atomic():
            if options["reset"]:
                self.reset_exams()
            self.seed()

        self.stdout.write(self.style.SUCCESS(
            "Seed Examens terminé : %s sessions, %s QCM, %s projets, %s oraux."
            % (
                ExamSession.objects.count(), Quiz.objects.count(),
                ProjectSubmission.objects.count(), OralAttempt.objects.count(),
            )
        ))
        self.stdout.write(
            "Comptes de démonstration :\n"
            "  Admin Paris : %s / Admin12345!\n"
            "  Admin Lyon  : %s / Admin12345!\n"
            "  Professeur  : %s / Prof12345!\n"
            "  Étudiants   : test.ui@example.com, ines.bernard@u-paris.fr, "
            "yanis.leroy@u-paris.fr / Etudiant12345!\n"
            "  Lyon        : lucas.moreau@univ-lyon.fr, sofia.benali@univ-lyon.fr "
            "/ Etudiant12345!"
            % (PARIS_EMAIL, LYON_EMAIL, PROF_EMAIL)
        )

    def reset_exams(self):
        for submission in ProjectSubmission.objects.all().only("file"):
            if submission.file:
                submission.file.delete(save=False)
        for model in (
            StudentGrade, ProjectSubmission, OralAttempt, ProjectCriterion,
            OralTopic, QuizAttempt, QuizAnswer, QuizChoice, QuizQuestion, Quiz,
            ExamSession, GradeRecord,
        ):
            model.objects.all().delete()

    def seed(self):
        self.now = timezone.now()
        self.paris = University.objects.get(code="UPC")
        self.lyon = University.objects.get(code="UDL")
        self.paris_l3 = SchoolClass.objects.get(
            university=self.paris, name="Licence 3 Informatique",
        )
        self.paris_m1 = SchoolClass.objects.get(
            university=self.paris, name="Master 1 Génie Logiciel",
        )
        self.lyon_m1 = SchoolClass.objects.get(
            university=self.lyon, name="Master 1 Mathématiques",
        )
        self.admin_paris = User.objects.get(email__iexact=PARIS_EMAIL)
        self.admin_lyon = User.objects.get(email__iexact=LYON_EMAIL)
        self.helene = User.objects.get(email__iexact=PROF_EMAIL)
        self.mariam = User.objects.get(email__iexact="m.traore@u-paris.fr")

        self.seed_paris_l3()
        self.seed_paris_m1()
        self.seed_lyon()
        self.finalize_records()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def subject(self, university, code):
        return Subject.objects.get(university=university, code=code)

    def course(self, university, subject):
        return Course.objects.filter(
            university=university, subject=subject,
        ).order_by("id").first()

    def students(self, school_class):
        return list(
            StudentProfile.objects.filter(groups__school_class=school_class)
            .distinct()
            .select_related("membership__user")
            .order_by("membership__user__last_name")
        )

    def student_by_email(self, school_class, email):
        return StudentProfile.objects.get(
            groups__school_class=school_class,
            membership__user__email__iexact=email,
        )

    def session(self, school_class, subject_code, title, exam_type,
                start, end, created_by, instructions=""):
        subject = self.subject(school_class.university, subject_code)
        return ExamSession.objects.create(
            university=school_class.university,
            school_class=school_class,
            course_subject=subject,
            title=title,
            exam_type=exam_type,
            instructions=instructions,
            opens_at=start,
            closes_at=end,
            created_by=created_by,
        )

    def quiz(self, session, questions, *, published=True, analysis=None):
        course = self.course(session.university, session.course_subject)
        quiz = Quiz.objects.create(
            university=session.university,
            session=session,
            course=course,
            instructions="Lisez chaque question puis sélectionnez une seule réponse.",
            duration_minutes=30,
            question_count=len(questions),
            pass_score=Decimal("10"),
            status=Quiz.STATUS_PUBLISHED if published else Quiz.STATUS_DRAFT,
            published_at=self.now if published else None,
            generated_by_ai=bool(analysis),
            ai_model="demo-local" if analysis else "",
            source_chars=2400 if analysis else 0,
            ai_analysis=analysis or {},
            ai_analysis_at=self.now if analysis else None,
            created_by=session.created_by,
        )
        for order, question in enumerate(questions, start=1):
            item = QuizQuestion.objects.create(
                quiz=quiz,
                order=order,
                prompt=question["prompt"],
                explanation=question.get("explanation", ""),
                points=Decimal("1"),
            )
            for choice_order, (label, is_correct) in enumerate(
                question["choices"], start=1,
            ):
                QuizChoice.objects.create(
                    question=item,
                    order=choice_order,
                    label=label,
                    is_correct=is_correct,
                )
        return quiz

    def attempt(self, quiz, student, correct_count, *, absent=False):
        questions = list(quiz.questions.prefetch_related("choices"))
        max_score = sum((question.points for question in questions), Decimal("0"))
        score = sum(
            (question.points for question in questions[:correct_count]),
            Decimal("0"),
        )
        started = quiz.session.opens_at + timedelta(minutes=5)
        deadline = started + timedelta(minutes=quiz.duration_minutes)
        if absent:
            attempt = QuizAttempt.objects.create(
                university=quiz.university,
                quiz=quiz,
                student=student,
                started_at=started,
                deadline_at=deadline,
                question_order=[question.pk for question in questions],
                submitted_at=quiz.session.closes_at,
                score=Decimal("0"),
                max_score=max_score,
                status=QuizAttempt.STATUS_EXPIRED,
                ai_feedback=_student_feedback(0),
                ai_feedback_at=self.now,
            )
            _sync_quiz_grade(attempt, Decimal("0"), max_score, absent=True)
            return attempt

        attempt = QuizAttempt.objects.create(
            university=quiz.university,
            quiz=quiz,
            student=student,
            started_at=started,
            deadline_at=deadline,
            question_order=[question.pk for question in questions],
            submitted_at=started + timedelta(minutes=12),
            score=score,
            max_score=max_score,
            status=QuizAttempt.STATUS_SUBMITTED,
            ai_feedback=_student_feedback(
                (score * Decimal("20") / max_score) if max_score else Decimal("0")
            ),
            ai_feedback_at=self.now,
        )
        for index, question in enumerate(questions):
            choices = list(question.choices.all())
            if index < correct_count:
                selected = next(choice for choice in choices if choice.is_correct)
            else:
                selected = next(choice for choice in choices if not choice.is_correct)
            QuizAnswer.objects.create(
                attempt=attempt, question=question, selected_choice=selected,
            )
        _sync_quiz_grade(attempt, score, max_score)
        return attempt

    def zip_payload(self, student):
        name = student.membership.user.get_full_name() or student.membership.user.email
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "README.md",
                "# Projet de %s\n\nProjet de démonstration pour EduSpark.\n" % name,
            )
            archive.writestr(
                "src/main.py",
                "def solve(graph):\n"
                "    \"\"\"Parcours de graphe de démonstration.\"\"\"\n"
                "    return list(graph)\n",
            )
            archive.writestr(
                "docs/rapport.md",
                "# Rapport\n\n## Objectifs\nAnalyser un graphe et produire un rapport.\n"
                "\n## Résultats\nLe prototype fonctionne sur les jeux de test.\n",
            )
        return buffer.getvalue()

    def project_submission(self, session, student, *, status,
                           ai_score=None, final_score=None, feedback="",
                           ai_result=None, graded_by=None):
        payload = self.zip_payload(student)
        original_name = "projet-%s.zip" % (student.membership.user.username.split("@")[0])
        submission = ProjectSubmission(
            university=session.university,
            session=session,
            student=student,
            original_name=original_name,
            size=len(payload),
            submitted_at=self.now - timedelta(days=1),
            status=status,
            ai_result=ai_result or {},
            ai_score=ai_score,
            ai_model="demo-local" if ai_score is not None else "",
            ai_evaluated_at=self.now if ai_score is not None else None,
            final_score=final_score,
            feedback=feedback,
            graded_by=graded_by if final_score is not None else None,
            graded_at=self.now if final_score is not None else None,
        )
        submission.file.save(original_name, ContentFile(payload), save=False)
        submission.save()
        if final_score is not None:
            _sync_exam_grade(
                session, student, final_score, comment=feedback,
                graded_by=graded_by,
            )
        return submission

    def ai_project_result(self, session, score, summary):
        criteria = []
        for index, criterion in enumerate(session.project_criteria.all()):
            criterion_score = Decimal(score) + Decimal("1.5") - Decimal(index)
            criteria.append({
                "label": criterion.label,
                "score": float(max(Decimal("0"), min(Decimal("20"), criterion_score))),
                "weight": criterion.weight,
                "met": index < 3,
                "comment": "Critère correctement traité dans le dépôt.",
            })
        return {
            "source": "local",
            "model": "demo-local",
            "summary": summary,
            "overall_comment": (
                "Le projet est structuré, documenté et respecte globalement "
                "le cahier des charges."
            ),
            "file_count": 3,
            "extracted_chars": 1480,
            "criteria": criteria,
            "score_20": float(score),
        }

    def oral_topics(self, session, titles):
        return [
            OralTopic.objects.create(
                session=session, title=title, order=index,
                instructions="Préparez une présentation de 10 minutes puis répondez aux questions.",
                duration_minutes=10,
            )
            for index, title in enumerate(titles, start=1)
        ]

    def oral_attempt(self, session, student, topic, *, score=None,
                     feedback="", graded_by=None, drawn_minutes_ago=30):
        drawn_at = self.now - timedelta(minutes=drawn_minutes_ago)
        attempt = OralAttempt.objects.create(
            university=session.university,
            session=session,
            student=student,
            topic=topic,
            drawn_at=drawn_at,
            preparation_deadline=drawn_at + timedelta(minutes=topic.duration_minutes),
            notes="Sujet préparé par l'étudiant.",
            score=score,
            feedback=feedback,
            status=(
                OralAttempt.STATUS_GRADED if score is not None
                else OralAttempt.STATUS_DRAWN
            ),
            graded_by=graded_by if score is not None else None,
            graded_at=self.now if score is not None else None,
        )
        if score is not None:
            _sync_exam_grade(
                session, student, score, comment=feedback, graded_by=graded_by,
            )
        return attempt

    # ------------------------------------------------------------------
    # Paris — Licence 3 Informatique
    # ------------------------------------------------------------------
    def seed_paris_l3(self):
        camille = self.student_by_email(self.paris_l3, "test.ui@example.com")
        ines = self.student_by_email(self.paris_l3, "ines.bernard@u-paris.fr")
        yanis = self.student_by_email(self.paris_l3, "yanis.leroy@u-paris.fr")

        open_start = self.now - timedelta(hours=2)
        open_end = self.now + timedelta(days=7)
        closed_start = self.now - timedelta(days=15)
        closed_end = self.now - timedelta(days=14)
        upcoming_start = self.now + timedelta(days=4)
        upcoming_end = upcoming_start + timedelta(hours=2)

        qcm = self.session(
            self.paris_l3, "INF501", "INF501 · QCM Algorithmique",
            ExamSession.TYPE_QCM, open_start, open_end, self.helene,
            "QCM d'entraînement sur les graphes, la complexité et les parcours.",
        )
        qcm_quiz = self.quiz(
            qcm,
            [
                {
                    "prompt": "Quelle structure de données est utilisée par le parcours en largeur ?",
                    "explanation": "Le BFS utilise une file FIFO.",
                    "choices": [
                        ("Une file (FIFO)", True), ("Une pile (LIFO)", False),
                        ("Un tas binaire", False), ("Une table de hachage", False),
                    ],
                },
                {
                    "prompt": "Quelle est la complexité de Dijkstra avec un tas binaire ?",
                    "explanation": "Chaque arête est relaxée et le tas coûte log V.",
                    "choices": [
                        ("O((V + E) log V)", True), ("O(V²)", False),
                        ("O(E)", False), ("O(V log E)", False),
                    ],
                },
                {
                    "prompt": "Un graphe non orienté est connexe si…",
                    "explanation": "Tout couple de sommets est relié par un chemin.",
                    "choices": [
                        ("tout couple de sommets est relié par un chemin", True),
                        ("il ne contient aucun cycle", False),
                        ("chaque sommet est de degré 2", False),
                        ("il possède exactement un cycle", False),
                    ],
                },
            ],
            analysis={
                "source": "local",
                "summary": "Les notions de parcours et de complexité sont globalement acquises.",
                "difficulty": "Niveau intermédiaire",
                "issues": ["La distinction entre BFS et DFS reste à consolider."],
                "recommendations": ["Refaire un exercice de parcours sur un graphe pondéré."],
            },
        )
        self.attempt(qcm_quiz, camille, 2)
        self.attempt(qcm_quiz, ines, 3)

        upcoming = self.session(
            self.paris_l3, "INF504", "INF504 · QCM Bases de données",
            ExamSession.TYPE_QCM, upcoming_start, upcoming_end, self.mariam,
            "QCM à venir sur le modèle relationnel et les requêtes SQL.",
        )
        self.quiz(
            upcoming,
            [
                {
                    "prompt": "Quelle clé identifie de façon unique une ligne d'une table ?",
                    "explanation": "La clé primaire est unique et non nulle.",
                    "choices": [
                        ("La clé primaire", True), ("La clé étrangère", False),
                        ("Un index", False), ("Une vue", False),
                    ],
                },
                {
                    "prompt": "Quel mot-clé filtre les lignes d'une requête SQL ?",
                    "explanation": "WHERE s'applique aux lignes, HAVING aux groupes.",
                    "choices": [
                        ("WHERE", True), ("GROUP BY", False),
                        ("ORDER BY", False), ("JOIN", False),
                    ],
                },
            ],
            published=False,
        )

        closed = self.session(
            self.paris_l3, "LAN301", "LAN301 · QCM Anglais scientifique",
            ExamSession.TYPE_QCM, closed_start, closed_end, self.mariam,
            "QCM terminé sur la compréhension écrite et le vocabulaire scientifique.",
        )
        closed_quiz = self.quiz(
            closed,
            [
                {
                    "prompt": "Choose the correct sentence.",
                    "explanation": "Le présent simple convient pour une vérité générale.",
                    "choices": [
                        ("The experiment shows a clear trend.", True),
                        ("The experiment show a clear trend.", False),
                        ("The experiment showing a clear trend.", False),
                        ("The experiment shown a clear trend.", False),
                    ],
                },
                {
                    "prompt": "What is the past participle of “write” ?",
                    "explanation": "write — wrote — written.",
                    "choices": [
                        ("written", True), ("wrote", False),
                        ("writed", False), ("writing", False),
                    ],
                },
            ],
        )
        self.attempt(closed_quiz, camille, 2)
        self.attempt(closed_quiz, ines, 1)
        self.attempt(closed_quiz, yanis, 0, absent=True)

        project = self.session(
            self.paris_l3, "INF501", "INF501 · Projet Graphes",
            ExamSession.TYPE_PROJECT, open_start - timedelta(days=1),
            open_end + timedelta(days=3), self.helene,
            "Déposez une archive ZIP contenant le code, le README et le rapport.",
        )
        ProjectCriterion.ensure_defaults(project)
        ai_result = self.ai_project_result(
            project, 16.5, "Projet complet et bien structuré.",
        )
        self.project_submission(
            project, camille, status=ProjectSubmission.STATUS_AI_EVALUATED,
            ai_score=Decimal("16.50"), ai_result=ai_result,
        )
        self.project_submission(
            project, ines, status=ProjectSubmission.STATUS_GRADED,
            ai_score=Decimal("14.00"), final_score=Decimal("15.50"),
            feedback="Bon travail, documentation claire et code lisible.",
            ai_result=self.ai_project_result(
                project, 14, "Projet fonctionnel, quelques améliorations possibles.",
            ),
            graded_by=self.helene,
        )

        oral = self.session(
            self.paris_l3, "INF501", "INF501 · Oral Algorithmique",
            ExamSession.TYPE_ORAL, open_start, open_end, self.helene,
            "Tirage au sort d'un sujet, 10 minutes de préparation puis passage oral.",
        )
        topics = self.oral_topics(oral, [
            "Sujet A · Parcours en largeur",
            "Sujet B · Plus court chemin",
            "Sujet C · Arbres couvrants",
            "Sujet D · Complexité algorithmique",
        ])
        self.oral_attempt(
            oral, camille, topics[0], drawn_minutes_ago=8,
        )
        self.oral_attempt(
            oral, ines, topics[1], score=Decimal("16.00"),
            feedback="Exposé clair, bonne maîtrise des graphes.",
            graded_by=self.helene, drawn_minutes_ago=180,
        )

    # ------------------------------------------------------------------
    # Paris — Master 1 Génie Logiciel
    # ------------------------------------------------------------------
    def seed_paris_m1(self):
        open_start = self.now - timedelta(hours=1)
        open_end = self.now + timedelta(days=10)
        upcoming_start = self.now + timedelta(days=6)
        upcoming_end = upcoming_start + timedelta(hours=3)

        qcm = self.session(
            self.paris_m1, "GEN401", "GEN401 · QCM Architecture applicative",
            ExamSession.TYPE_QCM, open_start, open_end, self.helene,
            "QCM sur les couches, les dépendances et les patterns d'architecture.",
        )
        self.quiz(
            qcm,
            [
                {
                    "prompt": "Quel pattern isole la logique métier de l'interface ?",
                    "explanation": "Le pattern MVC sépare les responsabilités.",
                    "choices": [
                        ("MVC", True), ("Singleton", False),
                        ("Factory", False), ("Observer", False),
                    ],
                },
                {
                    "prompt": "Une dépendance circulaire entre modules est…",
                    "explanation": "Elle rend les tests et l'évolution plus difficiles.",
                    "choices": [
                        ("à éviter autant que possible", True),
                        ("obligatoire", False),
                        ("sans impact", False),
                        ("recommandée", False),
                    ],
                },
            ],
        )

        project = self.session(
            self.paris_m1, "GEN401", "GEN401 · Projet Architecture",
            ExamSession.TYPE_PROJECT, upcoming_start, upcoming_end, self.helene,
            "Projet à venir : concevoir et documenter une architecture applicative.",
        )
        ProjectCriterion.ensure_defaults(project)

        oral = self.session(
            self.paris_m1, "GEN401", "GEN401 · Oral Architecture",
            ExamSession.TYPE_ORAL, upcoming_start, upcoming_end, self.helene,
            "Oral à venir sur les choix d'architecture et les compromis techniques.",
        )
        self.oral_topics(oral, [
            "Sujet A · Architecture en couches",
            "Sujet B · Microservices et monolithe",
            "Sujet C · Qualité et testabilité",
        ])

    # ------------------------------------------------------------------
    # Lyon — Master 1 Mathématiques
    # ------------------------------------------------------------------
    def seed_lyon(self):
        lucas = self.student_by_email(self.lyon_m1, "lucas.moreau@univ-lyon.fr")
        sofia = self.student_by_email(self.lyon_m1, "sofia.benali@univ-lyon.fr")

        open_start = self.now - timedelta(hours=3)
        open_end = self.now + timedelta(days=8)
        closed_start = self.now - timedelta(days=12)
        closed_end = self.now - timedelta(days=11)

        qcm = self.session(
            self.lyon_m1, "MAT401", "MAT401 · QCM Analyse fonctionnelle",
            ExamSession.TYPE_QCM, open_start, open_end, self.helene,
            "QCM sur les suites, la continuité et les espaces complets.",
        )
        qcm_quiz = self.quiz(
            qcm,
            [
                {
                    "prompt": "Dans un espace complet, toute suite de Cauchy…",
                    "explanation": "C'est la définition de la complétude.",
                    "choices": [
                        ("converge", True), ("diverge", False),
                        ("est stationnaire", False), ("est bornée mais divergente", False),
                    ],
                },
                {
                    "prompt": "Le théorème des valeurs intermédiaires demande…",
                    "explanation": "La continuité sur un intervalle fermé borné est suffisante.",
                    "choices": [
                        ("une fonction continue sur un intervalle", True),
                        ("une fonction dérivable", False),
                        ("une fonction monotone", False),
                        ("une fonction bornée", False),
                    ],
                },
            ],
            analysis={
                "source": "local",
                "summary": "Les notions de convergence et de continuité sont bien comprises.",
                "difficulty": "Niveau intermédiaire",
                "issues": ["Quelques confusions sur les espaces complets."],
                "recommendations": ["Travailler les exemples de suites de Cauchy."],
            },
        )
        self.attempt(qcm_quiz, lucas, 2)
        self.attempt(qcm_quiz, sofia, 1)

        closed = self.session(
            self.lyon_m1, "MAT402", "MAT402 · QCM Probabilités avancées",
            ExamSession.TYPE_QCM, closed_start, closed_end, self.helene,
            "QCM terminé sur les variables aléatoires et les convergences.",
        )
        closed_quiz = self.quiz(
            closed,
            [
                {
                    "prompt": "La loi des grands nombres concerne…",
                    "explanation": "Elle décrit la convergence de la moyenne empirique.",
                    "choices": [
                        ("la moyenne empirique", True), ("la médiane", False),
                        ("la variance seulement", False), ("la densité", False),
                    ],
                },
                {
                    "prompt": "Une variable aléatoire gaussienne est caractérisée par…",
                    "explanation": "Sa moyenne et son écart-type suffisent.",
                    "choices": [
                        ("sa moyenne et son écart-type", True),
                        ("son mode uniquement", False),
                        ("sa médiane uniquement", False),
                        ("son support", False),
                    ],
                },
            ],
        )
        self.attempt(closed_quiz, lucas, 0, absent=True)
        self.attempt(closed_quiz, sofia, 2)

        project = self.session(
            self.lyon_m1, "MAT401", "MAT401 · Projet Analyse numérique",
            ExamSession.TYPE_PROJECT, open_start - timedelta(days=1),
            open_end + timedelta(days=4), self.helene,
            "Déposez un ZIP avec le code, les résultats numériques et le rapport.",
        )
        ProjectCriterion.ensure_defaults(project)
        self.project_submission(
            project, lucas, status=ProjectSubmission.STATUS_AI_EVALUATED,
            ai_score=Decimal("17.00"),
            ai_result=self.ai_project_result(
                project, 17, "Projet très complet et rigoureux.",
            ),
        )
        self.project_submission(
            project, sofia, status=ProjectSubmission.STATUS_GRADED,
            ai_score=Decimal("13.00"), final_score=Decimal("13.50"),
            feedback="Résultats corrects, rapport à enrichir.",
            ai_result=self.ai_project_result(
                project, 13, "Projet correct, analyse à approfondir.",
            ),
            graded_by=self.helene,
        )

        oral = self.session(
            self.lyon_m1, "MAT402", "MAT402 · Oral Probabilités",
            ExamSession.TYPE_ORAL, open_start, open_end, self.helene,
            "Tirage au sort d'un sujet de probabilités, préparation puis oral.",
        )
        topics = self.oral_topics(oral, [
            "Sujet A · Loi des grands nombres",
            "Sujet B · Théorème central limite",
            "Sujet C · Chaînes de Markov",
        ])
        self.oral_attempt(oral, lucas, topics[0], drawn_minutes_ago=12)
        self.oral_attempt(
            oral, sofia, topics[1], score=Decimal("14.00"),
            feedback="Présentation structurée, quelques imprécisions.",
            graded_by=self.helene, drawn_minutes_ago=240,
        )

    # ------------------------------------------------------------------
    # Relevés officiels
    # ------------------------------------------------------------------
    def finalize_records(self):
        for school_class in (self.paris_l3, self.paris_m1, self.lyon_m1):
            record, _created = GradeRecord.objects.get_or_create(
                school_class=school_class,
                semester=semester_for(school_class),
                defaults={"university": school_class.university},
            )
            record.university = school_class.university
            _refresh_record_stats(record)
            if school_class in (self.paris_l3, self.lyon_m1):
                record.pv_signed = True
                record.pv_signed_at = self.now
                record.pv_signed_by = (
                    self.admin_paris if school_class == self.paris_l3
                    else self.admin_lyon
                )
                record.transcript_published = True
                record.published_at = self.now
            else:
                record.pv_signed = False
                record.pv_signed_at = None
                record.pv_signed_by = None
                record.transcript_published = False
                record.published_at = None
            record.save()
