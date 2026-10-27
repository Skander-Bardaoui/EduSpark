"""Métriques du plan de cours IA et commande d'évaluation (sans appel réseau)."""

import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from courses.services import ai
from courses.services import ai_metrics as m

SOURCE = "Parcours en largeur et en profondeur. Plus courts chemins : algorithme de Dijkstra. Graphes orientés."


class NormalizationTests(SimpleTestCase):
    def test_normalize_removes_accents_case_and_punctuation(self):
        self.assertEqual(m.normalize("  Complexité, É-té !"), "complexite e te")
        self.assertEqual(m.normalize(None), "")

    def test_significant_words_skip_short_words_and_stopwords(self):
        self.assertEqual(m.significant_words("Les graphes et la complexité des arbres"),
                         ["graphes", "complexite", "arbres"])


class TopicMetricsTests(SimpleTestCase):
    def test_grounded_topic_reuses_a_word_of_the_source(self):
        self.assertTrue(m.is_grounded("Parcours de graphes", SOURCE))
        self.assertTrue(m.is_grounded("Graphe orienté", SOURCE))  # singulier / pluriel
        self.assertFalse(m.is_grounded("Théorie des jeux", SOURCE))
        self.assertFalse(m.is_grounded("Le la", SOURCE))  # aucun mot significatif

    def test_precision_counts_invented_topics_as_errors(self):
        self.assertEqual(m.topic_precision(["Parcours", "Dijkstra", "Probabilités", "Jeux vidéo"], SOURCE), 0.5)
        self.assertEqual(m.topic_precision([], SOURCE), 0.0)

    def test_recall_matches_keywords_whatever_the_form(self):
        topics = ["Plus courts chemins (Dijkstra)", "Arbres couvrants minimaux"]
        self.assertTrue(m.keyword_found("dijkstra", topics))
        self.assertTrue(m.keyword_found("arbre couvrant", topics))
        self.assertFalse(m.keyword_found("flot", topics))
        self.assertFalse(m.keyword_found("", topics))
        self.assertEqual(m.topic_recall(topics, ["dijkstra", "arbre couvrant", "flot", "complexité"]), 0.5)
        self.assertIsNone(m.topic_recall(topics, []))

    def test_f1_is_the_harmonic_mean(self):
        self.assertAlmostEqual(m.f1(0.5, 1.0), 2 / 3)
        self.assertEqual(m.f1(0.0, 0.0), 0.0)
        self.assertIsNone(m.f1(0.8, None))
        self.assertIsNone(m.f1(None, 0.8))

    def test_language_compliance(self):
        self.assertTrue(m.in_language("Analyse statique", "fr"))
        self.assertTrue(m.in_language("Static analysis", "en"))
        self.assertTrue(m.in_language("التحليل الإحصائي", "ar"))
        self.assertFalse(m.in_language("测试和验证软件", "fr"))
        self.assertFalse(m.in_language("Analyse statique", "ar"))
        self.assertFalse(m.in_language("التحليل", "fr"))
        self.assertFalse(m.in_language("123", "fr"))
        self.assertEqual(m.language_compliance(["Graphes", "测试", "Arbres", "テスト"], "fr"), 0.5)
        self.assertEqual(m.language_compliance([], "fr"), 0.0)


class SyllabusChecksTests(SimpleTestCase):
    CHAPTERS = [
        {"title": "A", "objectives": ["x", "y"], "duration_hours": 6},
        {"title": "B", "objectives": ["x"], "duration_hours": 6},
        {"title": "C", "objectives": ["x", "y", "z", "t", "u"], "duration_hours": 8},
    ]

    def test_constraints_are_checked(self):
        checks = m.syllabus_checks(self.CHAPTERS, {"chapter_count": 3, "total_hours": 18})
        self.assertTrue(checks["chapter_count_ok"])
        self.assertAlmostEqual(checks["hours_error"], 2 / 18)
        self.assertAlmostEqual(checks["objectives_ok"], 1 / 3)

    def test_missing_options_are_not_penalised(self):
        checks = m.syllabus_checks(self.CHAPTERS, {})
        self.assertTrue(checks["chapter_count_ok"])
        self.assertIsNone(checks["hours_error"])
        self.assertFalse(m.syllabus_checks(self.CHAPTERS, {"chapter_count": 5})["chapter_count_ok"])
        self.assertEqual(m.syllabus_checks([], {})["objectives_ok"], 0.0)


