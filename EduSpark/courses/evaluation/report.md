# Évaluation du plan de cours IA

Généré par `python manage.py evaluate_ai --runs 2` le 27/10/2026 à 00:07.

- Jeu d'évaluation : 8 cas (`courses/evaluation/cases.json`) × 2 essai(s)
- Lecteur local : `qwen2.5:3b` (Ollama) · Rédacteur : `openai/gpt-oss-120b` (groq)

## Lecteur local (extraction des thèmes)

| Métrique | Valeur |
|---|---|
| Réponses exploitables | 100 % |
| Précision (thèmes ancrés dans le support) | 97 % |
| Rappel (notions de référence retrouvées) | 65 % |
| F1 | 0.75 |
| Thèmes dans la langue demandée | 100 % |
| Latence moyenne / p50 / p95 (s) | 3.5 / 3.3 / 5.1 |

### Avant / après (`baseline_v1.json`)

Même jeu de cas, mêmes règles de calcul ; seule la consigne du lecteur local a changé
(couvrir l'ensemble du document en regroupant les notions proches).

| Métrique | Avant | Après |
|---|---|---|
| Précision | 97 % | 97 % |
| Rappel | 60 % | 65 % |
| F1 | 0.71 | 0.75 |
| Langue demandée | 100 % | 100 % |

## Rédacteur (plan JSON)

| Métrique | Valeur |
|---|---|
| Appels réussis | 100 % |
| JSON valide au premier essai | 100 % |
| Nombre de chapitres respecté | 100 % |
| Écart moyen au volume horaire demandé | 0 % |
| Chapitres avec 2 à 4 objectifs | 100 % |
| Latence moyenne / p50 / p95 (s) | 1.9 / 1.8 / 2.8 |

## Détail par cas

| Cas | Langue | Essai | Précision | Rappel | F1 | Langue OK | Lecture (s) | JSON | Chapitres OK | Écart heures | Rédaction (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| graphes-fr | fr | 1 | 100 % | 71 % | 0.83 | 100 % | 5.1 | oui | oui | 0 % | 2.8 |
| graphes-fr | fr | 2 | 100 % | 71 % | 0.83 | 100 % | 4.0 | oui | oui | 0 % | 2.1 |
| sql-fr | fr | 1 | 100 % | 71 % | 0.83 | 100 % | 3.9 | oui | oui | 0 % | 1.8 |
| sql-fr | fr | 2 | 100 % | 71 % | 0.83 | 100 % | 3.3 | oui | oui | 0 % | 1.6 |
| tests-mixte | fr | 1 | 100 % | 29 % | 0.44 | 100 % | 3.4 | oui | oui | 0 % | 2.5 |
| tests-mixte | fr | 2 | 100 % | 43 % | 0.60 | 100 % | 3.5 | oui | oui | 0 % | 2.4 |
| laravel-fr | fr | 1 | 100 % | 86 % | 0.92 | 100 % | 3.3 | oui | oui | 0 % | 2.0 |
| laravel-fr | fr | 2 | 100 % | 86 % | 0.92 | 100 % | 3.2 | oui | oui | 0 % | 1.5 |
| ml-en | en | 1 | 100 % | 57 % | 0.73 | 100 % | 3.0 | oui | oui | 0 % | 1.8 |
| ml-en | en | 2 | 100 % | 57 % | 0.73 | 100 % | 2.8 | oui | oui | 0 % | 1.8 |
| reseaux-fr-en | fr | 1 | — | 71 % | — | 100 % | 3.8 | oui | oui | 0 % | 2.1 |
| reseaux-fr-en | fr | 2 | — | 71 % | — | 100 % | 3.2 | oui | oui | 0 % | 1.7 |
| archi-court | fr | 1 | 80 % | 60 % | 0.69 | 100 % | 3.1 | oui | oui | 0 % | 1.4 |
| archi-court | fr | 2 | 80 % | 60 % | 0.69 | 100 % | 2.9 | oui | oui | 0 % | 1.4 |
| stats-ar | ar | 1 | — | — | — | 100 % | 3.8 | oui | oui | 0 % | 1.9 |
| stats-ar | ar | 2 | — | — | — | 100 % | 4.0 | oui | oui | 0 % | 1.6 |

## Lecture des métriques

- **Précision** : un thème est compté juste s'il reprend au moins un mot significatif du support ;
  un thème inventé (hors du texte) la fait baisser.
- **Rappel** : part des notions annotées à la main (champ `keywords`) retrouvées dans les thèmes.
- Cas traduits (`source_language` différente de la langue demandée : support anglais pour un plan
  en français, plan en arabe) : précision et F1 non calculées, seuls rappel et langue comptent.
- **Langue** : un thème en chinois, japonais ou coréen, ou dans le mauvais alphabet, est non conforme.
- Les temps sont mesurés de bout en bout pour chaque étape (réseau compris). La génération tourne en
  tâche de fond (`courses/services/jobs.py`) : la page n'est jamais bloquée pendant ce temps.
