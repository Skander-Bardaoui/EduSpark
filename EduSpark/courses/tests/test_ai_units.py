"""Tests unitaires du pipeline IA (courses.services.ai) : lecture des supports,
validation du plan, rédacteurs Gemini / Groq / Anthropic, limite d'appels.

Aucun appel réseau : HTTP et SDK sont simulés.
"""

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx2
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from courses.services import ai

from .test_ai import AI_SETTINGS, api_message, fake_client, gemini_response, groq_response

CHAPTER = {"title": "Graphes", "objectives": ["Définir un graphe", "Parcourir"], "duration_hours": 3}


class TempDirMixin:
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="eduspark-ai-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Lecture des supports
# ---------------------------------------------------------------------------

class ExtractTextTests(TempDirMixin, SimpleTestCase):
    def test_pdf_text_is_extracted(self):
        from reportlab.pdfgen import canvas

        path = self.tmp / "cours.pdf"
        pdf = canvas.Canvas(str(path))
        pdf.drawString(72, 720, "Parcours en largeur des graphes")
        pdf.showPage()
        pdf.drawString(72, 720, "Algorithme de Dijkstra")
        pdf.save()
        text = ai.extract_text(path)
        self.assertIn("Parcours en largeur des graphes", text)
        self.assertIn("Algorithme de Dijkstra", text)

    def test_pdf_reading_stops_after_the_page_limit(self):
        from reportlab.pdfgen import canvas

        path = self.tmp / "long.pdf"
        pdf = canvas.Canvas(str(path))
        for number in range(1, 5):
            pdf.drawString(72, 720, "Page numero %d" % number)
            pdf.showPage()
        pdf.save()
        with mock.patch.object(ai, "MAX_PDF_PAGES", 2):
            text = ai.extract_text(path)
        self.assertIn("Page numero 2", text)
        self.assertNotIn("Page numero 3", text)

    def test_pptx_text_is_extracted_from_text_frames_only(self):
        from pptx import Presentation
        from pptx.util import Inches

        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[5])
        slide.shapes.title.text = "Architecture en couches"
        box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
        box.text_frame.text = "Inversion de dépendances"
        slide.shapes.add_connector(1, Inches(1), Inches(4), Inches(3), Inches(4))  # sans text_frame
        path = self.tmp / "slides.pptx"
        deck.save(str(path))
        text = ai.extract_text(path)
        self.assertIn("Architecture en couches", text)
        self.assertIn("Inversion de dépendances", text)

    def test_docx_text_is_read_from_the_xml(self):
        path = self.tmp / "fiche.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<w:document><w:body><w:p><w:r><w:t>Jointures SQL</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Sous-requêtes</w:t></w:r></w:p></w:body></w:document>',
            )
        self.assertEqual(ai.extract_text(path).split(), ["Jointures", "SQL", "Sous-requêtes"])

    def test_unknown_types_and_corrupted_files_give_empty_text(self):
        for name, content in (("video.mp4", b"x"), ("notes.txt", b"texte"), ("casse.pdf", b"pas un pdf"),
                              ("casse.pptx", b"pas un zip"), ("casse.docx", b"pas un zip"),
                              ("MAJUSCULES.DOCX", b"pas un zip")):
            with self.subTest(name=name):
                path = self.tmp / name
                path.write_bytes(content)
                self.assertEqual(ai.extract_text(path), "")

    def test_docx_without_document_xml_is_ignored(self):
        path = self.tmp / "vide.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("autre.xml", "<x/>")
        with self.assertLogs("courses.services.ai", "WARNING") as logs:
            self.assertEqual(ai.extract_text(path), "")
        self.assertIn("KeyError", logs.output[0])


