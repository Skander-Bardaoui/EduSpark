from unittest import mock

import requests
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, SchoolClass, StudentGroup, University
from accounts.tenancy import Role

from .models import Announcement, Forum, Message, Reply, Report, Thread
from .services import ai

PASSWORD = "Pass12345!"


def make_user(email, university, role, **extra):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD, **extra)
    membership = Membership.objects.create(user=user, university=university, role=role)
    return user, membership


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])  # tests 10x plus rapides
class CommunityTestCase(TestCase):
    """Deux universités ; dans la première, deux classes (A avec prof et étudiante, B sans eux)."""

    def setUp(self):
        self.uni = University.objects.create(name="Université Test", code="UT")
        self.other_uni = University.objects.create(name="Université Voisine", code="UV")

        self.admin, _ = make_user("admin@t.local", self.uni, Role.UNIVERSITY_ADMIN)
        self.prof, prof_m = make_user("prof@t.local", self.uni, Role.PROFESSOR, first_name="Hélène", last_name="Vasseur")
        self.other_prof, other_prof_m = make_user("prof2@t.local", self.uni, Role.PROFESSOR)
        self.student, student_m = make_user("etu@t.local", self.uni, Role.STUDENT, first_name="Camille", last_name="Martin")
        self.classmate, classmate_m = make_user("etu2@t.local", self.uni, Role.STUDENT)
        self.outsider, outsider_m = make_user("etu3@t.local", self.uni, Role.STUDENT)
        self.stranger, _ = make_user("etu@autre.local", self.other_uni, Role.STUDENT)

        self.class_a = SchoolClass.objects.create(university=self.uni, name="L3 Info", academic_year="2025-2026")
        self.class_b = SchoolClass.objects.create(university=self.uni, name="M1 Maths", academic_year="2025-2026")
        self.class_a.professors.add(prof_m.ensure_profile())
        self.class_b.professors.add(other_prof_m.ensure_profile())
        group_a = StudentGroup.objects.create(university=self.uni, school_class=self.class_a, name="TD1")
        group_a.students.add(student_m.ensure_profile(), classmate_m.ensure_profile())
        group_b = StudentGroup.objects.create(university=self.uni, school_class=self.class_b, name="TD1")
        group_b.students.add(outsider_m.ensure_profile())

        self.forum_a = Forum.objects.create(university=self.uni, school_class=self.class_a, title="Forum L3", created_by=self.prof)
        self.forum_b = Forum.objects.create(university=self.uni, school_class=self.class_b, title="Forum M1", created_by=self.other_prof)
        self.forum_general = Forum.objects.create(university=self.uni, title="Vie du campus", created_by=self.admin)
        self.forum_foreign = Forum.objects.create(university=self.other_uni, title="Forum étranger")

        self.thread = Thread.objects.create(forum=self.forum_a, author=self.student, title="Pile ou file ?", body="Quelle différence ?")
        self.reply = Reply.objects.create(thread=self.thread, author=self.prof, body="LIFO contre FIFO.")

    def login(self, user):
        self.client.force_login(user)
        return self.client


