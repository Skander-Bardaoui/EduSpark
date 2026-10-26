import csv
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from django.contrib import messages
from django.core.mail import send_mail
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, ImageChops

from accounts.decorators import role_required
from accounts.models import Profil, ProfessorProfile, SchoolClass, StudentProfile

from .forms import ExamSessionForm, GradeRecordForm
from .models import (
    DEFAULT_CRITERIA, ExamCopy, ExamCopyPage, ExamSession, ExamSubject,
    GradeRecord, JuryMember, StudentGrade, semester_for,
)
from .pdf import attestation_pdf, convocation_pdf, transcript_pdf

EXAM_SEMESTER = "Semestre 1 · 2025-2026"
COPY_EXTENSIONS = (".pdf", ".zip")
ABSENT_COMMENT = "Absent — aucune copie soumise."


def _is_absent_grade(grade):
    return bool(grade and (grade.comment or "").strip().startswith("Absent"))


def _tenant_classes(request):
    return SchoolClass.objects.filter(university=request.university).order_by("name")


def _tenant_sessions(request):
    return (
        ExamSession.objects.filter(university=request.university)
        .select_related("school_class", "created_by", "course_subject", "subject")
        .order_by("date", "start_time", "school_class__name")
    )


def _tenant_records(request):
    """Relevés de la session courante, un par classe de l'établissement."""
    records = []
    for school_class in _tenant_classes(request):
        record, _created = GradeRecord.objects.get_or_create(
            school_class=school_class,
            semester=semester_for(school_class),
            defaults={"university": request.university},
        )
        records.append(record)
    return records


def _count_room_conflicts(sessions):
    conflicts = 0
    for index, first in enumerate(sessions):
        for second in sessions[index + 1:]:
            if (
                first.plan_group
                and first.plan_group == second.plan_group
            ):
                # Une même planification multi-classes partage volontairement
                # la salle : ce n'est pas un conflit.
                continue
            if (
                first.date == second.date
                and first.room
                and first.room.casefold() == second.room.casefold()
                and first.start_time < second.end_time
                and second.start_time < first.end_time
            ):
                conflicts += 1
    return conflicts


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="%s"' % filename
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return response


def _next_or(request, fallback):
    target = request.POST.get("next")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)
    return redirect(fallback)


def _notify_planning(session, request):
    """Envoie la planification aux enseignants et étudiants de la classe."""
    sender = request.user.get_full_name() or request.user.email
    common = (
        "Épreuve : %s (%s)\n"
        "Classe : %s\n"
        "Date : %s, de %s à %s\n"
        "Salle : %s\n\n"
        % (
            session.title, session.get_exam_type_display(),
            session.school_class.name, session.date_label,
            session.start_time.strftime("%H:%M"),
            session.end_time.strftime("%H:%M"),
            session.room or "à définir",
        )
    )
    for professor in session.school_class.professors.select_related("membership__user"):
        user = professor.membership.user
        send_mail(
            "Nouvelle épreuve à préparer — %s" % session.title,
            "Bonjour %s,\n\n"
            "Une session d'examen vous a été assignée par l'administration :\n\n"
            "%s"
            "Déposez puis publiez le sujet d'épreuve depuis votre portail "
            "« Sessions d'examen ». Le sujet ne sera accessible aux étudiants "
            "que pendant la durée de l'épreuve.\n\n"
            "Cordialement,\n%s" % (
                user.get_full_name() or user.email, common, sender,
            ),
            None, [user.email], fail_silently=True,
        )
    for student in _session_students(session).select_related("membership__user"):
        user = student.membership.user
        send_mail(
            "Planification d'examen — %s" % session.title,
            "Bonjour %s,\n\n"
            "L'administration a planifié une épreuve pour votre classe :\n\n"
            "%s"
            "Retrouvez-la dans votre espace « Mes Examens ». Le sujet et le "
            "dépôt de copie (PDF ou ZIP) seront accessibles uniquement pendant "
            "la durée de l'épreuve.\n\n"
            "Cordialement,\n%s" % (
                user.get_full_name() or user.email, common, sender,
            ),
            None, [user.email], fail_silently=True,
        )


def _sessions_context(request, *, create_form=None, edit_form=None,
                      edit_session=None, open_modal=None):
    sessions = list(_tenant_sessions(request))
    if create_form is None:
        create_form = ExamSessionForm(
            university=request.university, prefix="create", multi=True,
        )
    conflicts = _count_room_conflicts(sessions)
    return {
        "semester": EXAM_SEMESTER,
        "sessions": sessions,
        "session_count": len(sessions),
        "convocation_count": sum(1 for session in sessions if session.is_convoked),
        "room_count": len({session.room for session in sessions if session.room}),
        "published_subject_count": sum(
            1 for session in sessions
            if getattr(session, "subject", None) is not None
            and session.subject.is_published
        ),
        "conflict_count": conflicts,
        "conflict_hint": (
            "Aucun chevauchement détecté" if conflicts == 0
            else "%s conflit(s) à résoudre" % conflicts
        ),
        "conflict_icon": "check_circle" if conflicts == 0 else "warning",
        "conflict_icon_class": (
            "bg-surface-container text-primary" if conflicts == 0
            else "bg-error-container text-error"
        ),
        "create_form": create_form,
        "edit_form": edit_form,
        "edit_session": edit_session,
        "open_modal": open_modal,
    }


@role_required(Profil.ROLE_ETUDIANT)
def student_exams(request):
    student = _student_profile(request)
    classes = _student_classes(request)
    today = timezone.localdate()
    sessions = (
        ExamSession.objects.filter(school_class__in=classes)
        .select_related("school_class", "school_class__university", "subject")
        .order_by("date", "start_time")
    )
    upcoming = [s for s in sessions if s.date >= today]

    copies = {
        copy.session_id: copy
        for copy in ExamCopy.objects.filter(
            student=student, session__in=upcoming,
        ).prefetch_related("pages")
    }
    session_rows = []
    for session in upcoming:
        copy = copies.get(session.pk)
        pages = list(copy.pages.all()) if copy else []
        convocation_hash = None
        if session.is_convoked:
            buffer = convocation_pdf(session, student)
            convocation_hash = sha256(buffer.getvalue()).hexdigest()
        subject = getattr(session, "subject", None)
        session_rows.append({
            "session": session,
            "copy": copy,
            "pages": [
                {"page": page, "hash": _page_hash(page)}
                for page in pages
            ],
            "submitted": copy is not None and copy.is_submitted,
            "copy_hash": _combined_hash(pages),
            "convocation_hash": convocation_hash,
            "duration_label": _duration_label(session.start_time, session.end_time),
            "subject": subject,
            "subject_available": bool(subject and subject.is_available),
            "subject_status": subject.availability_status if subject else "none",
            "deposit_open": session.deposit_open,
            "deposit_status": session.deposit_status,
        })

    published_grades = (
        StudentGrade.objects.filter(
            student=student, status=StudentGrade.STATUS_PUBLISHED,
        )
        .select_related("session", "session__school_class")
        .order_by("-session__date", "-session__start_time")
    )

    return render(request, "exams/student_exams.html", {
        "semester_label": _current_semester_label(classes),
        "session_rows": session_rows,
        "published_grades": published_grades,
        "has_sessions": bool(session_rows),
    })