class ExcerptTests(SimpleTestCase):
    def test_useful_lines_drop_short_numeric_and_repeated_lines(self):
        text = "  Page   1  \n12\nab\nGraphes orientés\nGRAPHES ORIENTÉS\nArbres   couvrants\n"
        self.assertEqual(list(ai._useful_lines(text)), ["Page 1", "Graphes orientés", "Arbres couvrants"])

    def test_empty_documents_give_an_empty_excerpt(self):
        self.assertEqual(ai.build_excerpt([]), "")
        self.assertEqual(ai.build_excerpt([("Vide", "12\n\n ab ")]), "")

    def test_each_document_gets_a_share_of_at_least_400_characters(self):
        documents = [("Doc %d" % i, "x" * 2000) for i in range(10)]
        excerpt = ai.build_excerpt(documents, limit=1000)
        self.assertEqual(len(excerpt), 1000)
        self.assertTrue(excerpt.startswith("### Doc 0\n" + "x" * 400))

    @override_settings(AI_LOCAL_TEXT_LIMIT=50)
    def test_default_limit_comes_from_settings(self):
        self.assertEqual(len(ai.build_excerpt([("Doc", "y" * 500)])), 50)

    def test_json_object_strips_reasoning_and_surrounding_text(self):
        self.assertEqual(ai._json_object('<think>je réfléchis {x}</think>Voici : {"a": 1} fin'), '{"a": 1}')
        self.assertEqual(ai._json_object("aucun objet"), "aucun objet")


class CourseDocumentsTests(SimpleTestCase):
    def material(self, name, path=None, error=None, original=None):
        file = mock.Mock()
        file.name = name
        if error:
            type(file).path = mock.PropertyMock(side_effect=error)
        else:
            type(file).path = mock.PropertyMock(return_value=path or "/tmp/" + name)
        return SimpleNamespace(original_name=original if original is not None else name, file=file, title=name)

    def test_only_readable_materials_with_text_are_returned(self):
        materials = [
            self.material("cours.pdf"),
            self.material("video.mp4"),
            self.material("distant.pptx", error=NotImplementedError()),
            self.material("sans-fichier.docx", error=ValueError()),
            self.material("vide.docx"),
            self.material("stockage.pdf", original=""),  # nom d'origine absent : nom du fichier
        ]
        texts = {"/tmp/cours.pdf": "Dijkstra", "/tmp/vide.docx": "   ", "/tmp/stockage.pdf": "Prim"}
        queryset = mock.Mock()
        queryset.order_by.return_value = materials
        with mock.patch("courses.models.CourseMaterial.objects.filter", return_value=queryset) as filter_, \
                mock.patch.object(ai, "extract_text", side_effect=lambda path: texts.get(path, "")):
            documents = ai.course_documents(7)
        filter_.assert_called_once_with(course_id=7)
        self.assertEqual(documents, [("cours.pdf", "Dijkstra"), ("stockage.pdf", "Prim")])

    def test_materials_fingerprint_is_empty_without_course(self):
        self.assertEqual(ai._materials_fingerprint(None), [])


# ---------------------------------------------------------------------------
# Validation du plan et consigne du rédacteur
# ---------------------------------------------------------------------------

class ValidateSyllabusUnitTests(SimpleTestCase):
    def test_too_many_chapters_are_refused(self):
        with self.assertRaisesMessage(ai.SyllabusInvalid, "Trop de chapitres"):
            ai.validate_syllabus({"chapters": [CHAPTER] * (ai.MAX_CHAPTERS + 1)})

    def test_chapter_must_be_an_object(self):
        with self.assertRaisesMessage(ai.SyllabusInvalid, "Chapitre 2 : objet attendu"):
            ai.validate_syllabus({"chapters": [CHAPTER, "Graphes"]})

    def test_objectives_and_title_are_cleaned_and_capped(self):
        chapter = dict(CHAPTER, title="  Titre " + "x" * 300, objectives=["  a  b ", " "] + ["o"] * 20)
        cleaned = ai.validate_syllabus({"chapters": [chapter]})[0]
        self.assertEqual(len(cleaned["title"]), 200)
        self.assertEqual(cleaned["objectives"][0], "a b")
        self.assertEqual(len(cleaned["objectives"]), ai.MAX_OBJECTIVES)


