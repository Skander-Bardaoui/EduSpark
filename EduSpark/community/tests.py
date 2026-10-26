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
        return {f.title for f in response.context["page"]}

    def test_student_sees_own_class_and_general_forums_only(self):
        self.assertEqual(self.forum_titles(self.student), {"Forum L3", "Vie du campus"})
        self.assertEqual(self.forum_titles(self.outsider), {"Forum M1", "Vie du campus"})

    def test_professor_sees_only_the_classes_they_teach(self):
        self.assertEqual(self.forum_titles(self.prof), {"Forum L3", "Vie du campus"})

    def test_admin_sees_every_forum_of_the_university_but_not_others(self):
        self.assertEqual(self.forum_titles(self.admin), {"Forum L3", "Forum M1", "Vie du campus"})

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

    def test_forum_search_and_filter(self):
        client = self.login(self.admin)
        found = client.get(reverse("community:admin_forum_supervision"), {"q": "campus"})
        self.assertEqual([f.title for f in found.context["page"]], ["Vie du campus"])
        general = client.get(reverse("community:admin_forum_supervision"), {"classe": "general"})
        self.assertEqual([f.title for f in general.context["page"]], ["Vie du campus"])


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
        url = reverse("community:forum_detail", args=[self.forum_a.pk])
        self.assertEqual([t.title for t in client.get(url, {"etat": "sans_reponse"}).context["page"]], ["Sans réponse ici"])
        self.assertEqual([t.title for t in client.get(url, {"q": "pile"}).context["page"]], ["Pile ou file ?"])


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
        self.assertEqual([r.pk for r in queue.context["page"]], [report.pk])
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
        self.assertEqual([r.pk for r in queue.context["page"]], [mine.pk])
        every = self.login(self.admin).get(reverse("community:admin_reports"))
        self.assertEqual(len(every.context["page"]), 2)

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
        return {a.title for a in response.context["page"]}

    def test_audience_rules(self):
        self.assertEqual(self.titles(self.student), {"Rentrée", "Consigne L3"})
        self.assertEqual(self.titles(self.outsider), {"Rentrée", "Consigne M1"})
        self.assertEqual(self.titles(self.admin), {"Rentrée", "Consigne L3", "Consigne M1"})

    def test_student_cannot_publish(self):
        response = self.login(self.student).post(reverse("community:announcement_create"), {
            "title": "Faux", "body": "x", "audience": "tous", "priority": "normale"})
        self.assertEqual(response.status_code, 403)

    def test_professor_publishes_and_edits_only_their_own(self):
        client = self.login(self.prof)
        client.post(reverse("community:announcement_create"), {
            "title": "Devoir reporté", "body": "Au lundi suivant.", "audience": "classe",
            "school_class": self.class_a.pk, "priority": "importante"})
        created = Announcement.objects.get(title="Devoir reporté")
        self.assertEqual((created.author, created.university), (self.prof, self.uni))
        self.assertEqual(client.post(reverse("community:announcement_edit", args=[self.for_b.pk]), {"title": "x"}).status_code, 404)
        self.assertEqual(client.post(reverse("community:announcement_edit", args=[self.everyone.pk]), {"title": "x"}).status_code, 403)

    def test_class_audience_needs_a_class(self):
        response = self.login(self.prof).post(reverse("community:announcement_create"), {
            "title": "Sans classe", "body": "x", "audience": "classe", "priority": "normale"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Announcement.objects.filter(title="Sans classe").exists())

    def test_admin_can_delete_any_announcement(self):
        self.login(self.admin).post(reverse("community:announcement_delete", args=[self.for_a.pk]))
        self.assertFalse(Announcement.objects.filter(pk=self.for_a.pk).exists())

    def test_announcement_of_another_class_is_a_404(self):
        self.assertEqual(self.login(self.student).get(reverse("community:announcement_detail", args=[self.for_b.pk])).status_code, 404)

    def test_search_filters(self):
        self.assertEqual(self.titles(self.admin, q="M1"), {"Consigne M1"})
        self.assertEqual(self.titles(self.admin, classe=self.class_a.pk), {"Consigne L3"})


class MessageTests(CommunityTestCase):
    def test_send_read_reply_and_delete(self):
        client = self.login(self.student)
        client.post(reverse("community:message_create"), {"recipient": self.prof.pk, "subject": "Horaire", "body": "Jeudi ?"})
        message = Message.objects.get()
        self.assertEqual((message.sender, message.recipient, message.university, message.read_at), (self.student, self.prof, self.uni, None))

        self.login(self.prof)
        self.assertEqual(self.client.get(reverse("community:prof_messages")).context["unread"], 1)
        self.client.get(reverse("community:message_detail", args=[message.pk]))
        message.refresh_from_db()
        self.assertIsNotNone(message.read_at)

        self.client.post(reverse("community:message_delete", args=[message.pk]))
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())  # encore dans la boîte de l'expéditeur
        self.login(self.student).post(reverse("community:message_delete", args=[message.pk]))
        self.assertFalse(Message.objects.filter(pk=message.pk).exists())

    def test_third_party_cannot_read_a_message(self):
        message = Message.objects.create(university=self.uni, sender=self.student, recipient=self.prof, subject="Privé", body="…")
        for user in (self.classmate, self.admin, self.stranger):
            self.assertEqual(self.login(user).get(reverse("community:message_detail", args=[message.pk])).status_code, 404)

    def test_can_only_write_to_members_of_the_same_university(self):
        response = self.login(self.student).post(reverse("community:message_create"), {
            "recipient": self.stranger.pk, "subject": "Hors université", "body": "…"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.exists())

    def test_cannot_write_to_oneself(self):
        self.login(self.student).post(reverse("community:message_create"), {"recipient": self.student.pk, "subject": "Moi", "body": "…"})
        self.assertFalse(Message.objects.exists())

    def test_folders_and_search(self):
        Message.objects.create(university=self.uni, sender=self.student, recipient=self.prof, subject="Alpha", body="…")
        Message.objects.create(university=self.uni, sender=self.prof, recipient=self.student, subject="Bêta", body="…")
        client = self.login(self.student)
        self.assertEqual([m.subject for m in client.get(reverse("community:student_messages")).context["page"]], ["Bêta"])
        self.assertEqual([m.subject for m in client.get(reverse("community:student_messages"), {"dossier": "envoyes"}).context["page"]], ["Alpha"])
        self.assertEqual(list(client.get(reverse("community:student_messages"), {"q": "zzz"}).context["page"]), [])


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