@role_required(Profil.ROLE_ETUDIANT)
def student_transcript(request):
    student = _student_profile(request)
    classes = _student_classes(request)
    grades = list(
        StudentGrade.objects.filter(
            student=student, status=StudentGrade.STATUS_PUBLISHED, score__isnull=False,
        )
        .select_related("session", "session__school_class")
        .order_by("session__date", "session__start_time")
    )

    semester_rows = []
    for semester, rows in _group_grades_by_semester(grades).items():
        coefficient_total = sum(g.session.coefficient for g in rows)
        average = (
            sum((g.score * g.session.coefficient for g in rows), Decimal("0"))
            / coefficient_total
            if coefficient_total else None
        )
        semester_rows.append({
            "label": semester,
            "rows": rows,
            "validated": sum(1 for g in rows if g.score >= 10),
            "average": average,
            "average_label": _format_decimal(average),
        })

    average, validated, graded_total = _weighted_summary(grades)
    rank = _compute_rank(student, classes, average) if average is not None else None
    mention = _mention_for(average) if average is not None else None
    promotion_size = _promotion_size(student, classes)

    if average is None:
        mention_hint = "Aucune note publiée pour le moment"
    elif average >= 10:
        mention_hint = "Semestre validé"
    else:
        mention_hint = "En attente de validation"

    return render(request, "exams/student_transcript.html", {
        "semester_rows": semester_rows,
        "grade_count": graded_total,
        "average": average,
        "average_label": _format_decimal(average),
        "validated": validated,
        "rank": rank,
        "promotion_size": promotion_size,
        "mention": mention,
        "mention_label": mention or "—",
        "mention_hint": mention_hint,
        "suffix_validated": "/%s" % graded_total,
        "rank_label": rank or "—",
        "rank_suffix": ("e / %s" % promotion_size) if rank else "",
    })


@role_required(Profil.ROLE_ETUDIANT)
def student_convocation_pdf(request, pk):
    student = _student_profile(request)
    session = get_object_or_404(
        ExamSession.objects.select_related("school_class", "school_class__university"),
        pk=pk, university=request.university, school_class__in=_student_classes(request),
    )
    if not session.is_convoked:
        messages.error(request, "La convocation de cette session n'a pas encore été envoyée.")
        return redirect("exams:student_exams")
    return _pdf_response(
        convocation_pdf(session, student),
        "convocation-%s.pdf" % session.pk,
    )


@role_required(Profil.ROLE_ETUDIANT)
def student_subject_download(request, pk):
    """Téléchargement du sujet, strictement limité à la durée de l'épreuve."""
    session = _student_session(request, pk)
    subject = getattr(session, "subject", None)
    if subject is None or not subject.is_published:
        messages.error(request, "Le sujet de cette épreuve n'est pas encore publié.")
        return redirect("exams:student_exams")
    status = subject.availability_status
    if status == "before":
        messages.error(
            request,
            "Le sujet sera accessible au début de l'épreuve, le %s."
            % session.subject_window_label,
        )
        return redirect("exams:student_exams")
    if status == "after":
        messages.error(
            request,
            "Le sujet n'est plus accessible : l'épreuve s'est terminée le %s."
            % session.subject_window_label,
        )
        return redirect("exams:student_exams")
    filename = os.path.basename(subject.file.name)
    return FileResponse(
        subject.file.open("rb"),
        as_attachment=True,
        filename=filename or "sujet-epreuve.pdf",
        content_type="application/pdf",
    )


@role_required(Profil.ROLE_ETUDIANT)
def student_transcript_pdf(request):
    student = _student_profile(request)
    grades = (
        StudentGrade.objects.filter(
            student=student, status=StudentGrade.STATUS_PUBLISHED, score__isnull=False,
        )
        .select_related("session")
        .order_by("session__date", "session__start_time")
    )
    average, validated, _total = _weighted_summary(grades)
    semester_rows = [
        {"label": semester, "rows": rows}
        for semester, rows in _group_grades_by_semester(grades).items()
    ]
    return _pdf_response(
        transcript_pdf(request.university, student, semester_rows, average,
                       _mention_for(average) if average is not None else None),
        "releve-notes.pdf",
    )


@role_required(Profil.ROLE_ETUDIANT)
def student_attestation_pdf(request):
    student = _student_profile(request)
    grades = StudentGrade.objects.filter(
        student=student, status=StudentGrade.STATUS_PUBLISHED, score__isnull=False,
    )
    average, validated, _total = _weighted_summary(grades)
    if average is None or average < 10:
        messages.error(
            request,
            "L'attestation de réussite est disponible uniquement lorsque la "
            "moyenne générale atteint 10/20.",
        )
        return redirect("exams:student_transcript")
    return _pdf_response(
        attestation_pdf(request.university, student, average,
                        _mention_for(average)),
        "attestation-reussite.pdf",
    )


@role_required(Profil.ROLE_ETUDIANT)
@require_POST
def student_copy_upload(request, pk):
    session = _student_session(request, pk)
    locked = _deposit_locked_message(session)
    if locked:
        messages.error(request, locked)
        return redirect("exams:student_exams")
    student = _student_profile(request)
    copy = ExamCopy.objects.filter(session=session, student=student).first()
    if copy is not None and copy.is_submitted:
        messages.error(
            request,
            "Cette copie a déjà été soumise : elle est verrouillée et ne peut "
            "plus être modifiée.",
        )
        return redirect("exams:student_exams")
    upload = request.FILES.get("file")
    if upload is None:
        messages.error(request, "Aucun fichier reçu.")
        return redirect("exams:student_exams")

    lower_name = upload.name.lower()
    if lower_name.endswith(COPY_EXTENSIONS):
        copy, _created = ExamCopy.objects.get_or_create(
            session=session, student=student,
            defaults={"university": request.university},
        )
        if copy.file:
            copy.file.delete(save=False)
        copy.file = upload
        copy.original_name = upload.name
        copy.file_size = upload.size
        copy.save()
        messages.success(
            request,
            "Copie « %s » déposée. Soumettez-la pour la verrouiller et la "
            "transmettre au correcteur." % upload.name,
        )
        return redirect("exams:student_exams")

    # Rétro-compatibilité : les anciennes copies scannées image restent acceptées.
    image = _validated_image(upload)
    if image is None:
        messages.error(
            request,
            "Format non reconnu : déposez un fichier PDF ou une archive ZIP.",
        )
        return redirect("exams:student_exams")
    copy, _created = ExamCopy.objects.get_or_create(
        session=session, student=student, defaults={"university": request.university},
    )
    ExamCopyPage.objects.create(copy=copy, file=upload)
    messages.success(request, "Page ajoutée à votre copie (%s page(s))." % copy.page_count)
    return redirect("exams:student_exams")


@role_required(Profil.ROLE_ETUDIANT)
@require_POST
def student_copy_submit(request, pk):
    session = _student_session(request, pk)
    locked = _deposit_locked_message(session)
    if locked:
        messages.error(request, locked)
        return redirect("exams:student_exams")
    copy = ExamCopy.objects.filter(
        session=session, student=_student_profile(request),
    ).prefetch_related("pages").first()
    if copy is None or not copy.has_content:
        messages.error(
            request,
            "Déposez d'abord votre copie (PDF ou archive ZIP) avant de soumettre.",
        )
    elif copy.is_submitted:
        messages.info(request, "Cette copie a déjà été soumise.")
    else:
        copy.submitted_at = timezone.now()
        copy.save(update_fields=["submitted_at", "updated_at"])
        messages.success(
            request,
            "Copie soumise avec horodatage officiel (%s)." % timezone.localtime(copy.submitted_at).strftime("%d/%m/%Y %H:%M"),
        )
    return redirect("exams:student_exams")