class WriterPromptTests(SimpleTestCase):
    def test_prompt_with_every_option(self):
        prompt = ai.build_writer_prompt(
            "Graphes", "L3", ["Parcours", "Dijkstra"],
            {"chapter_count": 5, "total_hours": 24, "language": "en", "style": "pratique"},
        )
        for expected in ("Titre du cours : Graphes", "Niveau : L3", "exactement 5", "24 heures",
                         "plutôt pratique", "Langue de rédaction : anglais", "- Parcours", "- Dijkstra"):
            self.assertIn(expected, prompt)

    def test_prompt_without_level_topics_or_options(self):
        prompt = ai.build_writer_prompt("Graphes", "", [], None)
        self.assertNotIn("Niveau", prompt)
        self.assertNotIn("exactement", prompt)
        self.assertIn("Aucun support analysé", prompt)
        self.assertIn("équilibré", prompt)
        self.assertIn("Langue de rédaction : français", prompt)

    def test_unknown_style_and_language_fall_back(self):
        prompt = ai.build_writer_prompt("Graphes", "L3", [], {"style": "inconnu", "language": "xx"})
        self.assertIn("équilibré", prompt)
        self.assertIn("français", prompt)


# ---------------------------------------------------------------------------
# Rédacteurs
# ---------------------------------------------------------------------------

@override_settings(**dict(AI_SETTINGS, AI_PROVIDER="gemini"))
class GeminiWriterTests(SimpleTestCase):
    def write(self, response):
        with mock.patch("courses.services.ai.requests.post", return_value=response) as post:
            text = ai.get_writer()("prompt")
        self.assertEqual(post.call_args.kwargs["headers"], {"x-goog-api-key": "gemini-test-key"})
        self.assertNotIn("gemini-test-key", post.call_args.args[0])  # jamais dans l'URL
        return text

    def test_thought_parts_are_ignored(self):
        self.assertEqual(json.loads(self.write(gemini_response({"chapters": [CHAPTER]}))), {"chapters": [CHAPTER]})

    def test_unreadable_body_is_invalid(self):
        response = mock.Mock(status_code=200, text="")
        response.json.side_effect = ValueError("pas du json")
        with self.assertRaisesMessage(ai.SyllabusInvalid, "Réponse Gemini illisible"):
            self.write(response)

    def test_no_candidate_or_blocked_answer_is_unavailable(self):
        empty = mock.Mock(status_code=200, text="")
        empty.json.return_value = {"candidates": []}
        for response, message in ((empty, "aucune réponse"),
                                  (gemini_response({}, finish="SAFETY"), "bloqué la réponse"),
                                  (gemini_response(blocked=True), "bloqué la demande")):
            with self.subTest(message=message), self.assertRaisesMessage(ai.AIUnavailable, message):
                self.write(response)

    def test_truncated_answer_is_invalid(self):
        with self.assertRaisesMessage(ai.SyllabusInvalid, "tronquée"):
            self.write(gemini_response({}, finish="MAX_TOKENS"))

    def test_http_errors(self):
        cases = (
            (mock.Mock(status_code=400, text="API_KEY_INVALID"), "Clé API Gemini refusée"),
            (mock.Mock(status_code=429, text=""), "Quota"),
            (mock.Mock(status_code=500, text=""), "renvoyé une erreur"),
        )
        for response, message in cases:
            with self.subTest(status=response.status_code), self.assertRaisesMessage(ai.AIUnavailable, message):
                self.write(response)

    def test_network_errors(self):
        import requests

        for error, message in ((requests.Timeout(), "Délai"), (requests.ConnectionError(), "injoignable")):
            with self.subTest(message=message), \
                    mock.patch("courses.services.ai.requests.post", side_effect=error), \
                    self.assertRaisesMessage(ai.AIUnavailable, message):
                ai.get_writer()("prompt")

    @override_settings(GEMINI_API_KEY="")
    def test_missing_key(self):
        with self.assertRaisesMessage(ai.AIUnavailable, "GEMINI_API_KEY"):
            ai.get_writer()