class StatisticsTests(SimpleTestCase):
    def test_percentiles_and_latency_summary(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertEqual(m.percentile(values, 50), 5)
        self.assertEqual(m.percentile(values, 95), 10)
        self.assertIsNone(m.percentile([], 50))
        summary = m.latency_summary([2.0, None, 4.0])
        self.assertEqual(summary, {"n": 2, "mean": 3.0, "p50": 2.0, "p95": 4.0, "max": 4.0})
        self.assertEqual(m.latency_summary([])["n"], 0)

    def test_mean_and_rate_ignore_missing_values(self):
        self.assertEqual(m.mean([1, None, 3]), 2)
        self.assertIsNone(m.mean([None]))
        self.assertEqual(m.rate([True, False, True, True]), 0.75)
        self.assertIsNone(m.rate([]))


CASES = [
    {"id": "graphes", "title": "Graphes", "level": "L3", "language": "fr", "text": SOURCE,
     "keywords": ["dijkstra", "parcours", "flot"], "options": {"chapter_count": 2, "total_hours": 10}},
    {"id": "vide", "title": "Vide", "level": "L1", "language": "ar", "text": "x", "keywords": [],
     "options": {}},
]
PLAN = {"chapters": [
    {"title": "Parcours", "objectives": ["Définir", "Appliquer"], "duration_hours": 4},
    {"title": "Chemins", "objectives": ["Calculer", "Comparer"], "duration_hours": 6},
]}


@override_settings(AI_PROVIDER="groq", COURSES_GROQ_API_KEY="k", COURSES_GROQ_MODEL="modele-test")
class EvaluateCommandTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="eduspark-eval-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cases = self.tmp / "cases.json"
        self.cases.write_text(json.dumps(CASES), encoding="utf-8")
        self.report = self.tmp / "report.md"

    def run_command(self, **extra):
        out = StringIO()
        call_command("evaluate_ai", cases=str(self.cases), output=str(self.report), stdout=out, **extra)
        return out.getvalue()

    def test_report_contains_all_metrics(self):
        local = mock.Mock(side_effect=[["Parcours en largeur", "Dijkstra", "Probabilités"], ai.LocalUnavailable("lent")])
        writer = mock.Mock(side_effect=[json.dumps(PLAN), "pas du json"])
        with mock.patch.object(ai, "local_extract_topics", local), \
                mock.patch.object(ai, "get_writer", return_value=writer):
            output = self.run_command()
        self.assertIn("Rapport écrit", output)
        report = self.report.read_text(encoding="utf-8")
        for label in ("Précision", "Rappel", "F1", "JSON valide au premier essai", "Nombre de chapitres respecté",
                      "Latence moyenne / p50 / p95", "graphes", "vide"):
            self.assertIn(label, report)
        data = json.loads(self.report.with_suffix(".json").read_text(encoding="utf-8"))
        summary = data["summary"]
        self.assertEqual(summary["local"]["success_rate"], 0.5)
        self.assertAlmostEqual(summary["local"]["precision"], 2 / 3)
        self.assertAlmostEqual(summary["local"]["recall"], 2 / 3)
        self.assertEqual(summary["api"]["json_valid_first_try"], 0.5)
        self.assertEqual(summary["api"]["chapter_count_ok"], 1.0)
        self.assertEqual(summary["api"]["hours_error"], 0.0)
        self.assertEqual(summary["writer_model"], "modele-test")
        local.assert_any_call(SOURCE, "fr")

    def test_runs_and_skip_options(self):
        writer = mock.Mock(side_effect=ai.AIUnavailable("quota"))
        with mock.patch.object(ai, "local_extract_topics") as local, \
                mock.patch.object(ai, "get_writer", return_value=writer):
            self.run_command(runs=2, skip_local=True)
        local.assert_not_called()
        data = json.loads(self.report.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["rows"]), 4)
        self.assertEqual(data["summary"]["api"]["success_rate"], 0.0)
        self.assertEqual(data["summary"]["local"]["runs"], 0)

    def test_skip_api(self):
        with mock.patch.object(ai, "local_extract_topics", return_value=["Dijkstra"]), \
                mock.patch.object(ai, "get_writer") as get_writer:
            self.run_command(skip_api=True)
        get_writer.assert_not_called()

    def test_baseline_is_rescored_and_compared(self):
        self.cases.write_text(json.dumps(CASES[:1]), encoding="utf-8")
        baseline = self.tmp / "baseline.json"
        baseline.write_text(json.dumps({"rows": [
            {"case": "graphes", "run": 1, "local_ok": True, "topics": ["Parcours", "Probabilités"],
             "precision": 0.99, "recall": 0.99},
            {"case": "inconnu", "run": 1, "local_ok": True, "topics": []},
        ]}), encoding="utf-8")
        with mock.patch.object(ai, "local_extract_topics", return_value=["Parcours", "Dijkstra"]):
            self.run_command(skip_api=True, baseline=str(baseline))
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("### Avant / après (`baseline.json`)", report)
        # Avant : recalculé (1 thème sur 2 ancré, 1 notion sur 3) et non repris tel quel du fichier.
        self.assertIn("| Précision | 50 % | 100 % |", report)
        self.assertIn("| Rappel | 33 % | 67 % |", report)

    def test_unreadable_baseline_is_an_error(self):
        with mock.patch.object(ai, "local_extract_topics", return_value=["Dijkstra"]), \
                self.assertRaises(CommandError):
            self.run_command(skip_api=True, baseline=str(self.tmp / "absent.json"))

    def test_unreadable_case_file_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command("evaluate_ai", cases=str(self.tmp / "absent.json"), output=str(self.report))