@role_required(Profil.ROLE_ETUDIANT)
@require_POST
def student_copy_page_rotate(request, pk):
    page = _student_copy_page(request, pk)
    locked = _copy_page_locked(page)
    if locked:
        messages.error(request, locked)
        return redirect("exams:student_exams")
    try:
        with Image.open(page.file.path) as image:
            rotated = image.rotate(-90, expand=True)
            _save_image(rotated, page.file.path)
    except Exception:
        messages.error(request, "Impossible de pivoter cette page.")
    else:
        messages.success(request, "Page pivotée de 90°.")
    return redirect("exams:student_exams")


@role_required(Profil.ROLE_ETUDIANT)
@require_POST
def student_copy_page_autocrop(request, pk):
    page = _student_copy_page(request, pk)
    locked = _copy_page_locked(page)
    if locked:
        messages.error(request, locked)
        return redirect("exams:student_exams")
    try:
        with Image.open(page.file.path) as image:
            rgb = image.convert("RGB")
            diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white"))
            bbox = diff.getbbox()
            if bbox and bbox != (0, 0, rgb.width, rgb.height):
                cropped = image.crop(bbox)
                _save_image(cropped, page.file.path)
            else:
                messages.info(request, "Aucune marge détectée sur cette page.")
                return redirect("exams:student_exams")
    except Exception:
        messages.error(request, "Impossible de recadrer cette page.")
    else:
        messages.success(request, "Marges de la page recadrées automatiquement.")
    return redirect("exams:student_exams")


@role_required(Profil.ROLE_ETUDIANT)
@require_POST
def student_copy_page_replace(request, pk):
    page = _student_copy_page(request, pk)
    locked = _copy_page_locked(page)
    if locked:
        messages.error(request, locked)
        return redirect("exams:student_exams")
    upload = request.FILES.get("file")
    image = _validated_image(upload)
    if upload is None or image is None:
        messages.error(request, "Format non reconnu : envoyez une image JPEG ou PNG.")
        return redirect("exams:student_exams")
    page.file.delete(save=False)
    page.file = upload
    page.save(update_fields=["file"])
    messages.success(request, "Page remplacée.")
    return redirect("exams:student_exams")


@role_required(Profil.ROLE_PROF)
def prof_corrections(request):
    classes = _prof_classes(request)
    sessions = list(
        ExamSession.objects.filter(school_class__in=classes)
        .select_related("school_class", "subject")
        .order_by("-date", "-start_time")
    )
    requested_session = request.POST.get("session") or request.GET.get("session")
    if not requested_session:
        return render(
            request, "exams/prof_corrections.html",
            _class_cards_context(request, classes, sessions),
        )

    session = _pick_by_pk(sessions, requested_session)
    if session is None:
        messages.error(request, "Cette session d'examen ne vous est pas accessible.")
        return redirect("exams:prof_corrections")

    students = list(_session_students(session))
    selected = (
        _pick_by_pk(students, request.POST.get("student") or request.GET.get("student"))
        or (students[0] if students else None)
    )
    grade = (
        StudentGrade.objects.filter(session=session, student=selected).first()
        if selected is not None else None
    )

    action = request.POST.get("action")
    if (
        request.method == "POST"
        and selected is not None
        and action in ("save", "validate", "publish", "absent")
    ):
        if action == "absent":
            submitted_copy = ExamCopy.objects.filter(
                session=session, student=selected, submitted_at__isnull=False,
            ).exists()
            if submitted_copy:
                messages.error(
                    request,
                    "%s a soumis une copie : impossible de le marquer absent."
                    % _display_name(selected),
                )
                return redirect(
                    "%s?session=%s&student=%s"
                    % (reverse("exams:prof_corrections"), session.pk, selected.pk)
                )
            if grade is None:
                grade = StudentGrade(
                    session=session, student=selected, university=request.university,
                )
            grade.score = Decimal("0")
            grade.criteria = []
            grade.comment = ABSENT_COMMENT
            grade.status = StudentGrade.STATUS_PUBLISHED
            grade.graded_by = request.user
            grade.save()
            messages.success(
                request,
                "%s marqué absent : note 0/20 publiée." % _display_name(selected),
            )
            next_student = _next_ungraded_student(session, students, selected)
            target = next_student or selected
            return redirect(
                "%s?session=%s&student=%s"
                % (reverse("exams:prof_corrections"), session.pk, target.pk)
            )
        criteria = _parse_criteria(request.POST)
        comment = request.POST.get("comment", "").strip()
        if grade is None:
            grade = StudentGrade(
                session=session, student=selected, university=request.university,
            )
        grade.criteria = criteria
        grade.comment = comment
        grade.graded_by = request.user
        if action in ("validate", "publish"):
            total = grade.criteria_total
            if total <= 0:
                messages.error(request, "Saisissez les points avant de valider la note.")
                return render(request, "exams/prof_corrections.html", _corrections_context(
                    request, sessions, session, students, selected, grade, comment,
                ))
            grade.score = min(total, grade.max_total)
            grade.status = (
                StudentGrade.STATUS_PUBLISHED
                if action == "publish"
                else StudentGrade.STATUS_VALIDATED
            )
            grade.save()
            if action == "publish":
                messages.success(
                    request,
                    "Note de %s validée et publiée (%s/20)." % (
                        _display_name(selected), _format_decimal(grade.score),
                    ),
                )
            else:
                messages.success(
                    request,
                    "Note de %s validée (%s/20). Publiez-la pour la rendre "
                    "visible à l'étudiant." % (
                        _display_name(selected), _format_decimal(grade.score),
                    ),
                )
            next_student = _next_ungraded_student(session, students, selected)
            target = next_student or selected
            return redirect(
                "%s?session=%s&student=%s"
                % (reverse("exams:prof_corrections"), session.pk, target.pk)
            )
        grade.score = grade.score if grade.status != StudentGrade.STATUS_DRAFT else None
        if grade.status not in (StudentGrade.STATUS_VALIDATED, StudentGrade.STATUS_PUBLISHED):
            grade.status = StudentGrade.STATUS_DRAFT
        grade.save()
        messages.success(request, "Brouillon de correction enregistré.")
        return redirect(
            "%s?session=%s&student=%s"
            % (reverse("exams:prof_corrections"), session.pk, selected.pk)
        )

    return render(request, "exams/prof_corrections.html", _corrections_context(
        request, sessions, session, students, selected, grade,
        grade.comment if grade else "",
    ))


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_corrections_publish(request):
    session = get_object_or_404(
        ExamSession, pk=request.POST.get("session"),
        university=request.university, school_class__in=_prof_classes(request),
    )
    updated = session.student_grades.filter(
        status=StudentGrade.STATUS_VALIDATED,
    ).update(status=StudentGrade.STATUS_PUBLISHED)
    if updated:
        messages.success(
            request, "%s note(s) publiée(s) pour « %s »." % (updated, session.title),
        )
    else:
        messages.info(request, "Aucune note validée à publier pour « %s »." % session.title)
    return redirect("%s?session=%s" % (reverse("exams:prof_corrections"), session.pk))


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_correction_publish_one(request):
    """Publie la note déjà validée d'un étudiant (action individuelle)."""
    session = get_object_or_404(
        ExamSession, pk=request.POST.get("session"),
        university=request.university, school_class__in=_prof_classes(request),
    )
    student = get_object_or_404(
        StudentProfile, pk=request.POST.get("student"),
        university=request.university,
        groups__school_class=session.school_class,
    )
    grade = StudentGrade.objects.filter(session=session, student=student).first()
    if grade is None or grade.score is None or grade.status == StudentGrade.STATUS_DRAFT:
        messages.error(
            request, "Aucune note validée à publier pour %s." % _display_name(student),
        )
    elif grade.status == StudentGrade.STATUS_PUBLISHED:
        messages.info(
            request, "La note de %s est déjà publiée." % _display_name(student),
        )
    else:
        grade.status = StudentGrade.STATUS_PUBLISHED
        grade.save(update_fields=["status", "updated_at"])
        messages.success(
            request,
            "Note de %s publiée (%s/20)." % (
                _display_name(student), _format_decimal(grade.score),
            ),
        )
    target = request.POST.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(target)
    return redirect("%s?session=%s&student=%s" % (
        reverse("exams:prof_corrections"), session.pk, student.pk,
    ))