@override_settings(**dict(AI_SETTINGS, AI_PROVIDER="groq"))
class GroqWriterTests(SimpleTestCase):
    def write(self, *responses):
        with mock.patch("courses.services.ai.requests.post", side_effect=list(responses)) as post:
            text = ai.get_writer()("prompt")
        return text, post

    def test_bearer_key_and_json_mode(self):
        text, post = self.write(groq_response({"chapters": [CHAPTER]}))
        self.assertEqual(json.loads(text), {"chapters": [CHAPTER]})
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer groq-test-key")
        self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})

    def test_model_without_json_mode_is_retried_without_it(self):
        refused = mock.Mock(status_code=400, text="response_format not supported")
        text, post = self.write(refused, groq_response(text='Voici le plan : {"chapters": []}'))
        self.assertEqual(text, '{"chapters": []}')
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("response_format", post.call_args_list[1].kwargs["json"])

    def test_unreadable_or_truncated_answers_are_invalid(self):
        unreadable = mock.Mock(status_code=200, text="")
        unreadable.json.return_value = {"choices": []}
        for response, message in ((unreadable, "illisible"), (groq_response({}, finish="length"), "tronquée"),
                                  (mock.Mock(status_code=400, text="json_validate_failed"), "JSON refusé")):
            with self.subTest(message=message), self.assertRaisesMessage(ai.SyllabusInvalid, message):
                self.write(response)

    def test_http_and_network_errors(self):
        import requests

        cases = ((mock.Mock(status_code=401, text=""), "refusée"), (mock.Mock(status_code=429, text=""), "Quota"),
                 (mock.Mock(status_code=502, text=""), "renvoyé une erreur"), (requests.Timeout(), "Délai"),
                 (requests.ConnectionError(), "injoignable"))
        for response, message in cases:
            with self.subTest(message=message), self.assertRaisesMessage(ai.AIUnavailable, message):
                self.write(response)

    def test_null_content_becomes_empty_text(self):
        response = mock.Mock(status_code=200, text="")
        response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": None}}]}
        self.assertEqual(self.write(response)[0], "")

    @override_settings(COURSES_GROQ_API_KEY="")
    def test_missing_key(self):
        with self.assertRaisesMessage(ai.AIUnavailable, "COURSES_GROQ_API_KEY"):
            ai.get_writer()


@override_settings(**AI_SETTINGS)
class AnthropicWriterTests(SimpleTestCase):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def status_error(self, cls, status):
        return cls("erreur", response=httpx2.Response(status, request=self.request), body=None)

    def test_errors_become_unavailable(self):
        cases = (
            (self.status_error(anthropic.AuthenticationError, 401), "Clé API refusée"),
            (self.status_error(anthropic.RateLimitError, 429), "Quota"),
            (self.status_error(anthropic.InternalServerError, 500), "renvoyé une erreur"),
            (anthropic.APIConnectionError(request=self.request), "injoignable"),
        )
        for error, message in cases:
            with self.subTest(message=message), self.assertRaisesMessage(ai.AIUnavailable, message):
                ai._call_writer(fake_client(error), "prompt")

    def test_refusal_and_truncation(self):
        with self.assertRaisesMessage(ai.AIUnavailable, "décliné"):
            ai._call_writer(fake_client(api_message("", stop_reason="refusal")), "prompt")
        with self.assertRaisesMessage(ai.SyllabusInvalid, "tronquée"):
            ai._call_writer(fake_client(api_message("{", stop_reason="max_tokens")), "prompt")

    def test_fallbacks_use_the_beta_endpoint(self):
        client = fake_client(api_message({"chapters": [CHAPTER]}))
        ai._call_writer(client, "prompt")
        kwargs = client.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertEqual(kwargs["output_config"]["format"]["type"], "json_schema")
        client.messages.create.assert_not_called()

    @override_settings(ANTHROPIC_FALLBACKS=False)
    def test_without_fallbacks_the_standard_endpoint_is_used(self):
        client = fake_client(api_message({"chapters": [CHAPTER]}))
        text = ai._call_writer(client, "prompt")
        self.assertEqual(json.loads(text), {"chapters": [CHAPTER]})
        client.beta.messages.create.assert_not_called()

    def test_client_is_built_from_settings(self):
        with mock.patch("anthropic.Anthropic") as constructor:
            ai._anthropic_client()
        constructor.assert_called_once_with(api_key="test-key", timeout=60, max_retries=1)

    def test_writer_model_name_per_provider(self):
        for provider, expected in (("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-2.5-flash"),
                                   ("anthropic", "claude-sonnet-5-5"), ("fake", "fake")):
            with self.subTest(provider=provider), override_settings(AI_PROVIDER=provider):
                self.assertEqual(ai._writer_model(), expected)


