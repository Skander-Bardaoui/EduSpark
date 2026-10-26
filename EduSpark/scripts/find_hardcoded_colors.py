"""Liste les couleurs écrites en dur dans les templates et les feuilles de style.

Usage, depuis le dossier EduSpark/ :
    ..\\.venv\\Scripts\\python.exe scripts/find_hardcoded_colors.py [--module courses] [--all]

Cherche les hex, rgb()/rgba(), noms de couleurs CSS, classes de la palette
Tailwind par défaut (bg-white, text-gray-600…) et valeurs arbitraires
(bg-[#06164b]). Les définitions du thème (static/theme/theme.css) sont
ignorées. Par défaut, les cas connus et voulus (logos de marque, ombres
décoratives, pages hors thème) sont regroupés à part ; --all les détaille.
Code de sortie : toujours 0 (c'est un inventaire, pas un test).
"""

import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES = ("templates", "accounts", "courses", "exercises", "exams", "community", "coaching", "landing")
SKIP = {ROOT / "static" / "theme" / "theme.css"}

PALETTE = (r"(white|black|(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|"
           r"cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3})")
PATTERNS = {
    # Un hex suit une syntaxe CSS / de classe (« : #fff », « [#fff] », « "#fff" »), pas du texte (« Série #402 »).
    "hex": re.compile(r"(?<=[\s:(\[,\"'=])#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b(?![\w-])(?<!\s#\d{3})"),
    "rgb": re.compile(r"rgba?\(\s*\d"),
    "tailwind": re.compile(r"(?<![\w-])(?:[a-z-]+:)*(?:bg|text|border|ring|from|via|to|fill|stroke|divide|outline|"
                           r"shadow|decoration|placeholder|accent|caret)-" + PALETTE + r"(?:/\d+)?\b"),
    "arbitraire": re.compile(r"-\[(?:#|rgba?\((?!var\())[^\]]*\]"),
    "nom CSS": re.compile(r"(?:color|background(?:-color)?)\s*:\s*(?:white|black|red|green|blue|gray|grey)\b"),
}

# Cas voulus : couleurs de marque, pages hors thème, ombres décoratives.
KNOWN = [
    (re.compile(r"accounts/(auth|password_reset_\w+)\.html$"), None, "page hors thème (voir README)"),
    (re.compile(r"landing/"), None, "page vitrine hors thème (voir README)"),
    (re.compile(r"accounts/(login|signup)\.html$"), re.compile(r"#(4285F4|34A853|FBBC05|EA4335|F35325|81BC06|05A6F0|FFBA08)", re.I), "logo Google / Microsoft"),
    (re.compile(r"accounts/(login|signup)\.html$"), re.compile(r"shadow-\[|border-white|ring-white|from-\[#06164b\]|via-\[#06164b\]|to-\[#06164b\]"), "panneau photo (zone toujours claire)"),
    (re.compile(r"\.html$"), re.compile(r"shadow-\[[^\]]*rgba?\("), "ombre décorative"),
    (re.compile(r"courses/material_view\.html$"), re.compile(r"bg-black"), "bandes noires du lecteur vidéo"),
    (re.compile(r"portal/_a11y_icon\.html$"), None, "symbole d'accessibilité (couleurs imposées)"),
    (re.compile(r"portal/_a11y_head\.html$"), re.compile(r"#ffbf00|rgb\(0"), "focus renforcé jaune (accessibilité)"),
]


def files():
    for module in MODULES:
        base = ROOT / module
        for path in sorted(base.rglob("*")):
            if path.suffix in (".html", ".css", ".js") and path not in SKIP and "/probe/" not in path.as_posix():
                yield module, path


def known_reason(rel, match):
    for path_re, match_re, reason in KNOWN:
        if path_re.search(rel) and (match_re is None or match_re.search(match)):
            return reason
    return None


def main(argv):
    only = argv[argv.index("--module") + 1] if "--module" in argv else None
    show_all = "--all" in argv
    found = defaultdict(list)
    known = defaultdict(int)
    for module, path in files():
        if only and module != only:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            for kind, pattern in PATTERNS.items():
                for m in pattern.finditer(line):
                    reason = known_reason(rel, line[max(0, m.start() - 40):m.end() + 40])
                    if reason and not show_all:
                        known[(module, reason)] += 1
                        continue
                    found[module].append(f"  {rel}:{number}  [{kind}] {m.group(0)}" + (f"  ({reason})" if reason else ""))

    total = 0
    for module in MODULES:
        if found.get(module):
            print(f"\n== {module} ({len(found[module])})")
            print("\n".join(found[module]))
            total += len(found[module])
    if known:
        print("\n== cas connus et voulus (--all pour le détail)")
        for (module, reason), count in sorted(known.items()):
            print(f"  {module:10} {count:4}  {reason}")
    print(f"\n{total} couleur(s) en dur à examiner.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
