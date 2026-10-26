from datetime import date, time
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from reportlab.pdfgen import canvas as pdf_canvas

from accounts.models import SchoolClass
from courses.models import Subject
from exams.models import ExamSession, ExamSubject, GradeRecord, semester_for

SESSION_ROWS = (
    ("Université Paris Cité", "Licence 3 Informatique", "INF501 · Algorithmique avancée",
     ExamSession.TYPE_ECRIT, date(2026, 11, 3), time(8, 30), time(10, 30), "Amphi A"),
    ("Université Paris Cité", "Licence 3 Informatique", "MAT301 · Probabilités",
     ExamSession.TYPE_ECRIT, date(2026, 11, 6), time(13, 30), time(15, 30), "Salle 204"),
    ("Université Paris Cité", "Master 1 Génie Logiciel", "INF502 · Systèmes distribués",
     ExamSession.TYPE_ECRIT, date(2026, 11, 4), time(8, 30), time(10, 30), "Amphi B"),
    ("Université Paris Cité", "Master 1 Génie Logiciel", "GEN401 · Architecture applicative",
     ExamSession.TYPE_ECRIT, date(2026, 11, 7), time(10, 15), time(12, 15), "Salle 204"),
    ("Université de Lyon", "Master 1 Mathématiques", "MAT401 · Analyse fonctionnelle",
     ExamSession.TYPE_ECRIT, date(2026, 11, 3), time(10, 15), time(12, 15), "Amphi C"),
    ("Université de Lyon", "Master 1 Mathématiques", "MAT402 · Probabilités avancées",
     ExamSession.TYPE_ECRIT, date(2026, 11, 6), time(8, 30), time(10, 30), "Salle 105"),
    ("Université de Lyon", "Master 1 Mathématiques", "MAT403 · Analyse numérique",
     ExamSession.TYPE_ECRIT, date(2026, 11, 10), time(9, 0), time(11, 0), "Salle 108"),
)

RECORD_ROWS = (
    ("Université Paris Cité", "Licence 3 Informatique", 74, 66, Decimal("12.40"), True, True),
    ("Université Paris Cité", "Master 1 Génie Logiciel", 24, 22, Decimal("13.10"), False, False),
    ("Université de Lyon", "Master 1 Mathématiques", 36, 29, Decimal("12.90"), False, False),
)

ADMIN_EMAILS = {
    "Université Paris Cité": "admin.paris@u-paris.fr",
    "Université de Lyon": "admin.lyon@univ-lyon.fr",
}


class Command(BaseCommand):
    help = "Crée les sessions d'examen et relevés de démonstration (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Exécuter même quand DEBUG=False.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "seed_exams est réservé au développement (DEBUG=False). "
                "Relancez avec --force pour l'exécuter malgré tout."
            )

        now = timezone.now()
        sessions_created = 0
        records_created = 0
        records_updated = 0

        with transaction.atomic():
            for (university_name, class_name, title, exam_type, exam_date,
                 start, end, room) in SESSION_ROWS:
                school_class = SchoolClass.objects.filter(
                    university__name=university_name, name=class_name,
                ).first()
                if school_class is None:
                    self.stdout.write(self.style.WARNING(
                        "Classe introuvable : %s / %s" % (university_name, class_name)
                    ))
                    continue
                admin = User.objects.filter(
                    email__iexact=ADMIN_EMAILS.get(university_name, ""),
                ).first()
                code = title.split("·", 1)[0].strip()
                subject = Subject.objects.filter(
                    university=school_class.university, code=code,
                ).first()
                defaults = {
                    "university": school_class.university,
                    "course_subject": subject,
                    "exam_type": exam_type,
                    "date": exam_date,
                    "start_time": start,
                    "end_time": end,
                    "room": room,
                    "created_by": admin,
                }
                if subject is not None:
                    defaults["code"] = subject.code
                    defaults["coefficient"] = subject.coefficient
                _session, created = ExamSession.objects.update_or_create(
                    school_class=school_class,
                    title=title,
                    defaults=defaults,
                )
                sessions_created += int(created)

            for (university_name, class_name, students, admitted, average,
                 pv_signed, published) in RECORD_ROWS:
                school_class = SchoolClass.objects.filter(
                    university__name=university_name, name=class_name,
                ).first()
                if school_class is None:
                    continue
                admin = User.objects.filter(
                    email__iexact=ADMIN_EMAILS.get(university_name, ""),
                ).first()
                record, created = GradeRecord.objects.get_or_create(
                    school_class=school_class,
                    semester=semester_for(school_class),
                    defaults={"university": school_class.university},
                )
                record.university = school_class.university
                record.students_count = students
                record.admitted_count = admitted
                record.average = average
                record.pv_signed = pv_signed
                record.transcript_published = published
                record.pv_signed_at = now if pv_signed else None
                record.pv_signed_by = admin if pv_signed else None
                record.published_at = now if published else None
                record.save()
                if created:
                    records_created += 1
                else:
                    records_updated += 1

            for school_class in SchoolClass.objects.all():
                GradeRecord.objects.get_or_create(
                    school_class=school_class,
                    semester=semester_for(school_class),
                    defaults={"university": school_class.university},
                )

            mat401 = ExamSession.objects.filter(
                school_class__university__name="Université de Lyon",
                school_class__name="Master 1 Mathématiques",
                title="MAT401 · Analyse fonctionnelle",
            ).first()
            if mat401 is not None:
                admin = User.objects.filter(
                    email__iexact=ADMIN_EMAILS["Université de Lyon"],
                ).first()
                buffer = BytesIO()
                canvas = pdf_canvas.Canvas(buffer)
                canvas.setTitle("Sujet — %s" % mat401.title)
                canvas.drawString(72, 780, "Sujet d'épreuve — %s (MAT401)" % mat401.title)
                canvas.drawString(72, 750, "Ceci est un sujet de démonstration généré par seed_exams.")
                canvas.showPage()
                canvas.save()
                ExamSubject.objects.get_or_create(
                    session=mat401,
                    defaults={
                        "file": ContentFile(buffer.getvalue(), name="sujet-mat401.pdf"),
                        "created_by": admin,
                        "published_at": now,
                    },
                )

        self.stdout.write(self.style.SUCCESS(
            "Seed examens terminé : %s sessions créées, %s relevés créés, %s mis à jour."
            % (sessions_created, records_created, records_updated)
        ))
