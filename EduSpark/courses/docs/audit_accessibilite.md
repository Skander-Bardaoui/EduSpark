# Audit d'accessibilité — module cours

Audit automatisé **axe-core 4.10.2** (moteur utilisé par Lighthouse et axe DevTools),
règles **WCAG 2.0 / 2.1 niveaux A et AA**, sur les 23 pages du module cours,
pour les trois rôles, en **thème clair et thème sombre** (46 audits).

## Résultat

**0 violation** après correction (une seule anomalie trouvée au premier passage, voir plus bas).

| Rôle | Page | HTTP | Violations (clair) | Violations (sombre) |
|---|---|---|---|---|
| Professeur | `/prof/cours/` | 200 | 0 | 0 |
| Professeur | `/prof/cours/nouveau/` | 200 | 0 | 0 |
| Professeur | `/prof/cours/6/` | 200 | 0 | 0 |
| Professeur | `/prof/cours/6/plan-ia/` | 200 | 0 | 0 |
| Professeur | `/prof/cours/6/plan-ia/manuel/` | 200 | 0 | 0 |
| Professeur | `/prof/cours/6/chapitres/nouveau/` | 200 | 0 | 0 |
| Professeur | `/prof/matieres/` | 200 | 0 | 0 |
| Professeur | `/prof/emploi-du-temps/` | 200 | 0 | 0 |
| Professeur | `/prof/supports-de-cours/` | 200 | 0 | 0 |
| Professeur | `/prof/supports-de-cours/nouveau/?cours=6` | 200 | 0 | 0 |
| Professeur | `/cours/supports/7/` | 200 | 0 | 0 |
| Admin université | `/administration/offre-de-formation/` | 200 | 0 | 0 |
| Admin université | `/administration/matieres/` | 200 | 0 | 0 |
| Admin université | `/administration/matieres/nouvelle/` | 200 | 0 | 0 |
| Admin université | `/administration/affectations/` | 200 | 0 | 0 |
| Admin université | `/administration/emploi-du-temps/` | 200 | 0 | 0 |
| Admin université | `/administration/emploi-du-temps/seances/nouvelle/` | 200 | 0 | 0 |
| Admin université | `/administration/cours/` | 200 | 0 | 0 |
| Admin université | `/administration/cours/1/` | 200 | 0 | 0 |
| Étudiant | `/etudiant/cours/` | 200 | 0 | 0 |
| Étudiant | `/etudiant/cours/1/` | 200 | 0 | 0 |
| Étudiant | `/etudiant/emploi-du-temps/` | 200 | 0 | 0 |
| Étudiant | `/etudiant/supports-de-cours/` | 200 | 0 | 0 |

## Anomalie corrigée

| Règle | Élément | Avant | Correction |
|---|---|---|---|
| `color-contrast` (WCAG 1.4.3) | Étiquette « Libre » des créneaux vides de l'emploi du temps (`_week_grid.html`) | 4,16:1 (gris `outline` sur fond clair, 11 px) | Couleur `on-surface-variant` : contraste supérieur à 4,5:1 dans les deux thèmes |

## Ce que couvrent les critères de la grille

- **Structure sémantique** : chaque page a un `<main id="main-content">`, un seul `<h1>`, des sections
  titrées (`<h2>` reliés par `aria-labelledby`), la navigation dans `<nav>` et un lien d'évitement
  « Aller au contenu » ; les pages d'erreur (403, 404, 500) ont `<header>`, `<main>`, `<nav>` et `<footer>`.
- **ARIA et textes alternatifs** : boutons à icône seule nommés (`aria-label`), icônes décoratives
  masquées (`aria-hidden`), zones dynamiques annoncées (`role="status"`, `aria-live` sur la page
  d'attente de l'IA et le dépôt de fichiers), erreurs de formulaire signalées par `aria-invalid`.
- **Contraste** : vérifié par axe sur chaque page et par `scripts/check_contrast.py` sur tous les
  tokens de couleur (WCAG AA, clair et sombre).
- **Clavier** : tous les contrôles sont des éléments natifs (`a`, `button`, `input`, `select`) ;
  focus visible partout (contour `primary`, renforcé en jaune via le menu Accessibilité) ; zone de
  dépôt de fichiers activable au clavier (bouton « Choisir des fichiers ») ; modales avec focus piégé
  et fermeture par Échap.

## Refaire l'audit

- Chrome : DevTools → **Lighthouse** → catégorie *Accessibility*, ou l'extension **axe DevTools**.
- Pages à vérifier : celles du tableau ci-dessus, connecté avec chaque rôle, puis en thème sombre
  (bouton soleil / lune de la barre du haut).