@role_required(Profil.ROLE_PROF)
@require_GET
def prof_exam_sessions(request):
    classes = _prof_classes(request)
    sessions = list(
        ExamSession.objects.filter(school_class__in=classes)
        .select_related("school_class", "course_subject", "subject")
        .order_by("date", "start_time")
    )
    today = timezone.localdate()
    upcoming = [s for s in sessions if s.date >= today]
    convoked = [s for s in sessions if s.is_convoked]
    conflicts = _count_room_conflicts(sessions)

    return render(request, "exams/prof_exam_sessions.html", {
        "semester": _current_semester_label(classes),
        "sessions": sessions,
        "upcoming": upcoming,
        "session_count": len(upcoming),
        "convocation_count": sum(1 for s in convoked if s.date >= today),
        "student_count": sum(
            _session_students(s).count()
            for s in convoked if s.date >= today
        ),
        "room_count": len({s.room for s in upcoming if s.room}),
        "published_subject_count": sum(
            1 for s in sessions
            if getattr(s, "subject", None) is not None and s.subject.is_published
        ),
        "conflict_count": conflicts,
        "conflict_hint": (
            "Aucun chevauchement détecté" if conflicts == 0
            else "%s conflit(s) à résoudre" % conflicts
        ),
        "conflict_icon": "check_circle" if conflicts == 0 else "warning",
        "conflict_icon_class": (
            "bg-surface-container text-primary" if conflicts == 0
            else "bg-error-container text-error"
        ),
    })


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_subject_upload(request, pk):
    session = get_object_or_404(
        ExamSession, pk=pk, school_class__in=_prof_classes(request),
    )
    upload = request.FILES.get("file")
    if upload is None:
        messages.error(request, "Aucun fichier reçu pour « %s »." % session.title)
        return redirect("exams:prof_exam_sessions")
    if not upload.name.lower().endswith(".pdf"):
        messages.error(request, "Envoyez le sujet au format PDF.")
        return redirect("exams:prof_exam_sessions")
    subject, created = ExamSubject.objects.get_or_create(
        session=session,
        defaults={"file": upload, "created_by": request.user},
    )
    if not created:
        if subject.file:
            subject.file.delete(save=False)
        subject.file = upload
        subject.created_by = request.user
        subject.published_at = None
        subject.save()
        messages.success(
            request,
            "Sujet de « %s » remplacé — publication réinitialisée, pensez à le republier."
            % session.title,
        )
    else:
        messages.success(
            request,
            "Sujet déposé pour « %s ». Pensez à le publier pour les étudiants."
            % session.title,
        )
    return redirect("exams:prof_exam_sessions")


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_subject_publish(request, pk):
    session = get_object_or_404(
        ExamSession, pk=pk, school_class__in=_prof_classes(request),
    )
    subject = getattr(session, "subject", None)
    if subject is None:
        messages.error(
            request, "Déposez d'abord le sujet d'épreuve avant de le publier.",
        )
    elif subject.is_published:
        subject.published_at = None
        subject.save(update_fields=["published_at", "updated_at"])
        messages.success(
            request, "Publication du sujet « %s » annulée." % session.title,
        )
    else:
        subject.published_at = timezone.now()
        subject.save(update_fields=["published_at", "updated_at"])
        messages.success(
            request, "Sujet « %s » publié auprès des étudiants." % session.title,
        )
    return redirect("exams:prof_exam_sessions")


@role_required(Profil.ROLE_PROF)
def prof_grade_sheets(request):
    classes = _prof_classes(request)
    sessions = list(
        ExamSession.objects.filter(school_class__in=classes)
        .select_related("school_class")
        .order_by("date", "start_time")
    )
    records = {
        school_class.pk: GradeRecord.objects.get_or_create(
            school_class=school_class, semester=semester_for(school_class),
            defaults={"university": request.university},
        )[0]
        for school_class in classes
    }
    rows = []
    for session in sessions:
        record = records.get(session.school_class_id)
        scores = [
            grade.score for grade in session.student_grades.filter(
                status__in=(StudentGrade.STATUS_VALIDATED, StudentGrade.STATUS_PUBLISHED),
                score__isnull=False,
            )
        ]
        jury = _jury_names(record)
        rows.append({
            "session": session,
            "record": record,
            "average": (sum(scores) / len(scores)) if scores else None,
            "grade_count": len(scores),
            "jury": jury,
        })

    pending_records = [record for record in records.values() if not record.pv_signed]
    records_average = [
        record.average for record in records.values()
        if record.students_count and record.average
    ]
    first_class = classes.order_by("name").first()
    jury_context = None
    if first_class is not None:
        record = records[first_class.pk]
        jury_context = {
            "school_class": first_class,
            "record": record,
            "members": _jury_context_members(record, first_class),
        }

    deliberations = []
    for school_class in classes:
        record = records[school_class.pk]
        if record.pv_signed:
            continue
        next_session = next(
            (s for s in sessions if s.school_class_id == school_class.pk and s.date >= timezone.localdate()),
            None,
        )
        deliberations.append({
            "label": "Jury %s · %s" % (school_class.name, record.semester),
            "detail": (
                "%s · %s · %s" % (
                    next_session.date_label, next_session.start_time.strftime("%H:%M"), next_session.room,
                ) if next_session else "Date à fixer"
            ),
            "confirmed": bool(next_session and next_session.is_convoked),
        })

    return render(request, "exams/prof_grade_sheets.html", {
        "semester": _current_semester_label(classes),
        "rows": rows,
        "pending_records": pending_records,
        "pending_count": len(pending_records),
        "student_total": sum(record.students_count for record in records.values()),
        "jury_total": JuryMember.objects.filter(grade_record__in=records.values()).count(),
        "records_average": (
            (sum(records_average) / len(records_average)) if records_average else None
        ),
        "jury_context": jury_context,
        "deliberations": deliberations,
    })


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_grade_sheets_sign(request):
    records = GradeRecord.objects.filter(
        university=request.university,
        school_class__in=_prof_classes(request),
        pv_signed=False,
    )
    signed = 0
    for record in records:
        if _sign_record(record, request.user):
            signed += 1
    if signed:
        messages.success(request, "%s relevé(s) signé(s) électroniquement." % signed)
    else:
        messages.info(request, "Aucun relevé en attente de signature.")
    return redirect("exams:prof_grade_sheets")


@role_required(Profil.ROLE_PROF)
@require_POST
def prof_jury_invite(request, pk):
    record = get_object_or_404(
        GradeRecord, pk=pk, university=request.university,
        school_class__in=_prof_classes(request),
    )
    existing = set(record.jury_members.values_list("professor_id", flat=True))
    candidate = (
        ProfessorProfile.objects.filter(university=request.university)
        .exclude(pk__in=existing)
        .order_by("membership__user__last_name", "membership__user__first_name")
        .first()
    )
    if candidate is None:
        messages.info(
            request, "Tous les enseignants de l'établissement font déjà partie de ce jury.",
        )
    else:
        JuryMember.objects.create(
            grade_record=record, professor=candidate,
            status=JuryMember.STATUS_INVITED,
        )
        send_mail(
            "Invitation au jury — %s" % record.school_class.name,
            "Bonjour %s,\n\nVous êtes invité(e) à rejoindre le jury du relevé "
            "%s (%s).\n\nCordialement,\n%s"
            % (
                candidate.membership.user.get_full_name() or candidate.membership.user.email,
                record.school_class.name, record.semester,
                request.user.get_full_name() or request.user.email,
            ),
            None,
            [candidate.membership.user.email],
            fail_silently=True,
        )
        messages.success(
            request,
            "Invitation envoyée à %s." % (
                candidate.membership.user.get_full_name()
                or candidate.membership.user.email
            ),
        )
    return redirect("exams:prof_grade_sheets")


@role_required(Profil.ROLE_ADMIN)
def admin_exam_sessions(request):
    edit_session = None
    edit_form = None
    open_modal = None

    edit_id = request.GET.get("edit")
    if edit_id:
        edit_session = (
            ExamSession.objects.filter(pk=edit_id, university=request.university)
            .select_related("school_class")
            .first()
        )
        if edit_session is not None:
            edit_form = ExamSessionForm(
                instance=edit_session,
                university=request.university,
                prefix="edit",
            )
            open_modal = "edit"

    return render(request, "exams/admin_exam_sessions.html",
                  _sessions_context(request, edit_form=edit_form,
                                    edit_session=edit_session, open_modal=open_modal))


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_exam_session_create(request):
    form = ExamSessionForm(
        request.POST, university=request.university, prefix="create", multi=True,
    )
    if form.is_valid():
        sessions = form.save_sessions(
            university=request.university, user=request.user,
        )
        for session in sessions:
            _notify_planning(session, request)
        if len(sessions) == 1:
            session = sessions[0]
            messages.success(
                request,
                "Épreuve « %s » planifiée pour %s — enseignants et étudiants notifiés."
                % (session.title, session.school_class.name),
            )
        else:
            messages.success(
                request,
                "Épreuve « %s » planifiée pour %s classes — enseignants et "
                "étudiants notifiés." % (sessions[0].title, len(sessions)),
            )
        return redirect("exams:admin_exam_sessions")
    return render(request, "exams/admin_exam_sessions.html",
                  _sessions_context(request, create_form=form, open_modal="create"))


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_exam_session_update(request, pk):
    session = get_object_or_404(ExamSession, pk=pk, university=request.university)
    form = ExamSessionForm(
        request.POST, instance=session, university=request.university, prefix="edit",
    )
    if form.is_valid():
        form.save()
        messages.success(request, "Session « %s » mise à jour." % session.title)
        return redirect("exams:admin_exam_sessions")
    return render(request, "exams/admin_exam_sessions.html",
                  _sessions_context(request, edit_form=form,
                                    edit_session=session, open_modal="edit"))


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_exam_session_toggle_convocation(request, pk):
    session = get_object_or_404(ExamSession, pk=pk, university=request.university)
    if session.is_convoked:
        session.status = ExamSession.STATUS_PLANNED
        session.convoked_at = None
        copy_count = session.copies.count()
        message = "Convocation annulée pour « %s »." % session.title
        if copy_count:
            message += " %s copie(s) déposée(s) conservée(s)." % copy_count
    else:
        session.status = ExamSession.STATUS_CONVOKED
        session.convoked_at = timezone.now()
        message = "Convocations envoyées pour « %s » — étudiants et enseignants notifiés." % session.title
        for student in _session_students(session).select_related("membership__user"):
            send_mail(
                "Convocation d'examen — %s" % session.title,
                "Bonjour %s,\n\n"
                "Vous êtes convoqué(e) à l'épreuve suivante :\n\n"
                "Épreuve : %s (%s)\n"
                "Date : %s, de %s à %s\n"
                "Salle : %s\n\n"
                "Votre convocation officielle est disponible dans votre espace "
                "« Mes Examens ».\n\n"
                "Cordialement,\n%s"
                % (
                    student.membership.user.get_full_name()
                    or student.membership.user.email,
                    session.title, session.get_exam_type_display(),
                    session.date_label,
                    session.start_time.strftime("%H:%M"),
                    session.end_time.strftime("%H:%M"), session.room,
                    request.user.get_full_name() or request.user.email,
                ),
                None,
                [student.membership.user.email],
                fail_silently=True,
            )
        for professor in session.school_class.professors.select_related("membership__user"):
            send_mail(
                "Convocation envoyée — %s" % session.title,
                "Bonjour %s,\n\n"
                "La convocation de l'épreuve « %s » (%s) vient d'être envoyée "
                "aux étudiants de %s.\n"
                "Pensez à publier le sujet d'épreuve s'il n'est pas déjà en ligne.\n\n"
                "Cordialement,\n%s"
                % (
                    professor.membership.user.get_full_name()
                    or professor.membership.user.email,
                    session.title, session.get_exam_type_display(),
                    session.school_class.name,
                    request.user.get_full_name() or request.user.email,
                ),
                None,
                [professor.membership.user.email],
                fail_silently=True,
            )
    session.save(update_fields=["status", "convoked_at", "updated_at"])
    messages.success(request, message)
    return redirect("exams:admin_exam_sessions")


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_exam_session_delete(request, pk):
    session = get_object_or_404(ExamSession, pk=pk, university=request.university)
    title = session.title
    session.delete()
    messages.success(request, "Session « %s » supprimée." % title)
    return redirect("exams:admin_exam_sessions")


@role_required(Profil.ROLE_ADMIN)
def admin_exam_sessions_export(request):
    rows = (
        (
            session.date.isoformat(),
            session.start_time.strftime("%H:%M"),
            session.end_time.strftime("%H:%M"),
            session.school_class.name,
            (
                "%s · %s" % (session.course_subject.code, session.course_subject.name)
                if session.course_subject else ""
            ),
            session.title,
            session.get_exam_type_display(),
            session.room,
            session.get_status_display(),
        )
        for session in _tenant_sessions(request)
    )
    return _csv_response(
        "sessions-examen.csv",
        ("Date", "Début", "Fin", "Classe", "Matière", "Épreuve", "Type", "Salle", "Statut"),
        rows,
    )


@role_required(Profil.ROLE_ADMIN)
def admin_statistics(request):
    records = _tenant_records(request)
    evaluated = [record for record in records if record.students_count]
    students_total = sum(record.students_count for record in evaluated)
    admitted_total = sum(record.admitted_count for record in evaluated)
    weighted_average = sum(
        (record.average * record.students_count for record in evaluated),
        Decimal("0"),
    )
    average_label = (
        ("%.1f" % (weighted_average / students_total)).replace(".", ",")
        if students_total else "—"
    )
    return render(request, "exams/admin_statistics.html", {
        "semester": EXAM_SEMESTER,
        "records": records,
        "class_count": len(evaluated),
        "students_total": students_total,
        "admitted_total": admitted_total,
        "success_rate": round(admitted_total * 100 / students_total) if students_total else 0,
        "average_label": average_label,
    })


@role_required(Profil.ROLE_ADMIN)
def admin_statistics_export(request):
    rows = (
        (
            record.school_class.name,
            record.school_class.level,
            record.students_count,
            record.admitted_count,
            record.average_label,
            record.rate_label,
        )
        for record in _tenant_records(request)
    )
    return _csv_response(
        "statistiques-reussite.csv",
        ("Classe", "Niveau", "Inscrits", "Admis", "Moyenne", "Taux de réussite"),
        rows,
    )


@role_required(Profil.ROLE_ADMIN)
def admin_official_records(request):
    records = _tenant_records(request)
    pending_records = [record for record in records if not record.pv_signed]
    return render(request, "exams/admin_official_records.html", {
        "semester": EXAM_SEMESTER,
        "records": records,
        "pending_records": pending_records,
        "record_count": len(records),
        "published_count": sum(1 for record in records if record.transcript_published),
        "pending_count": len(pending_records),
    })


@role_required(Profil.ROLE_ADMIN)
def admin_official_records_export(request):
    rows = (
        (
            record.school_class.name,
            record.semester,
            record.students_count,
            record.average_label,
            "Signé" if record.pv_signed else "En attente",
            "Publié" if record.transcript_published else "En attente",
        )
        for record in _tenant_records(request)
    )
    return _csv_response(
        "releves-officiels.csv",
        ("Classe", "Semestre", "Étudiants", "Moyenne", "PV du jury", "Relevé"),
        rows,
    )


@role_required(Profil.ROLE_ADMIN)
def admin_grade_record_detail(request, pk):
    record = get_object_or_404(
        GradeRecord.objects.select_related("school_class"), pk=pk, university=request.university,
    )
    if request.method == "POST" and request.POST.get("action") == "recalculate":
        rows, _sessions = _deliberation_rows(record)
        _recalculate_grade_record(record, rows)
        messages.success(
            request,
            "PV de %s recalculé depuis les notes publiées." % record.school_class.name,
        )
        return redirect("exams:admin_grade_record_detail", pk=record.pk)

    if request.method == "POST":
        form = GradeRecordForm(request.POST, instance=record)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Résultats du relevé de %s enregistrés." % record.school_class.name,
            )
            return redirect("exams:admin_grade_record_detail", pk=record.pk)
    else:
        form = GradeRecordForm(instance=record)

    deliberation_rows, sessions = _deliberation_rows(record)
    return render(request, "exams/admin_grade_record_detail.html", {
        "record": record,
        "form": form,
        "semester": record.semester,
        "sessions": sessions,
        "deliberation_rows": deliberation_rows,
        "deliberation_count": len(deliberation_rows),
        "deliberation_admitted": sum(
            1 for row in deliberation_rows if row["decision"] == "Admis"
        ),
        "deliberation_pending": sum(
            1 for row in deliberation_rows if row["decision"] == "En attente"
        ),
    })


def _sign_record(record, user):
    if record.pv_signed:
        return False
    record.pv_signed = True
    record.pv_signed_at = timezone.now()
    record.pv_signed_by = user
    record.save(update_fields=["pv_signed", "pv_signed_at", "pv_signed_by", "updated_at"])
    return True


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_grade_record_sign(request, pk):
    record = get_object_or_404(GradeRecord, pk=pk, university=request.university)
    if _sign_record(record, request.user):
        messages.success(request, "PV de %s signé." % record.school_class.name)
    else:
        messages.info(request, "Le PV de %s est déjà signé." % record.school_class.name)
    return _next_or(request, "exams:admin_official_records")


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_grade_record_sign_selected(request):
    record_id = request.POST.get("record")
    record = (
        GradeRecord.objects.filter(pk=record_id, university=request.university).first()
        if record_id else None
    )
    if record is None:
        messages.error(request, "Sélectionnez un PV à signer.")
    elif _sign_record(record, request.user):
        messages.success(request, "PV de %s signé." % record.school_class.name)
    else:
        messages.info(request, "Le PV de %s est déjà signé." % record.school_class.name)
    return redirect("exams:admin_official_records")


@role_required(Profil.ROLE_ADMIN)
@require_POST
def admin_grade_record_publish(request, pk):
    record = get_object_or_404(GradeRecord, pk=pk, university=request.university)
    if not record.pv_signed:
        messages.error(request, "Signez le PV de %s avant de publier le relevé." % record.school_class.name)
    elif record.transcript_published:
        messages.info(request, "Le relevé de %s est déjà publié." % record.school_class.name)
    else:
        record.transcript_published = True
        record.published_at = timezone.now()
        record.save(update_fields=["transcript_published", "published_at", "updated_at"])
        messages.success(request, "Relevé de %s publié." % record.school_class.name)
    return _next_or(request, "exams:admin_official_records")


# ---------------------------------------------------------------------------
# Helpers des parcours prof / étudiant
# ---------------------------------------------------------------------------

_PROFILE_RELATED_NAMES = {
    ProfessorProfile: "professor_profile",
    StudentProfile: "student_profile",
}


def _membership_profile(request, profile_class):
    membership = getattr(request, "membership", None)
    if membership is None:
        return None
    try:
        return getattr(membership, _PROFILE_RELATED_NAMES[profile_class])
    except profile_class.DoesNotExist:
        return None


def _prof_profile(request):
    return _membership_profile(request, ProfessorProfile)


def _student_profile(request):
    return _membership_profile(request, StudentProfile)


def _prof_classes(request):
    profile = _prof_profile(request)
    if profile is None:
        return SchoolClass.objects.none()
    return SchoolClass.objects.filter(
        university=request.university, professors=profile,
    ).distinct()


def _student_classes(request):
    profile = _student_profile(request)
    if profile is None:
        return SchoolClass.objects.none()
    return SchoolClass.objects.filter(
        university=request.university, groups__students=profile,
    ).distinct()


def _session_students(session):
    return (
        StudentProfile.objects.filter(groups__school_class=session.school_class)
        .distinct()
        .order_by("membership__user__last_name", "membership__user__first_name")
    )


def _class_students(school_class):
    return (
        StudentProfile.objects.filter(groups__school_class=school_class)
        .distinct()
        .select_related("membership__user")
        .order_by("membership__user__last_name", "membership__user__first_name")
    )


def _deliberation_rows(record):
    students = list(_class_students(record.school_class))
    sessions = list(
        record.school_class.exam_sessions.select_related("subject")
        .order_by("date", "start_time")
    )
    grades = (
        StudentGrade.objects.filter(session__in=sessions, student__in=students)
        .select_related("session")
    )
    by_key = {
        (grade.student_id, grade.session_id): grade for grade in grades
    }
    rows = []
    for student in students:
        subjects = []
        published_grades = []
        for session in sessions:
            grade = by_key.get((student.pk, session.pk))
            subjects.append({
                "session": session,
                "grade": grade,
                "is_absent": _is_absent_grade(grade),
            })
            if (
                grade
                and grade.status == StudentGrade.STATUS_PUBLISHED
                and grade.score is not None
            ):
                published_grades.append(grade)
        average, validated, graded_total = _weighted_summary(published_grades)
        if average is None:
            decision = "En attente"
        elif average >= 10:
            decision = "Admis"
        else:
            decision = "Ajourné"
        rows.append({
            "student": student,
            "subjects": subjects,
            "has_grades": any(item["grade"] is not None for item in subjects),
            "average": average,
            "average_label": _format_decimal(average),
            "validated": validated,
            "graded_total": graded_total,
            "decision": decision,
            "is_absent": any(item["is_absent"] for item in subjects),
        })
    return rows, sessions


def _recalculate_grade_record(record, rows):
    averages = [row["average"] for row in rows if row["average"] is not None]
    record.students_count = len(rows)
    record.admitted_count = sum(
        1 for row in rows
        if row["average"] is not None and row["average"] >= 10
    )
    record.average = (
        sum(averages, Decimal("0")) / len(averages)
        if averages else Decimal("0")
    )
    record.save(update_fields=[
        "students_count", "admitted_count", "average", "updated_at",
    ])


def _class_cards_context(request, classes, sessions):
    """Vue « cartes de classe » du correcteur.

    Chaque classe regroupe ses épreuves, puis pour chaque épreuve la liste
    des étudiants avec l'état de leur copie et de leur note.
    """
    sessions_by_class = {}
    for session in sessions:
        sessions_by_class.setdefault(session.school_class_id, []).append(session)

    cards = []
    for school_class in classes:
        class_sessions = sessions_by_class.get(school_class.pk, [])
        students = list(_class_students(school_class))
        session_rows = []
        for session in class_sessions:
            copies = {
                copy.student_id: copy
                for copy in ExamCopy.objects.filter(session=session).prefetch_related("pages")
            }
            grades = {
                grade.student_id: grade
                for grade in StudentGrade.objects.filter(session=session)
            }
            rows = []
            for student in students:
                copy = copies.get(student.pk)
                grade = grades.get(student.pk)
                copy_name = ""
                if copy and copy.has_file:
                    copy_name = copy.original_name or os.path.basename(copy.file.name)
                grade_is_absent = _is_absent_grade(grade)
                rows.append({
                    "student": student,
                    "copy": copy,
                    "grade": grade,
                    "has_copy": bool(copy and copy.has_content),
                    "copy_submitted": bool(copy and copy.is_submitted),
                    "copy_name": copy_name,
                    "grade_status": grade.get_status_display() if grade else "Non corrigée",
                    "grade_is_absent": grade_is_absent,
                    "can_mark_absent": not bool(copy and copy.is_submitted) and not grade_is_absent,
                    "can_publish": bool(
                        grade and grade.score is not None
                        and grade.status == StudentGrade.STATUS_VALIDATED
                    ),
                    "correction_url": "%s?session=%s&student=%s" % (
                        reverse("exams:prof_corrections"), session.pk, student.pk,
                    ),
                })
            session_rows.append({
                "session": session,
                "students": rows,
                "student_count": len(rows),
                "copy_count": sum(1 for row in rows if row["has_copy"]),
                "submitted_count": sum(1 for row in rows if row["copy_submitted"]),
                "graded_count": sum(
                    1 for row in rows if row["grade"] and row["grade"].score is not None
                ),
                "published_count": sum(
                    1 for row in rows if row["grade"] and row["grade"].is_published
                ),
            })
        cards.append({
            "school_class": school_class,
            "sessions": session_rows,
            "student_count": len(students),
            "session_count": len(session_rows),
            "copy_count": sum(row["copy_count"] for row in session_rows),
            "graded_count": sum(row["graded_count"] for row in session_rows),
            "published_count": sum(row["published_count"] for row in session_rows),
        })

    return {
        "sessions": sessions,
        "session": None,
        "class_cards": cards,
        "class_count": len(cards),
        "session_count": len(sessions),
        "copy_count": sum(card["copy_count"] for card in cards),
        "graded_count": sum(card["graded_count"] for card in cards),
        "published_count": sum(card["published_count"] for card in cards),
    }


def _student_session(request, pk):
    return get_object_or_404(
        ExamSession, pk=pk, university=request.university,
        school_class__in=_student_classes(request),
    )


def _student_copy_page(request, pk):
    return get_object_or_404(
        ExamCopyPage.objects.select_related("copy", "copy__session"),
        pk=pk, copy__student=_student_profile(request),
        copy__university=request.university,
    )


def _deposit_locked_message(session):
    """Message d'erreur si le dépôt est fermé, sinon None."""
    status = session.access_status
    if status == "before":
        return "Le dépôt de copie s'ouvre au début de l'épreuve, le %s à %s." % (
            session.date_label, session.start_time.strftime("%H:%M"),
        )
    if status == "after":
        return "Le dépôt de copie est fermé : l'épreuve s'est terminée le %s à %s." % (
            session.date_label, session.end_time.strftime("%H:%M"),
        )
    return None


def _copy_page_locked(page):
    if page.copy.is_submitted:
        return "Cette copie a déjà été soumise : elle est verrouillée."
    return _deposit_locked_message(page.copy.session) or None


def _pick_by_pk(items, raw_pk):
    for item in items:
        if str(item.pk) == str(raw_pk):
            return item
    return None


def _display_name(profile):
    name = profile.membership.user.get_full_name().strip()
    return name or profile.membership.user.email


def _format_decimal(value):
    if value is None:
        return "—"
    return ("%.2f" % value).rstrip("0").rstrip(".").replace(".", ",")


def _weighted_summary(grades):
    if not grades:
        return None, 0, 0
    coefficient_total = sum((g.session.coefficient for g in grades), Decimal("0"))
    average = (
        sum((g.score * g.session.coefficient for g in grades), Decimal("0"))
        / coefficient_total
    )
    validated = sum(1 for g in grades if g.score >= 10)
    return average, validated, len(grades)


def _group_grades_by_semester(grades):
    grouped = {}
    for grade in grades:
        label = grade.session.semester or "Semestre 1"
        grouped.setdefault(label, []).append(grade)
    return grouped


def _mention_for(average):
    if average >= 16:
        return "Très Bien"
    if average >= 14:
        return "Bien"
    if average >= 12:
        return "Assez Bien"
    if average >= 10:
        return "Passable"
    return "Ajourné"


def _promotion_size(student, classes):
    return (
        StudentProfile.objects.filter(groups__school_class__in=classes)
        .distinct().count()
    )