class VisibilityTests(CommunityTestCase):
    def forum_titles(self, user):
        response = self.login(user).get(reverse("community:student_forums"))
        self.assertEqual(response.status_code, 200)
        return {f.title for f in response.context["forums"]}

    def test_student_sees_own_class_and_general_forums_only(self):
        self.assertEqual(self.forum_titles(self.student), {"Forum L3", "Vie du campus"})
        self.assertEqual(self.forum_titles(self.outsider), {"Forum M1", "Vie du campus"})

    def test_professor_sees_only_the_classes_they_teach(self):
        self.assertEqual(self.forum_titles(self.prof), {"Forum L3", "Vie du campus"})

    def test_admin_sees_every_forum_of_the_university_but_not_others(self):
        self.assertEqual(self.forum_titles(self.admin), {"Forum L3", "Forum M1", "Vie du campus"})
        table = self.login(self.admin).get(reverse("community:admin_forum_supervision"))
        self.assertEqual({row["forum"].title for row in table.context["rows"]}, {"Forum L3", "Forum M1", "Vie du campus"})

    def test_forum_of_another_class_or_university_is_a_404(self):
        client = self.login(self.student)
        self.assertEqual(client.get(reverse("community:forum_detail", args=[self.forum_b.pk])).status_code, 404)
        self.assertEqual(client.get(reverse("community:forum_detail", args=[self.forum_foreign.pk])).status_code, 404)
        self.assertEqual(client.post(reverse("community:thread_create", args=[self.forum_b.pk]), {"title": "x", "body": "y"}).status_code, 404)

    def test_thread_of_a_hidden_forum_is_a_404(self):
        hidden = Thread.objects.create(forum=self.forum_b, author=self.outsider, title="Autre classe", body="…")
        self.assertEqual(self.login(self.student).get(reverse("community:thread_detail", args=[hidden.pk])).status_code, 404)

    def test_login_is_required(self):
        response = self.client.get(reverse("community:student_forums"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/connexion/", response["Location"])

    def test_feed_search_and_forum_filter(self):
        Thread.objects.create(forum=self.forum_general, author=self.student, title="Horaires de la bibliothèque", body="…")
        client = self.login(self.student)
        url = reverse("community:student_forums")
        self.assertEqual([t.title for t in client.get(url, {"q": "bibliothèque"}).context["page"]], ["Horaires de la bibliothèque"])
        self.assertEqual([t.title for t in client.get(url, {"forum": self.forum_a.pk}).context["page"]], ["Pile ou file ?"])

    def test_forum_detail_opens_the_feed_filtered_on_that_forum(self):
        response = self.login(self.student).get(reverse("community:forum_detail", args=[self.forum_a.pk]))
        self.assertRedirects(
            response, "%s?forum=%d" % (reverse("community:student_forums"), self.forum_a.pk), fetch_redirect_response=False,
        )
        self.assertEqual(self.client.get(reverse("community:forum_detail", args=[self.forum_b.pk])).status_code, 404)


class ForumManagementTests(CommunityTestCase):
    def test_student_cannot_create_a_forum(self):
        response = self.login(self.student).post(reverse("community:forum_create"), {"title": "Mon forum"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Forum.objects.filter(title="Mon forum").exists())

    def test_professor_creates_a_forum_for_their_class_only(self):
        client = self.login(self.prof)
        client.post(reverse("community:forum_create"), {"title": "Nouveau", "school_class": self.class_a.pk, "course_ref": "INF501"})
        forum = Forum.objects.get(title="Nouveau")
        self.assertEqual((forum.university, forum.created_by), (self.uni, self.prof))
        refused = client.post(reverse("community:forum_create"), {"title": "Intrus", "school_class": self.class_b.pk})
        self.assertEqual(refused.status_code, 200)
        self.assertFalse(Forum.objects.filter(title="Intrus").exists())

    def test_professor_cannot_edit_a_forum_they_do_not_manage(self):
        response = self.login(self.prof).post(reverse("community:forum_edit", args=[self.forum_general.pk]), {"title": "Piraté"})
        self.assertEqual(response.status_code, 403)

    def test_locked_forum_blocks_students_but_not_the_professor(self):
        self.forum_a.is_locked = True
        self.forum_a.save()
        client = self.login(self.student)
        client.post(reverse("community:thread_create", args=[self.forum_a.pk]), {"title": "Tard", "body": "…"})
        client.post(reverse("community:reply_create", args=[self.thread.pk]), {"body": "Trop tard"})
        self.assertFalse(Thread.objects.filter(title="Tard").exists())
        self.assertFalse(Reply.objects.filter(body="Trop tard").exists())
        self.login(self.prof).post(reverse("community:reply_create", args=[self.thread.pk]), {"body": "Note du prof"})
        self.assertTrue(Reply.objects.filter(body="Note du prof").exists())

    def test_deleting_a_forum_requires_confirmation_and_cascades(self):
        client = self.login(self.prof)
        self.assertContains(client.get(reverse("community:forum_delete", args=[self.forum_a.pk])), "Confirmer la suppression")
        self.assertTrue(Forum.objects.filter(pk=self.forum_a.pk).exists())
        client.post(reverse("community:forum_delete", args=[self.forum_a.pk]))
        self.assertFalse(Thread.objects.filter(pk=self.thread.pk).exists())


class ThreadAndReplyTests(CommunityTestCase):
    def test_student_asks_a_question(self):
        response = self.login(self.classmate).post(
            reverse("community:thread_create", args=[self.forum_a.pk]), {"title": "Nouvelle question", "body": "Détails"},
        )
        thread = Thread.objects.get(title="Nouvelle question")
        self.assertRedirects(response, reverse("community:thread_detail", args=[thread.pk]))
        self.assertEqual((thread.author, thread.university), (self.classmate, self.uni))

    def test_only_the_author_edits_a_question_and_a_reply(self):
        client = self.login(self.classmate)
        self.assertEqual(client.post(reverse("community:thread_edit", args=[self.thread.pk]), {"title": "x", "body": "y"}).status_code, 403)
        self.assertEqual(client.post(reverse("community:reply_edit", args=[self.reply.pk]), {"body": "x"}).status_code, 403)
        self.login(self.student).post(reverse("community:thread_edit", args=[self.thread.pk]), {"title": "Titre corrigé", "body": "Corps"})
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.title, "Titre corrigé")

    def test_author_or_moderator_deletes_a_question_but_not_a_classmate(self):
        self.assertEqual(self.login(self.classmate).post(reverse("community:thread_delete", args=[self.thread.pk])).status_code, 403)
        self.login(self.prof).post(reverse("community:thread_delete", args=[self.thread.pk]))
        self.assertFalse(Thread.objects.filter(pk=self.thread.pk).exists())

    def test_empty_reply_is_rejected(self):
        self.login(self.student).post(reverse("community:reply_create", args=[self.thread.pk]), {"body": "   "})
        self.assertEqual(self.thread.replies.count(), 1)

    def test_professor_validates_a_single_solution_and_their_name_is_kept(self):
        other = Reply.objects.create(thread=self.thread, author=self.classmate, body="Autre piste")
        client = self.login(self.prof)
        client.post(reverse("community:reply_mark_solution", args=[self.reply.pk]))
        client.post(reverse("community:reply_mark_solution", args=[other.pk]))
        self.thread.refresh_from_db(); self.reply.refresh_from_db(); other.refresh_from_db()
        self.assertTrue(self.thread.is_resolved)
        self.assertEqual((self.reply.is_solution, self.reply.validated_by), (False, None))
        self.assertEqual((other.is_solution, other.validated_by), (True, self.prof))
        self.assertIsNotNone(other.validated_at)
        self.assertEqual(other.validator_name, "Hélène Vasseur")

    def test_validation_can_be_withdrawn_by_the_professor(self):
        client = self.login(self.prof)
        url = reverse("community:reply_mark_solution", args=[self.reply.pk])
        client.post(url)
        client.post(url)
        self.reply.refresh_from_db()
        self.assertEqual((self.reply.is_solution, self.reply.validated_by, self.reply.validated_at), (False, None, None))

    def test_only_the_professor_of_the_forum_can_validate(self):
        url = reverse("community:reply_mark_solution", args=[self.reply.pk])
        # l'auteur de la question, un camarade, l'administration : refusés
        for user in (self.student, self.classmate, self.admin):
            self.assertEqual(self.login(user).post(url).status_code, 403, user.email)
        # un professeur d'une autre classe ne voit même pas ce forum
        self.assertEqual(self.login(self.other_prof).post(url).status_code, 404)
        self.reply.refresh_from_db()
        self.assertFalse(self.reply.is_solution)

    def test_validated_solution_displays_the_validator_name_and_only_professors_get_the_button(self):
        self.login(self.prof).post(reverse("community:reply_mark_solution", args=[self.reply.pk]))
        thread_url = reverse("community:thread_detail", args=[self.thread.pk])
        student_page = self.login(self.student).get(thread_url)
        self.assertContains(student_page, "Solution validée par Pr. Hélène Vasseur")
        self.assertNotContains(student_page, "Valider comme solution")
        self.assertNotContains(student_page, "Retirer ma validation")
        prof_page = self.login(self.prof).get(thread_url)
        self.assertContains(prof_page, "Retirer ma validation")

    def test_unvalidated_reply_shows_no_solution_badge_but_the_professor_can_validate(self):
        thread_url = reverse("community:thread_detail", args=[self.thread.pk])
        self.assertNotContains(self.login(self.student).get(thread_url), "Solution validée")
        self.assertContains(self.login(self.prof).get(thread_url), "Valider comme solution")

    def test_student_cannot_reopen_a_question_with_a_validated_solution(self):
        self.login(self.prof).post(reverse("community:reply_mark_solution", args=[self.reply.pk]))
        url = reverse("community:thread_toggle_resolved", args=[self.thread.pk])
        self.login(self.student).post(url)
        self.thread.refresh_from_db(); self.reply.refresh_from_db()
        self.assertEqual((self.thread.is_resolved, self.reply.is_solution), (True, True))
        self.login(self.prof).post(url)  # le professeur peut rouvrir : la validation est retirée
        self.thread.refresh_from_db(); self.reply.refresh_from_db()
        self.assertEqual((self.thread.is_resolved, self.reply.is_solution, self.reply.validated_by), (False, False, None))

    def test_student_can_still_mark_their_own_question_resolved_without_a_solution(self):
        self.login(self.student).post(reverse("community:thread_toggle_resolved", args=[self.thread.pk]))
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_resolved)

    def test_search_and_state_filters_in_a_forum(self):
        Thread.objects.create(forum=self.forum_a, author=self.student, title="Sans réponse ici", body="…")
        client = self.login(self.student)
        url = reverse("community:student_forums")
        params = {"forum": self.forum_a.pk}
        self.assertEqual([t.title for t in client.get(url, {**params, "etat": "sans_prof"}).context["page"]], ["Sans réponse ici"])
        self.assertEqual([t.title for t in client.get(url, {**params, "q": "pile"}).context["page"]], ["Pile ou file ?"])


class ModerationTests(CommunityTestCase):
    def test_student_cannot_moderate(self):
        client = self.login(self.student)
        self.assertEqual(client.post(reverse("community:thread_toggle_hidden", args=[self.thread.pk])).status_code, 403)
        self.assertEqual(client.get(reverse("community:prof_moderation")).status_code, 403)

    def test_hidden_content_disappears_for_students_but_not_for_the_professor(self):
        self.login(self.prof).post(reverse("community:reply_toggle_hidden", args=[self.reply.pk]))
        self.reply.refresh_from_db()
        self.assertTrue(self.reply.is_hidden)
        student_view = self.login(self.student).get(reverse("community:thread_detail", args=[self.thread.pk]))
        self.assertEqual(list(student_view.context["replies"]), [])
        prof_view = self.login(self.prof).get(reverse("community:thread_detail", args=[self.thread.pk]))
        self.assertEqual(list(prof_view.context["replies"]), [self.reply])

    def test_hidden_thread_is_a_404_for_students(self):
        self.thread.is_hidden = True
        self.thread.save()
        self.assertEqual(self.login(self.student).get(reverse("community:thread_detail", args=[self.thread.pk])).status_code, 404)
        self.assertEqual(self.login(self.prof).get(reverse("community:thread_detail", args=[self.thread.pk])).status_code, 200)

    def test_report_flow_hides_the_content(self):
        client = self.login(self.classmate)
        url = reverse("community:report_create", args=["reponse", self.reply.pk])
        client.post(url, {"reason": Report.REASON_OFFTOPIC, "details": "Hors sujet"})
        client.post(url, {"reason": Report.REASON_SPAM})  # doublon ignoré
        report = Report.objects.get()
        self.assertEqual((report.reporter, report.reply, report.university), (self.classmate, self.reply, self.uni))

        queue = self.login(self.prof).get(reverse("community:prof_moderation"))
        self.assertEqual([r.pk for r in queue.context["reports"]], [report.pk])
        self.client.post(reverse("community:report_resolve", args=[report.pk]), {"action": "masquer"})
        report.refresh_from_db(); self.reply.refresh_from_db()
        self.assertEqual((report.status, report.handled_by, self.reply.is_hidden), (Report.STATUS_ACTIONED, self.prof, True))

    def test_dismissing_a_report_keeps_the_content(self):
        report = Report.objects.create(thread=self.thread, reporter=self.classmate, reason=Report.REASON_OTHER)
        self.login(self.prof).post(reverse("community:report_resolve", args=[report.pk]), {"action": "ignorer"})
        report.refresh_from_db(); self.thread.refresh_from_db()
        self.assertEqual((report.status, self.thread.is_hidden), (Report.STATUS_DISMISSED, False))

    def test_professor_only_sees_reports_of_their_own_forums(self):
        foreign = Thread.objects.create(forum=self.forum_b, author=self.outsider, title="Autre classe", body="…")
        Report.objects.create(thread=foreign, reporter=self.outsider, reason=Report.REASON_SPAM)
        mine = Report.objects.create(thread=self.thread, reporter=self.classmate, reason=Report.REASON_SPAM)
        queue = self.login(self.prof).get(reverse("community:prof_moderation"))
        self.assertEqual([r.pk for r in queue.context["reports"]], [mine.pk])
        every = self.login(self.admin).get(reverse("community:admin_reports"))
        self.assertEqual(len(every.context["reports"]), 2)

    def test_cannot_report_own_message(self):
        self.login(self.student).post(reverse("community:report_create", args=["question", self.thread.pk]), {"reason": Report.REASON_SPAM})
        self.assertFalse(Report.objects.exists())


class AnnouncementTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.everyone = Announcement.objects.create(university=self.uni, author=self.admin, title="Rentrée", body="…")
        self.for_a = Announcement.objects.create(
            university=self.uni, author=self.prof, title="Consigne L3", body="…",
            audience=Announcement.AUDIENCE_CLASS, school_class=self.class_a,
        )
        self.for_b = Announcement.objects.create(
            university=self.uni, author=self.other_prof, title="Consigne M1", body="…",
            audience=Announcement.AUDIENCE_CLASS, school_class=self.class_b,
        )
        Announcement.objects.create(university=self.other_uni, title="Autre université", body="…")

    def titles(self, user, **params):
        response = self.login(user).get(reverse("community:student_announcements"), params)
        return {a.title for a in response.context["announcements"]}

    def test_audience_rules(self):
        self.assertEqual(self.titles(self.student), {"Rentrée", "Consigne L3"})
        self.assertEqual(self.titles(self.outsider), {"Rentrée", "Consigne M1"})
        self.assertEqual(self.titles(self.admin), {"Rentrée", "Consigne L3", "Consigne M1"})

    def test_student_cannot_publish(self):
        response = self.login(self.student).post(reverse("community:announcement_create"), {
            "title": "Faux", "body": "x", "audience": "tous", "priority": "normale", "category": "organisation"})
        self.assertEqual(response.status_code, 403)

    def test_professor_publishes_and_edits_only_their_own(self):
        client = self.login(self.prof)
        client.post(reverse("community:announcement_create"), {
            "title": "Devoir reporté", "body": "Au lundi suivant.", "audience": "classe",
            "school_class": self.class_a.pk, "priority": "importante", "category": "examens"})
        created = Announcement.objects.get(title="Devoir reporté")
        self.assertEqual((created.author, created.university), (self.prof, self.uni))
        self.assertEqual(client.post(reverse("community:announcement_edit", args=[self.for_b.pk]), {"title": "x"}).status_code, 404)
        self.assertEqual(client.post(reverse("community:announcement_edit", args=[self.everyone.pk]), {"title": "x"}).status_code, 403)

    def test_class_audience_needs_a_class(self):
        response = self.login(self.prof).post(reverse("community:announcement_create"), {
            "title": "Sans classe", "body": "x", "audience": "classe", "priority": "normale", "category": "organisation"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Announcement.objects.filter(title="Sans classe").exists())

    def test_admin_can_delete_any_announcement(self):
        self.login(self.admin).post(reverse("community:announcement_delete", args=[self.for_a.pk]))
        self.assertFalse(Announcement.objects.filter(pk=self.for_a.pk).exists())

    def test_announcement_of_another_class_is_a_404(self):
        self.assertEqual(self.login(self.student).get(reverse("community:announcement_detail", args=[self.for_b.pk])).status_code, 404)

    def test_search_filters(self):
        self.assertEqual(self.titles(self.admin, q="M1"), {"Consigne M1"})


class MessageTests(CommunityTestCase):
    def conversations(self, user):
        return self.login(user).get(reverse("community:student_messages")).context["conversations"]

    def test_send_read_reply_and_delete(self):
        client = self.login(self.student)
        client.post(reverse("community:message_create"), {"recipient": self.prof.pk, "subject": "Horaire", "body": "Jeudi ?"})
        message = Message.objects.get()
        self.assertEqual((message.sender, message.recipient, message.university, message.read_at), (self.student, self.prof, self.uni, None))

        inbox = self.login(self.prof).get(reverse("community:prof_messages"))
        self.assertEqual(inbox.context["unread_total"], 1)
        self.assertEqual([c["user"] for c in inbox.context["conversations"]], [self.student])
        self.client.post(reverse("community:conversation_mark_read", args=[self.student.pk]))
        message.refresh_from_db()
        self.assertIsNotNone(message.read_at)

        # réponse rapide (sans objet) : la conversation regroupe les deux messages
        self.client.post(reverse("community:message_create"), {"recipient": self.student.pk, "subject": "", "body": "Oui, 10h."})
        self.assertEqual([len(c["messages"]) for c in self.conversations(self.student)], [2])

        self.login(self.prof).post(reverse("community:conversation_delete", args=[self.student.pk]))
        self.assertEqual(Message.objects.count(), 2)  # encore dans la boîte de l'étudiant
        self.login(self.student).post(reverse("community:conversation_delete", args=[self.prof.pk]))
        self.assertFalse(Message.objects.exists())

    def test_third_party_never_sees_a_conversation(self):
        Message.objects.create(university=self.uni, sender=self.student, recipient=self.prof, subject="Privé", body="…")
        for user in (self.classmate, self.admin, self.stranger):
            self.assertEqual(self.conversations(user), [])
        self.assertEqual(self.login(self.classmate).post(reverse("community:conversation_delete", args=[self.prof.pk])).status_code, 404)
        self.assertEqual(Message.objects.count(), 1)

    def test_can_only_write_to_members_of_the_same_university(self):
        response = self.login(self.student).post(reverse("community:message_create"), {
            "recipient": self.stranger.pk, "subject": "Hors université", "body": "…"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.exists())

    def test_cannot_write_to_oneself(self):
        self.login(self.student).post(reverse("community:message_create"), {"recipient": self.student.pk, "subject": "Moi", "body": "…"})
        self.assertFalse(Message.objects.exists())

    def test_conversations_are_grouped_per_correspondent_and_ordered_by_recency(self):
        Message.objects.create(university=self.uni, sender=self.student, recipient=self.prof, subject="Alpha", body="1")
        Message.objects.create(university=self.uni, sender=self.classmate, recipient=self.student, subject="Bêta", body="2")
        Message.objects.create(university=self.uni, sender=self.prof, recipient=self.student, subject="", body="3")
        convs = self.conversations(self.student)
        self.assertEqual([c["user"] for c in convs], [self.prof, self.classmate])
        self.assertEqual([c["unread"] for c in convs], [1, 1])
        self.assertEqual([m.body for m in convs[0]["messages"]], ["1", "3"])
        page = self.client.get(reverse("community:student_messages"), {"avec": self.classmate.pk})
        self.assertEqual(page.context["active_id"], self.classmate.pk)


class LiveMessagingTests(CommunityTestCase):
    def poll(self, user, **params):
        response = self.login(user).get(reverse("community:message_poll"), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        return response.json()

    def send(self, user, recipient, body, subject=""):
        return self.login(user).post(
            reverse("community:message_create"), {"recipient": recipient.pk, "subject": subject, "body": body},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    def test_ajax_send_returns_the_message_without_redirect(self):
        response = self.send(self.student, self.prof, "Bonjour en direct")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"]["body"], "Bonjour en direct")
        self.assertTrue(data["message"]["mine"])
        self.assertEqual(data["message"]["other_id"], self.prof.pk)
        self.assertEqual(Message.objects.get().sender, self.student)

    def test_ajax_send_reports_errors_as_json(self):
        response = self.send(self.student, self.stranger, "Hors université")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(Message.objects.exists())

    def test_poll_returns_only_new_messages_for_the_recipient(self):
        first = self.send(self.student, self.prof, "Un").json()["message"]
        data = self.poll(self.prof, apres=0)
        self.assertEqual([m["body"] for m in data["messages"]], ["Un"])
        self.assertFalse(data["messages"][0]["mine"])
        self.assertEqual(data["messages"][0]["other_name"], "Camille Martin")
        self.assertEqual(data["unread_total"], 1)
        self.send(self.student, self.prof, "Deux")
        later = self.poll(self.prof, apres=first["id"])
        self.assertEqual([m["body"] for m in later["messages"]], ["Deux"])
        self.assertEqual(self.poll(self.prof, apres=later["messages"][0]["id"])["messages"], [])

    def test_poll_also_returns_my_own_messages_sent_from_another_tab(self):
        self.send(self.student, self.prof, "Depuis un autre onglet")
        data = self.poll(self.student, apres=0)
        self.assertEqual([(m["body"], m["mine"]) for m in data["messages"]], [("Depuis un autre onglet", True)])

    def test_poll_never_leaks_messages_of_others_or_deleted_ones(self):
        self.send(self.student, self.prof, "Privé")
        for user in (self.classmate, self.admin, self.stranger):
            self.assertEqual(self.poll(user, apres=0)["messages"], [])
        self.login(self.prof).post(reverse("community:conversation_delete", args=[self.student.pk]))
        self.assertEqual(self.poll(self.prof, apres=0)["messages"], [])
        self.assertEqual(len(self.poll(self.student, apres=0)["messages"]), 1)

    def test_read_receipts_come_back_for_followed_messages(self):
        sent = self.send(self.student, self.prof, "Lu ?").json()["message"]
        self.assertEqual(self.poll(self.student, apres=sent["id"], suivis=str(sent["id"]))["read_ids"], [])
        self.login(self.prof).post(reverse("community:conversation_mark_read", args=[self.student.pk]))
        data = self.poll(self.student, apres=sent["id"], suivis=str(sent["id"]))
        self.assertEqual(data["read_ids"], [sent["id"]])
        self.assertEqual(self.poll(self.prof, apres=sent["id"])["unread_total"], 0)

    def test_inbox_exposes_the_last_message_id_to_start_polling_from(self):
        self.send(self.student, self.prof, "A")
        last = self.send(self.student, self.prof, "B").json()["message"]["id"]
        self.assertEqual(self.login(self.prof).get(reverse("community:prof_messages")).context["last_id"], last)

    def test_poll_requires_login_and_ignores_garbage_parameters(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("community:message_poll")).status_code, 302)
        data = self.poll(self.student, apres="abc", suivis="x,1;2,,")
        self.assertEqual(data["messages"], [])


class AISuggestionTests(CommunityTestCase):
    url_name = "community:thread_ai_suggestion"

    def post(self, user=None):
        return self.login(user or self.student).post(reverse(self.url_name, args=[self.thread.pk]))

    def groq_reply(self, content, status=200):
        response = mock.Mock(status_code=status, text=content)
        response.json.return_value = {"choices": [{"message": {"content": content}}]}
        return response

    def test_without_api_key_a_clear_message_is_returned_and_nothing_is_saved(self):
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": ""}):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])
        self.assertIn("indisponible", response.json()["error"])
        self.assertEqual(self.thread.replies.count(), 1)

    def test_suggestion_is_returned_as_a_draft_not_published(self):
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}), \
                mock.patch.object(ai.requests, "post", return_value=self.groq_reply("<think>réflexion</think>Une pile est LIFO.")) as post:
            response = self.post()
        self.assertEqual(response.json(), {"ok": True, "text": "Une pile est LIFO."})
        self.assertEqual(self.thread.replies.count(), 1)
        prompt = post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertIn("Pile ou file ?", prompt)
        self.assertIn("LIFO contre FIFO.", prompt)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")

    def test_provider_failures_become_unavailable(self):
        failures = (
            {"side_effect": requests.ConnectionError("down")},
            {"return_value": self.groq_reply("quota", status=429)},
            {"return_value": mock.Mock(status_code=200, json=mock.Mock(return_value={"oups": 1}))},
            {"return_value": self.groq_reply("   ")},
        )
        for failure in failures:
            with mock.patch.dict("os.environ", {"GROQ_API_KEY": "k"}), mock.patch.object(ai.requests, "post", **failure):
                self.assertEqual(self.post().status_code, 503, failure)

    def test_hidden_replies_are_not_sent_to_the_model(self):
        Reply.objects.create(thread=self.thread, author=self.classmate, body="Propos masqué", is_hidden=True)
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "k"}), \
                mock.patch.object(ai.requests, "post", return_value=self.groq_reply("ok")) as post:
            self.post()
        self.assertNotIn("Propos masqué", post.call_args.kwargs["json"]["messages"][1]["content"])

    def test_cannot_suggest_for_a_thread_one_cannot_see(self):
        self.assertEqual(self.post(self.outsider).status_code, 404)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.login(self.student).get(reverse(self.url_name, args=[self.thread.pk])).status_code, 405)

    def test_ai_assisted_flag_is_stored_with_the_published_reply(self):
        self.login(self.student).post(reverse("community:reply_create", args=[self.thread.pk]), {"body": "Brouillon relu", "ai_assisted": "True"})
        self.assertTrue(Reply.objects.get(body="Brouillon relu").ai_assisted)
        self.login(self.student).post(reverse("community:reply_create", args=[self.thread.pk]), {"body": "Écrit à la main"})
        self.assertFalse(Reply.objects.get(body="Écrit à la main").ai_assisted)

    def test_module_works_without_ai(self):
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": ""}):
            page = self.login(self.student).get(reverse("community:thread_detail", args=[self.thread.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Suggérer une réponse")
        self.assertContains(page, "pas configuré")


class FeedDesignTests(CommunityTestCase):
    def test_each_role_gets_its_own_page(self):
        student = self.login(self.student).get(reverse("community:student_forums"))
        self.assertTemplateUsed(student, "community/student_forums.html")
        self.assertContains(student, "Assistant IA Forums")
        prof = self.login(self.prof).get(reverse("community:prof_forums"))
        self.assertTemplateUsed(prof, "community/prof_forums.html")
        self.assertContains(prof, "Taux de résolution")
        self.assertTemplateUsed(self.login(self.admin).get(reverse("community:admin_forum_supervision")), "community/admin_forum_supervision.html")
        self.assertTemplateUsed(self.login(self.admin).get(reverse("community:admin_communication")), "community/admin_communication.html")
        self.assertTemplateUsed(self.login(self.admin).get(reverse("community:admin_reports")), "community/admin_reports.html")
        self.assertTemplateUsed(self.login(self.prof).get(reverse("community:prof_moderation")), "community/prof_moderation.html")

    def test_validated_solution_is_shown_as_certified_in_the_feed(self):
        self.login(self.prof).post(reverse("community:reply_mark_solution", args=[self.reply.pk]))
        page = self.login(self.student).get(reverse("community:student_forums"))
        self.assertContains(page, "Résolu certifié Enseignant")
        self.assertContains(page, "Réponse validée par Pr. Hélène Vasseur")
        self.assertEqual([t.title for t in self.client.get(reverse("community:student_forums"), {"etat": "officielle"}).context["page"]], ["Pile ou file ?"])

    def test_question_without_staff_reply_is_waiting_for_a_teacher(self):
        waiting = Thread.objects.create(forum=self.forum_a, author=self.classmate, title="Sans prof", body="…")
        Reply.objects.create(thread=waiting, author=self.student, body="Réponse d'un camarade")
        feed = self.login(self.prof).get(reverse("community:prof_forums"), {"etat": "sans_prof"})
        self.assertEqual([t.title for t in feed.context["page"]], ["Sans prof"])
        self.assertEqual(feed.context["kpi_pending"], 1)
        self.assertEqual(feed.context["count_sans_prof"], 1)

    def test_votes_toggle_once_per_user(self):
        url = reverse("community:thread_toggle_vote", args=[self.thread.pk])
        self.login(self.student).post(url)
        self.login(self.classmate).post(url)
        self.assertEqual(self.thread.votes.count(), 2)
        self.client.post(url)  # le même étudiant retire son vote
        self.assertEqual(self.thread.votes.count(), 1)
        feed = self.client.get(reverse("community:student_forums"))
        self.assertEqual(feed.context["page"][0].vote_count, 1)

    def test_vote_on_a_thread_one_cannot_see_is_a_404(self):
        hidden = Thread.objects.create(forum=self.forum_b, author=self.outsider, title="Autre classe", body="…")
        self.assertEqual(self.login(self.student).post(reverse("community:thread_toggle_vote", args=[hidden.pk])).status_code, 404)

    def test_view_counter_ignores_the_author(self):
        url = reverse("community:thread_detail", args=[self.thread.pk])
        self.login(self.student).get(url)
        self.login(self.classmate).get(url)
        self.login(self.prof).get(url)
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.view_count, 2)

    def test_ask_a_question_from_the_feed_with_a_forum_choice(self):
        client = self.login(self.classmate)
        page = client.get(reverse("community:thread_new"))
        self.assertEqual({f.title for f in page.context["form"].fields["forum"].queryset}, {"Forum L3", "Vie du campus"})
        client.post(reverse("community:thread_new"), {"forum": self.forum_a.pk, "title": "Depuis le fil", "body": "…"})
        self.assertEqual(Thread.objects.get(title="Depuis le fil").forum, self.forum_a)
        refused = client.post(reverse("community:thread_new"), {"forum": self.forum_b.pk, "title": "Mauvais forum", "body": "…"})
        self.assertEqual(refused.status_code, 200)
        self.assertFalse(Thread.objects.filter(title="Mauvais forum").exists())

    def test_locked_forums_are_not_offered_to_students(self):
        self.forum_a.is_locked = True
        self.forum_a.save()
        form = self.login(self.student).get(reverse("community:thread_new")).context["form"]
        self.assertEqual({f.title for f in form.fields["forum"].queryset}, {"Vie du campus"})

    def test_ai_panel_keep_publishes_the_draft_as_an_ai_assisted_reply(self):
        self.login(self.classmate).post(
            reverse("community:reply_create", args=[self.thread.pk]), {"body": "Suggestion gardée", "ai_assisted": "True"},
        )
        reply = Reply.objects.get(body="Suggestion gardée")
        self.assertEqual((reply.author, reply.ai_assisted), (self.classmate, True))

    def test_top_contributors_count_validated_solutions(self):
        self.login(self.prof).post(reverse("community:reply_mark_solution", args=[self.reply.pk]))
        top = self.login(self.student).get(reverse("community:student_forums")).context["top_contributors"]
        self.assertEqual([(c["user"], c["count"]) for c in top], [(self.prof, 1)])


class AnnouncementDesignTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.exam = Announcement.objects.create(
            university=self.uni, author=self.prof, title="Partiel", body="Amphi A", category="examens",
            audience=Announcement.AUDIENCE_CLASS, school_class=self.class_a, is_pinned=True,
        )
        self.campus = Announcement.objects.create(university=self.uni, author=self.admin, title="Campus fermé", body="…", category="campus")

    def test_unread_tracking_and_mark_all_read(self):
        page = self.login(self.student).get(reverse("community:student_announcements"))
        self.assertEqual(page.context["unread_count"], 2)
        self.assertEqual(page.context["pinned"], self.exam)
        self.assertEqual([a.title for a in page.context["announcements"]], ["Campus fermé"])  # l'épinglée a sa carte dédiée
        self.client.get(reverse("community:announcement_detail", args=[self.campus.pk]))
        self.assertEqual(self.client.get(reverse("community:student_announcements")).context["unread_count"], 1)
        self.client.post(reverse("community:announcement_mark_all_read"))
        self.assertEqual(self.client.get(reverse("community:student_announcements")).context["unread_count"], 0)
        # la lecture est personnelle
        self.assertEqual(self.login(self.classmate).get(reverse("community:student_announcements")).context["unread_count"], 2)

    def test_categories_offered_as_filters_match_the_visible_announcements(self):
        categories = dict(self.login(self.student).get(reverse("community:student_announcements")).context["categories"])
        self.assertEqual(categories, {"examens": "Examens", "campus": "Vie du campus"})

    def test_admin_stats_and_read_rate(self):
        self.login(self.student).get(reverse("community:announcement_detail", args=[self.campus.pk]))
        page = self.login(self.admin).get(reverse("community:admin_communication"))
        self.assertEqual((page.context["total"], page.context["pinned_count"]), (2, 1))
        self.assertEqual(page.context["read_rate"], round(100 * 1 / 6))

    def test_category_is_stored_with_the_announcement(self):
        self.login(self.prof).post(reverse("community:announcement_create"), {
            "title": "Dépôt TP", "body": "Vendredi", "audience": "tous", "priority": "normale", "category": "ressources"})
        created = Announcement.objects.get(title="Dépôt TP")
        self.assertEqual((created.category, created.category_icon), ("ressources", "folder_shared"))


class ForumManagementPageTests(CommunityTestCase):
    def test_professor_manages_only_their_forums_and_admin_all(self):
        prof_rows = self.login(self.prof).get(reverse("community:forum_manage")).context["rows"]
        self.assertEqual({r["forum"].title for r in prof_rows}, {"Forum L3"})
        admin_rows = self.login(self.admin).get(reverse("community:forum_manage")).context["rows"]
        self.assertEqual(len(admin_rows), 3)
        self.assertEqual(self.login(self.student).get(reverse("community:forum_manage")).status_code, 403)

    def test_lock_toggle_and_watch_status(self):
        client = self.login(self.prof)
        client.post(reverse("community:forum_toggle_lock", args=[self.forum_a.pk]))
        self.forum_a.refresh_from_db()
        self.assertTrue(self.forum_a.is_locked)
        self.assertEqual(client.get(reverse("community:forum_manage")).context["rows"][0]["status"], "locked")
        client.post(reverse("community:forum_toggle_lock", args=[self.forum_a.pk]))
        Report.objects.create(thread=self.thread, reporter=self.classmate, reason=Report.REASON_SPAM)
        self.assertEqual(client.get(reverse("community:forum_manage")).context["rows"][0]["status"], "watch")

    def test_only_a_manager_can_lock(self):
        url = reverse("community:forum_toggle_lock", args=[self.forum_a.pk])
        self.assertEqual(self.login(self.student).post(url).status_code, 403)
        self.assertEqual(self.login(self.other_prof).post(url).status_code, 404)

    def test_moderation_page_computes_its_kpis(self):
        report = Report.objects.create(thread=self.thread, reporter=self.classmate, reason=Report.REASON_DISRESPECT)
        page = self.login(self.prof).get(reverse("community:prof_moderation"))
        self.assertEqual((page.context["open_count"], page.context["high_count"]), (1, 1))
        self.client.post(reverse("community:report_resolve", args=[report.pk]), {"action": "masquer"})
        page = self.client.get(reverse("community:prof_moderation"))
        self.assertEqual((page.context["open_count"], page.context["treated_week"], page.context["hidden_count"]), (0, 1, 1))
