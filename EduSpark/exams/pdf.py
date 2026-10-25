"""Génération des documents officiels PDF (convocation, relevé, attestation).

reportlab (polices Helvetica, encodage latin-1) : les caractères hors
latin-1 (·, —, « »…) sont remplacés par des équivalents sûrs.
"""

import io

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

_PRIMARY = colors.HexColor("#002752")
_MUTED = colors.HexColor("#5b6472")
_LINE = colors.HexColor("#d5dae2")


def _safe(text):
    return (
        str(text or "")
        .replace("·", "-").replace("—", "-").replace("–", "-")
        .replace("«", '"').replace("»", '"').replace("’", "'")
        .replace("…", "...").replace("œ", "oe").replace("Œ", "Oe")
    )


def _footer(pdf, page_number=None):
    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(0.6)
    pdf.line(48, 52, A4[0] - 48, 52)
    pdf.setFont("Helvetica", 7.5)
    pdf.setFillColor(_MUTED)
    pdf.drawString(48, 40, _safe("Document généré par EduSpark le %s." % timezone.localdate().strftime("%d/%m/%Y")))
    pdf.drawRightString(A4[0] - 48, 40, "EduSpark - Hub educatif et creatif multimodal")


def _header(pdf, university_name, title):
    pdf.setFillColor(_PRIMARY)
    pdf.rect(0, A4[1] - 74, A4[0], 74, stroke=0, fill=1)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(48, A4[1] - 34, _safe(university_name))
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(48, A4[1] - 50, "Gestion des examens et des notes")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(48, A4[1] - 106, _safe(title))


def convocation_pdf(session, student):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("Convocation - %s" % _safe(session.title))
    _header(pdf, session.university.name, "Convocation officielle d'examen")

    pdf.setFont("Helvetica", 10.5)
    pdf.setFillColor(colors.black)
    pdf.drawString(48, A4[1] - 150, _safe(
        "Convoquee le : %s" % timezone.localtime(session.convoked_at).strftime("%d/%m/%Y %H:%M")
        if session.convoked_at else ""
    ))
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(48, A4[1] - 185, _safe(session.title))
    pdf.setFont("Helvetica", 10.5)
    pdf.drawString(48, A4[1] - 205, _safe(
        "Epreuve : %s%s" % (
            session.get_exam_type_display(),
            "  -  Code : %s" % session.code if session.code else "",
        )
    ))
    pdf.drawString(48, A4[1] - 225, _safe(
        "Classe : %s (%s)" % (session.school_class.name, session.school_class.academic_year)
    ))

    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(0.6)
    pdf.line(48, A4[1] - 240, A4[0] - 48, A4[1] - 240)

    rows = (
        ("Date", _safe(session.date_label)),
        ("Horaire", _safe("%s a %s" % (session.time_label, session.start_time.strftime("%H:%M")))),
        ("Salle", _safe(session.room)),
    )
    y = A4[1] - 265
    pdf.setFont("Helvetica-Bold", 10.5)
    for label, value in rows:
        pdf.drawString(48, y, label)
        pdf.setFont("Helvetica", 10.5)
        pdf.drawString(160, y, value)
        pdf.setFont("Helvetica-Bold", 10.5)
        y -= 20

    pdf.setStrokeColor(_LINE)
    pdf.line(48, y - 4, A4[0] - 48, y - 4)

    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(48, y - 26, "Etudiant(e) convoque(e)")
    pdf.setFont("Helvetica", 10.5)
    name = student.membership.user.get_full_name() or student.membership.user.email
    pdf.drawString(48, y - 46, _safe(name))
    pdf.drawString(48, y - 64, _safe(
        "Matricule : %s%s" % (
            student.student_number or "-",
            "  -  Filiere : %s" % student.program if student.program else "",
        )
    ))

    pdf.setFont("Helvetica-Oblique", 9)
    pdf.setFillColor(_MUTED)
    pdf.drawString(48, y - 110, _safe(
        "Se presenter 15 minutes avant le debut de l'epreuve avec une piece d'identite. "
        "Cette convocation vaut justificatif officiel de presence."
    ))

    _footer(pdf)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer


def _draw_grade_table(pdf, semester_rows, start_y):
    y = start_y
    header = ("Code", "Evaluation", "Coef.", "Note /20", "Statut")
    widths = (70, 250, 50, 70, 70)
    x = 48
    pdf.setFont("Helvetica-Bold", 9)
    pdf.setFillColor(_PRIMARY)
    for label, width in zip(header, widths):
        pdf.drawString(x, y, label)
        x += width
    y -= 8
    pdf.setStrokeColor(_LINE)
    pdf.line(48, y, 48 + sum(widths), y)
    y -= 16

    for semester in semester_rows:
        pdf.setFont("Helvetica-Bold", 9.5)
        pdf.setFillColor(colors.black)
        pdf.drawString(48, y, _safe(semester["label"]))
        y -= 14
        for grade in semester["rows"]:
            session = grade.session
            pdf.setFont("Helvetica", 9)
            pdf.setFillColor(colors.black)
            values = (
                session.code or "-",
                _safe(session.title[:44]),
                _safe(str(session.coefficient).replace(".", ",")),
                _safe(("%.2f" % grade.score).rstrip("0").rstrip(".").replace(".", ",")),
                "Valide" if grade.score >= 10 else "Non valide",
            )
            x = 48
            for value, width in zip(values, widths):
                pdf.drawString(x, y, value)
                x += width
            y -= 14
        y -= 8
    return y


def transcript_pdf(university, student, semester_rows, average, mention):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("Releve de notes")
    _header(pdf, university.name, "Releve de notes officiel")

    name = student.membership.user.get_full_name() or student.membership.user.email
    pdf.setFont("Helvetica", 10.5)
    pdf.setFillColor(colors.black)
    pdf.drawString(48, A4[1] - 140, _safe(name))
    pdf.drawString(48, A4[1] - 158, _safe(
        "Matricule : %s%s" % (
            student.student_number or "-",
            "  -  Filiere : %s" % student.program if student.program else "",
        )
    ))

    y = _draw_grade_table(pdf, semester_rows, A4[1] - 195)

    pdf.setStrokeColor(_LINE)
    pdf.line(48, y, A4[0] - 48, y)
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(48, y - 22, "Moyenne generale ponderee : %s / 20" % _safe(
        ("%.2f" % average).rstrip("0").rstrip(".").replace(".", ",") if average is not None else "-"
    ))
    pdf.drawString(48, y - 40, "Mention : %s" % _safe(mention or "-"))

    _footer(pdf)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer


def attestation_pdf(university, student, average, mention):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("Attestation de reussite")
    _header(pdf, university.name, "Attestation de reussite")

    name = student.membership.user.get_full_name() or student.membership.user.email
    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(colors.black)
    pdf.drawString(48, A4[1] - 150, _safe(
        "Le responsable des examens atteste que"
    ))
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(48, A4[1] - 176, _safe(name))
    pdf.setFont("Helvetica", 11)
    pdf.drawString(48, A4[1] - 200, _safe(
        "matricule %s, a valide l'annee universitaire avec une moyenne generale de"
        % (student.student_number or "-")
    ))
    pdf.setFont("Helvetica-Bold", 13)
    pdf.setFillColor(_PRIMARY)
    pdf.drawString(48, A4[1] - 226, "%s / 20" % _safe(
        ("%.2f" % average).rstrip("0").rstrip(".").replace(".", ",")
    ))
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(48, A4[1] - 250, _safe("Mention : %s" % (mention or "-")))

    pdf.setFont("Helvetica", 9.5)
    pdf.setFillColor(_MUTED)
    pdf.drawString(48, A4[1] - 300, _safe(
        "Cette attestation est delivree a titre officiel et peut etre presentee "
        "aupres des administrations et employeurs."
    ))

    _footer(pdf)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer
