"""Contrôle WCAG AA des tokens du thème (clair et sombre).

Usage, depuis le dossier EduSpark/ :
    ..\\.venv\\Scripts\\python.exe scripts/check_contrast.py [--markdown]

Lit static/theme/theme.css, calcule le ratio de chaque paire fond / texte
utilisée par les templates et échoue (code 1) si une paire du thème sombre,
ou une paire nouvelle du thème clair, est sous le seuil. Les écarts du thème
clair qui existaient avant le thème (et qu'on ne modifie pas, pour ne pas
changer le rendu actuel) sont signalés sans faire échouer le contrôle.
"""

import pathlib
import re
import sys

THEME_CSS = pathlib.Path(__file__).resolve().parent.parent / "static" / "theme" / "theme.css"

TEXT, UI = 4.5, 3.0

# (texte, fond, seuil) — noms des tokens sans le préfixe --md-.
SURFACES = ("background", "surface-container-low", "surface-container-lowest",
            "surface-container", "surface-container-high", "surface-container-highest")
PAIRS = (
    [(fg, bg, TEXT) for fg in ("on-surface", "on-surface-variant", "primary", "secondary", "error")
     for bg in SURFACES]
    + [(fg, bg, UI) for fg in ("outline", "tertiary", "success", "warning", "info")
       for bg in ("background", "surface-container-lowest", "surface-container")]
    + [
        ("on-primary", "primary", TEXT),
        ("on-primary", "primary-container", TEXT),
        ("primary", "primary-fixed", TEXT),
        ("on-surface", "primary-fixed", TEXT),
        ("on-secondary", "secondary", TEXT),
        ("on-secondary-container", "secondary-container", TEXT),
        ("on-secondary-fixed", "secondary-fixed", TEXT),
        ("on-tertiary-fixed", "tertiary-fixed", TEXT),
        ("on-tertiary-container", "tertiary-container", TEXT),
        ("on-error", "error", TEXT),
        ("on-error-container", "error-container", TEXT),
        ("on-hero", "hero-from", TEXT),
        ("on-hero", "hero-via", TEXT),
        ("on-hero", "hero-to", TEXT),
        ("inverse-on-surface", "inverse-surface", TEXT),
        ("on-success-container", "success-container", TEXT),
        ("tertiary", "warning-container", TEXT),
        ("warning", "warning-container", UI),
        ("primary", "background", UI),  # anneau de focus
    ]
)

# Écarts du thème clair antérieurs au thème : signalés, non bloquants.
KNOWN_LIGHT = {
    ("warning", "surface-container"),  # ambre Tailwind 600 du module community
    ("on-tertiary-container", "tertiary-container"),  # palette admin
}


def blocks(css):
    """Valeurs de chaque bloc :root…{…} (sans les media queries imbriquées)."""
    found = {}
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for selector, body in re.findall(r"(:root[^{]*)\{([^{}]*)\}", css):
        values = dict(re.findall(r"--md-([\w-]+):\s*(\d+ \d+ \d+);", body))
        found.setdefault(selector.strip(), []).append(values)
    return found


def luminance(triplet):
    channels = [int(x) / 255 for x in triplet.split()]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def hexa(triplet):
    return "#" + "".join("%02x" % int(x) for x in triplet.split())


def themes(css):
    found = blocks(css)
    light = dict(found[":root"][0])
    dark_copies = found[':root[data-theme="dark"]'][:1] + found[":root:not([data-theme])"][:1]
    result = {"clair (prof)": light}
    for role in ("admin", "student", "auth"):
        result[f"clair ({role})"] = {**light, **found[f':root[data-palette="{role}"]'][0]}
    result["sombre"] = {**light, **dark_copies[0]}
    return result, dark_copies


def main(argv):
    css = THEME_CSS.read_text(encoding="utf-8")
    all_themes, dark_copies = themes(css)
    errors = []
    if len(dark_copies) != 2 or dark_copies[0] != dark_copies[1]:
        errors.append("Le bloc sombre de la media query prefers-color-scheme diffère de :root[data-theme=\"dark\"].")

    markdown = "--markdown" in argv
    if markdown:
        print("| Texte | Fond | Seuil | Clair (prof) | Sombre |")
        print("|---|---|---|---|---|")
    for fg, bg, minimum in PAIRS:
        cells = []
        for name, values in all_themes.items():
            value = ratio(values[fg], values[bg])
            ok = value >= minimum
            if not ok:
                known = name.startswith("clair") and (fg, bg) in KNOWN_LIGHT
                tag = "préexistant" if known else "ÉCHEC"
                line = f"{tag:12} {name:14} {fg} sur {bg} : {value:.2f}:1 (min {minimum})"
                (print if known else errors.append)(line)
            cells.append((name, values, value, ok))
        if markdown:
            light, dark = cells[0], cells[-1]
            fmt = lambda c: f"{c[1][fg] and hexa(c[1][fg])} / {hexa(c[1][bg])} — **{c[2]:.2f}**{'' if c[3] else ' ⚠'}"
            print(f"| `{fg}` | `{bg}` | {minimum} | {fmt(light)} | {fmt(dark)} |")

    for line in errors:
        print(line)
    if errors:
        print(f"\n{len(errors)} paire(s) sous le seuil WCAG AA.")
        return 1
    print(f"\nContraste OK : {len(PAIRS)} paires x {len(all_themes)} thèmes.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