def _compute_rank(student, classes, own_average):
    classmates = (
        StudentProfile.objects.filter(groups__school_class__in=classes)
        .exclude(pk=student.pk).distinct()
    )
    better = 0
    for classmate in classmates:
        classmate_grades = StudentGrade.objects.filter(
            student=classmate, status=StudentGrade.STATUS_PUBLISHED,
            score__isnull=False,
        ).select_related("session")
        average, _validated, _total = _weighted_summary(classmate_grades)
        if average is not None and average > own_average:
            better += 1
    return better + 1


def _current_semester_label(classes):
    first = classes.order_by("name").first()
    return semester_for(first) if first is not None else EXAM_SEMESTER


def _page_hash(page):
    digest = sha256()
    try:
        with open(page.file.path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _combined_hash(pages):
    if not pages:
        return None
    digest = sha256()
    try:
        for page in pages:
            with open(page.file.path, "rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _duration_label(start, end):
    if not start or not end:
        return ""
    minutes = int(
        (datetime.combine(date.today(), end) - datetime.combine(date.today(), start))
        .total_seconds() / 60
    )
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return "%dh%02d" % (hours, minutes)
    if hours:
        return "%dh00" % hours
    return "%dmin" % minutes


def _pdf_response(buffer, filename):
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="%s"' % filename
    return response


def _validated_image(upload):
    if upload is None:
        return None
    try:
        with Image.open(upload) as image:
            if image.format not in ("JPEG", "PNG"):
                return None
            image.verify()
        upload.seek(0)
    except Exception:
        return None
    return upload


def _save_image(image, path):
    if image.mode in ("RGBA", "P", "LA"):
        image = image.convert("RGB")
    image.save(path)


def _parse_criteria(post):
    criteria = []
    index = 0
    while "crit_label_%s" % index in post:
        label = post.get("crit_label_%s" % index, "").strip()
        weight = _to_decimal(post.get("crit_weight_%s" % index, "0"))
        raw_points = (post.get("crit_points_%s" % index, "") or "").strip()
        points = _to_decimal(raw_points) if raw_points else Decimal("0")
        comment = post.get("crit_comment_%s" % index, "").strip()
        if label:
            criteria.append({
                "label": label,
                "weight": float(weight),
                "points": float(points),
                "comment": comment,
            })
        index += 1
    return criteria


def _to_decimal(raw):
    try:
        return Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _corrections_context(request, sessions, session, students, selected,
                         grade, comment=""):
    session_grades = list(StudentGrade.objects.filter(session=session))
    graded_ids = {item.student_id for item in session_grades}
    criteria = grade.criteria if (grade and grade.criteria) else [
        dict(item, points=None, comment="") for item in DEFAULT_CRITERIA
    ]
    total = len(students)
    graded = len(graded_ids & {s.pk for s in students})

    def first_with_status(predicate):
        for student in students:
            if predicate(student):
                return student
        return None

    grades_by_student = {item.student_id: item for item in session_grades}
    status_labels = {
        item.student_id: (
            "Publiée" if item.status == StudentGrade.STATUS_PUBLISHED
            else "Validée" if item.status == StudentGrade.STATUS_VALIDATED
            else "En révision"
        )
        for item in session_grades
    }
    for student in students:
        student.correction_status = status_labels.get(student.pk, "Non corrigée")
    first_not_graded = first_with_status(lambda s: s.pk not in grades_by_student)
    first_draft = first_with_status(
        lambda s: grades_by_student.get(s.pk) is not None
        and grades_by_student[s.pk].status == StudentGrade.STATUS_DRAFT
    )
    first_validated = first_with_status(
        lambda s: grades_by_student.get(s.pk) is not None
        and grades_by_student[s.pk].status in (
            StudentGrade.STATUS_VALIDATED, StudentGrade.STATUS_PUBLISHED,
        )
    )
    copy = (
        ExamCopy.objects.filter(session=session, student=selected)
        .prefetch_related("pages").first()
        if selected is not None else None
    )
    selected_index = next(
        (index for index, item in enumerate(students) if item.pk == selected.pk),
        None,
    ) if selected is not None else None
    prev_student = (
        students[selected_index - 1] if selected_index is not None and selected_index > 0
        else None
    )
    next_student = (
        students[selected_index + 1]
        if selected_index is not None and selected_index + 1 < len(students)
        else None
    )
    return {
        "sessions": sessions,
        "session": session,
        "students": students,
        "selected_student": selected,
        "grade": grade,
        "criteria": criteria,
        "comment": comment,
        "counts": {
            "total": total,
            "not_graded": total - graded,
            "draft": sum(1 for item in session_grades if item.status == StudentGrade.STATUS_DRAFT),
            "validated": sum(
                1 for item in session_grades
                if item.status in (StudentGrade.STATUS_VALIDATED, StudentGrade.STATUS_PUBLISHED)
            ),
            "published": sum(1 for item in session_grades if item.status == StudentGrade.STATUS_PUBLISHED),
        },
        "status_labels": status_labels,
        "progress": round(graded * 100 / total) if total else 0,
        "first_not_graded": first_not_graded,
        "first_draft": first_draft,
        "first_validated": first_validated,
        "copy": copy,
        "copy_pages": list(copy.pages.all()) if copy else [],
        "copy_has_file": bool(copy and copy.has_file),
        "copy_is_pdf": bool(copy and copy.is_pdf),
        "copy_is_zip": bool(copy and copy.is_zip),
        "grade_is_absent": _is_absent_grade(grade),
        "can_mark_absent": not bool(copy and copy.is_submitted) and not _is_absent_grade(grade),
        "subject": getattr(session, "subject", None),
        "prev_student": prev_student,
        "next_student": next_student,
    }


def _next_ungraded_student(session, students, current):
    graded = set(
        StudentGrade.objects.filter(session=session).values_list("student_id", flat=True)
    )
    ordered = [s for s in students if s.pk != current.pk]
    return next((s for s in ordered if s.pk not in graded), None) or current


def _jury_names(record):
    if record is None:
        return []
    members = list(
        record.jury_members.select_related("professor__membership__user")
        .order_by("role_label", "professor__membership__user__last_name")
    )
    if members:
        return [_display_name(member.professor) for member in members]
    return [
        _display_name(professor)
        for professor in record.school_class.professors.select_related("membership__user")
    ]


def _initials(name):
    parts = [part for part in (name or "").split() if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (parts[0][:2] if parts else "?").upper()


def _jury_context_members(record, school_class):
    by_professor = {
        member.professor_id: member for member in record.jury_members.all()
    }
    first_professor = school_class.professors.first()
    members = []
    for professor in school_class.professors.select_related("membership__user"):
        member = by_professor.get(professor.pk)
        name = _display_name(professor)
        members.append({
            "name": name,
            "initials": _initials(name),
            "role_label": (
                member.get_role_label_display() if member else
                ("Présidence du jury" if professor.pk == first_professor.pk
                 else "Examinateur")
            ),
            "status": member.status if member else JuryMember.STATUS_CONFIRMED,
        })
    for member in record.jury_members.exclude(
        professor__in=school_class.professors.all(),
    ).select_related("professor__membership__user"):
        name = _display_name(member.professor)
        members.append({
            "name": name,
            "initials": _initials(name),
            "role_label": member.get_role_label_display(),
            "status": member.status,
        })
    return members