# ---------------------------------------------------------------------------
# Limite d'appels et orchestration
# ---------------------------------------------------------------------------

@override_settings(**AI_SETTINGS)
class RateLimitUnitTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_anonymous_or_disabled_limit_is_never_counted(self):
        ai.check_rate_limit(None)
        with override_settings(AI_RATE_LIMIT_PER_HOUR=0):
            for _ in range(20):
                ai.check_rate_limit(1)

    def test_limit_is_reached_after_n_calls(self):
        with override_settings(AI_RATE_LIMIT_PER_HOUR=2):
            ai.check_rate_limit(5)
            ai.check_rate_limit(5)
            with self.assertRaisesMessage(ai.RateLimitExceeded, "Limite de 2"):
                ai.check_rate_limit(5)
            ai.check_rate_limit(6)  # autre utilisateur, autre compteur

    def test_counter_expired_between_add_and_incr(self):
        with mock.patch.object(ai.cache, "incr", side_effect=ValueError), \
                mock.patch.object(ai.cache, "set") as set_:
            ai.check_rate_limit(9)
        set_.assert_called_once()

    @override_settings(AI_PROVIDER="inconnu")
    def test_unknown_provider_is_unavailable(self):
        with self.assertRaisesMessage(ai.AIUnavailable, "AI_PROVIDER inconnu"):
            ai.generate_syllabus("Graphes", "L3")

    @override_settings(AI_PROVIDER="fake")
    def test_cached_result_is_returned_without_new_count(self):
        first = ai.generate_syllabus("Graphes", "L3", user_id=3)
        with mock.patch.object(ai, "check_rate_limit") as check:
            second = ai.generate_syllabus("  Graphes ", "L3 ", user_id=3)
        check.assert_not_called()
        self.assertEqual(first, second)
        self.assertEqual(second["mode"], ai.MODE_API_ONLY)
        self.assertEqual(second["local_status"], ai.LOCAL_NO_MATERIALS)


class LocalReaderUnitTests(SimpleTestCase):
    @override_settings(**AI_SETTINGS)
    def test_unreadable_answer_shapes(self):
        import requests

        bad_json = mock.Mock()
        bad_json.json.return_value = {"message": {"content": "pas du json"}}
        no_message = mock.Mock()
        no_message.json.return_value = {}
        http_error = mock.Mock()
        http_error.raise_for_status.side_effect = requests.HTTPError("500")
        cases = ((bad_json, "illisible"), (no_message, "illisible"), (http_error, "injoignable"),
                 (requests.Timeout(), "Délai"))
        for answer, message in cases:
            kwargs = {"side_effect": answer} if isinstance(answer, Exception) else {"return_value": answer}
            with self.subTest(message=message), mock.patch("courses.services.ai.requests.post", **kwargs), \
                    self.assertRaisesMessage(ai.LocalUnavailable, message):
                ai.local_extract_topics("texte")

    def test_unknown_language_falls_back_to_french(self):
        answer = mock.Mock()
        answer.json.return_value = {"message": {"content": json.dumps({"topics": ["Graphes"]})}}
        with override_settings(**AI_SETTINGS), \
                mock.patch("courses.services.ai.requests.post", return_value=answer) as post:
            ai.local_extract_topics("texte", "xx")
        self.assertIn("rédigés en français", post.call_args.kwargs["json"]["messages"][0]["content"])
        self.assertEqual(post.call_args.kwargs["json"]["keep_alive"], AI_SETTINGS.get("OLLAMA_KEEP_ALIVE", "30m"))

    def test_clean_topics_skip_non_strings_and_truncate(self):
        self.assertEqual(ai.clean_topics({"topics": [None, {"a": 1}, "x" * 200]}), ["x" * 120])
        with self.assertRaises(ai.LocalUnavailable):
            ai.clean_topics("pas un objet")
