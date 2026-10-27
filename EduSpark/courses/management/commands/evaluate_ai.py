"""Évalue le plan de cours IA sur un jeu de cas fixe et écrit un rapport.

    ..\\.venv\\Scripts\\python.exe manage.py evaluate_ai --runs 2

Jeu de cas : courses/evaluation/cases.json (texte de support, notions de
référence annotées à la main, langue et consignes demandées). Les deux étapes
sont mesurées séparément, avec les vrais modèles configurés dans .env :

* lecteur local (Ollama) : précision, rappel, F1, conformité de langue,
  taux d'échec, latence ;
* rédacteur (API) : JSON valide au premier essai, nombre de chapitres
  respecté, écart au volume horaire, objectifs par chapitre, latence.

Rapport : courses/evaluation/report.md (+ report.json pour les données brutes).
Aucune écriture en base ; le cache des plans n'est pas utilisé.
"""

import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from courses.services import ai
from courses.services import ai_metrics as m

EVALUATION_DIR = Path(__file__).resolve().parents[2] / "evaluation"


def _fmt(value, pct=False, digits=2):
    if value is None:
        return "—"
    return ("%.0f %%" % (value * 100)) if pct else ("%.*f" % (digits, value))


class Command(BaseCommand):
    help = "Évalue le pipeline IA du plan de cours (métriques et temps de réponse)."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=1, help="Répétitions de chaque cas (défaut : 1).")
        parser.add_argument("--cases", default=str(EVALUATION_DIR / "cases.json"))
        parser.add_argument("--output", default=str(EVALUATION_DIR / "report.md"))
        parser.add_argument("--skip-local", action="store_true", help="Ne pas évaluer le lecteur local.")
        parser.add_argument("--skip-api", action="store_true", help="Ne pas évaluer le rédacteur API.")
        parser.add_argument(
            "--baseline", default=None,
            help="Rapport JSON d'une version précédente (ex. courses/evaluation/baseline_v1.json) : "
                 "ajoute une comparaison avant / après, recalculée avec les mêmes règles.",
        )

    def handle(self, *args, **options):
        try:
            cases = json.loads(Path(options["cases"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CommandError("Jeu de cas illisible : %s" % error)
        runs = max(1, options["runs"])
        rows = []
        for case in cases:
            for run in range(1, runs + 1):
                self.stdout.write("· %s (essai %d/%d)" % (case["id"], run, runs))
                row = {"case": case["id"], "language": case["language"], "run": run}
                topics = []
                if not options["skip_local"]:
                    topics = self.evaluate_local(case, row)
                if not options["skip_api"]:
                    self.evaluate_writer(case, topics, row)
                rows.append(row)
        summary = self.summarize(rows)
        baseline = self.load_baseline(options["baseline"], cases) if options["baseline"] else None
        output = Path(options["output"])
        output.write_text(self.render(summary, rows, runs, len(cases), baseline), encoding="utf-8")
        output.with_suffix(".json").write_text(
            json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS("Rapport écrit : %s" % output))

    # -- Étapes ------------------------------------------------------------------
    def evaluate_local(self, case, row):
        started = time.monotonic()
        try:
            topics = ai.local_extract_topics(case["text"], case["language"])
        except ai.LocalUnavailable as error:
            row.update(local_ok=False, local_error=str(error), local_latency=time.monotonic() - started)
            return []
        row.update(local_ok=True, local_latency=time.monotonic() - started, topics=topics,
                   **self.local_metrics(case, topics))
        return topics

    @staticmethod
    def local_metrics(case, topics):
        # Thèmes traduits (support dans une autre langue) : ils ne peuvent pas
        # reprendre les mots du texte, la précision n'a pas de sens.
        translated = case.get("source_language", case["language"]) != case["language"]
        precision = None if translated else m.topic_precision(topics, case["text"])
        recall = m.topic_recall(topics, case.get("keywords") or [])
        return {
            "precision": precision,
            "recall": recall,
            "f1": m.f1(precision, recall),
            "language_ok": m.language_compliance(topics, case["language"]),
        }

    def load_baseline(self, path, cases):
        """Synthèse d'un ancien rapport, métriques recalculées sur ses thèmes avec les règles actuelles."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CommandError("Rapport de référence illisible : %s" % error)
        by_id = {case["id"]: case for case in cases}
        rows = []
        for row in data.get("rows", []):
            case = by_id.get(row.get("case"))
            if case is not None and row.get("local_ok"):
                row = dict(row, **self.local_metrics(case, row.get("topics") or []))
            rows.append(row)
        return {"path": str(path), "summary": self.summarize(rows)}

    def evaluate_writer(self, case, topics, row):
        options = dict(case.get("options") or {}, language=case["language"])
        prompt = ai.build_writer_prompt(case["title"], case["level"], topics, options)
        started = time.monotonic()
        try:
            raw = ai.get_writer()(prompt)
        except ai.AIUnavailable as error:
            row.update(api_ok=False, api_error=str(error), api_latency=time.monotonic() - started)
            return
        row["api_latency"] = time.monotonic() - started
        try:
            chapters = ai.validate_syllabus(json.loads(raw))
        except (ValueError, ai.SyllabusInvalid) as error:
            row.update(api_ok=True, json_valid=False, api_error=str(error))
            return
        row.update(api_ok=True, json_valid=True, chapters=len(chapters), **m.syllabus_checks(chapters, options))

    # -- Synthèse ----------------------------------------------------------------
    def summarize(self, rows):
        local = [row for row in rows if "local_ok" in row]
        local_ok = [row for row in local if row["local_ok"]]
        api = [row for row in rows if "api_ok" in row]
        valid = [row for row in api if row.get("json_valid")]
        return {
            "provider": settings.AI_PROVIDER,
            "writer_model": ai._writer_model(),
            "local_model": settings.OLLAMA_MODEL,
            "local": {
                "runs": len(local),
                "success_rate": m.rate(row["local_ok"] for row in local),
                "precision": m.mean(row.get("precision") for row in local_ok),
                "recall": m.mean(row.get("recall") for row in local_ok),
                "f1": m.mean(row.get("f1") for row in local_ok),
                "language_ok": m.mean(row.get("language_ok") for row in local_ok),
                "latency": m.latency_summary(row.get("local_latency") for row in local),
            },
            "api": {
                "runs": len(api),
                "success_rate": m.rate(row["api_ok"] for row in api),
                "json_valid_first_try": m.rate(row.get("json_valid") for row in api if row["api_ok"]),
                "chapter_count_ok": m.rate(row["chapter_count_ok"] for row in valid),
                "hours_error": m.mean(row["hours_error"] for row in valid),
                "objectives_ok": m.mean(row["objectives_ok"] for row in valid),
                "latency": m.latency_summary(row.get("api_latency") for row in api),
            },
        }

    def render(self, summary, rows, runs, case_count, baseline=None):
        local, api = summary["local"], summary["api"]
        lat_l, lat_a = local["latency"], api["latency"]
        lines = [
            "# Évaluation du plan de cours IA",
            "",
            "Généré par `python manage.py evaluate_ai --runs %d` le %s." % (runs, time.strftime("%d/%m/%Y à %H:%M")),
            "",
            "- Jeu d'évaluation : %d cas (`courses/evaluation/cases.json`) × %d essai(s)" % (case_count, runs),
            "- Lecteur local : `%s` (Ollama) · Rédacteur : `%s` (%s)" % (
                summary["local_model"], summary["writer_model"], summary["provider"]),
            "",
            "## Lecteur local (extraction des thèmes)",
            "",
            "| Métrique | Valeur |",
            "|---|---|",
            "| Réponses exploitables | %s |" % _fmt(local["success_rate"], pct=True),
            "| Précision (thèmes ancrés dans le support) | %s |" % _fmt(local["precision"], pct=True),
            "| Rappel (notions de référence retrouvées) | %s |" % _fmt(local["recall"], pct=True),
            "| F1 | %s |" % _fmt(local["f1"]),
            "| Thèmes dans la langue demandée | %s |" % _fmt(local["language_ok"], pct=True),
            "| Latence moyenne / p50 / p95 (s) | %s / %s / %s |" % (
                _fmt(lat_l["mean"], digits=1), _fmt(lat_l["p50"], digits=1), _fmt(lat_l["p95"], digits=1)),
            "",
        ]
        if baseline:
            before = baseline["summary"]["local"]
            lines += [
                "### Avant / après (`%s`)" % Path(baseline["path"]).name,
                "",
                "Même jeu de cas, mêmes règles de calcul ; seule la consigne du lecteur local a changé",
                "(couvrir l'ensemble du document en regroupant les notions proches).",
                "",
                "| Métrique | Avant | Après |",
                "|---|---|---|",
            ]
            for label, key, pct in (("Précision", "precision", True), ("Rappel", "recall", True),
                                    ("F1", "f1", False), ("Langue demandée", "language_ok", True)):
                lines.append("| %s | %s | %s |" % (label, _fmt(before[key], pct=pct), _fmt(local[key], pct=pct)))
            lines.append("")
        lines += [
            "## Rédacteur (plan JSON)",
            "",
            "| Métrique | Valeur |",
            "|---|---|",
            "| Appels réussis | %s |" % _fmt(api["success_rate"], pct=True),
            "| JSON valide au premier essai | %s |" % _fmt(api["json_valid_first_try"], pct=True),
            "| Nombre de chapitres respecté | %s |" % _fmt(api["chapter_count_ok"], pct=True),
            "| Écart moyen au volume horaire demandé | %s |" % _fmt(api["hours_error"], pct=True),
            "| Chapitres avec 2 à 4 objectifs | %s |" % _fmt(api["objectives_ok"], pct=True),
            "| Latence moyenne / p50 / p95 (s) | %s / %s / %s |" % (
                _fmt(lat_a["mean"], digits=1), _fmt(lat_a["p50"], digits=1), _fmt(lat_a["p95"], digits=1)),
            "",
            "## Détail par cas",
            "",
            "| Cas | Langue | Essai | Précision | Rappel | F1 | Langue OK | Lecture (s) | JSON | Chapitres OK | Écart heures | Rédaction (s) |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            lines.append("| %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                row["case"], row["language"], row["run"],
                _fmt(row.get("precision"), pct=True), _fmt(row.get("recall"), pct=True), _fmt(row.get("f1")),
                _fmt(row.get("language_ok"), pct=True), _fmt(row.get("local_latency"), digits=1),
                {True: "oui", False: "non"}.get(row.get("json_valid"), "—"),
                {True: "oui", False: "non"}.get(row.get("chapter_count_ok"), "—"),
                _fmt(row.get("hours_error"), pct=True), _fmt(row.get("api_latency"), digits=1),
            ))
        lines += [
            "",
            "## Lecture des métriques",
            "",
            "- **Précision** : un thème est compté juste s'il reprend au moins un mot significatif du support ;",
            "  un thème inventé (hors du texte) la fait baisser.",
            "- **Rappel** : part des notions annotées à la main (champ `keywords`) retrouvées dans les thèmes.",
            "- Cas traduits (`source_language` différente de la langue demandée : support anglais pour un plan",
            "  en français, plan en arabe) : précision et F1 non calculées, seuls rappel et langue comptent.",
            "- **Langue** : un thème en chinois, japonais ou coréen, ou dans le mauvais alphabet, est non conforme.",
            "- Les temps sont mesurés de bout en bout pour chaque étape (réseau compris). La génération tourne en",
            "  tâche de fond (`courses/services/jobs.py`) : la page n'est jamais bloquée pendant ce temps.",
            "",
        ]
        return "\n".join(lines)
