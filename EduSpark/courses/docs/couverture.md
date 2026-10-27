# Tests et couverture — module cours

**431 tests** automatisés, **tous verts**.
Couverture du code du module : **99 %** (lignes et branches), 100 % des lignes sauf 2.

## Lancer les tests et la couverture

Depuis le dossier `EduSpark/` :

```powershell
..\.venv\Scripts\python.exe -m pip install -r courses\requirements-dev.txt
..\.venv\Scripts\python.exe manage.py test courses
..\.venv\Scripts\python.exe -m coverage run --rcfile=courses/.coveragerc manage.py test courses
..\.venv\Scripts\python.exe -m coverage report --rcfile=courses/.coveragerc
..\.venv\Scripts\python.exe -m coverage html --rcfile=courses/.coveragerc    # courses/docs/coverage_html/index.html
```

Aucun appel réseau dans les tests : Ollama, Gemini, Groq et Anthropic sont simulés ; les fichiers
déposés vont dans un dossier temporaire.

## Types de tests

- **Unitaires** : modèles (validations, contraintes, conflits d'emploi du temps), services (pipeline IA,
  métriques, lanceur de tâches, droits d'accès aux supports), formulaires, filtres de gabarits.
- **Intégration / vues** : client de test Django sur chaque page et endpoint (codes HTTP, contenu,
  redirections, JSON), parcours complets admin → professeur → étudiant.
- **Sécurité / permissions** : accès refusé par rôle (403), isolation entre universités (404),
  supports protégés (pas d'URL publique), jetons CSRF, tâche IA liée à son auteur.

## Inventaire

| Fichier | Tests | Contenu |
|---|---|---|
| `test_admin_flow.py` | 50 |  |
| `test_ai.py` | 46 | Pipeline IA : lecteur local + rédacteur, cas dégradés, cache, vues |
| `test_ai_async.py` | 18 | Génération en tâche de fond : thread réel, statut, résultat, accès |
| `test_ai_metrics.py` | 17 | Métriques IA et commande evaluate_ai |
| `test_ai_units.py` | 46 | Pipeline IA (unitaires) : lecture PDF / PowerPoint / Word, Gemini, Groq, Anthropic, quotas |
| `test_course_upload.py` | 7 | Dépôt de fichiers par bouton ou glisser-déposer |
| `test_error_pages.py` | 4 | Pages d'erreur 403 / 404 / 500 |
| `test_files.py` | 35 |  |
| `test_integration.py` | 20 |  |
| `test_models.py` | 47 | Modèles : contraintes, normalisation, suppressions protégées |
| `test_models_units.py` | 35 | Modèles (unitaires) : validations, conflits d'emploi du temps, droits d'accès, signaux, formulaires |
| `test_prof_flow.py` | 49 |  |
| `test_seed.py` | 9 |  |
| `test_services.py` | 18 |  |
| `test_student_flow.py` | 30 |  |

## Rapport de couverture (27/10/2026)

| Name                                            |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------------------------ | -------: | -------: | -------: | -------: | ------: | --------: |
| courses\\models.py                              |      405 |        1 |      102 |       12 |     97% |164-\>166, 243-\>259, 263-\>265, 339-\>344, 365-\>364, 372-\>374, 499, 554-\>556, 562-\>564, 630-\>632, 681-\>exit, 695-\>697 |
| courses\\services\\\_\_init\_\_.py              |      102 |        1 |       40 |        1 |     99% |       207 |
| courses\\files.py                               |       56 |        0 |       20 |        1 |     99% |128-\>exit |
| courses\\forms.py                               |      259 |        0 |       40 |        1 |     99% | 137-\>141 |
| courses\\admin.py                               |       63 |        0 |        0 |        0 |    100% |           |
| courses\\admin\_views.py                        |      289 |        0 |       20 |        0 |    100% |           |
| courses\\ai\_views.py                           |      119 |        0 |       12 |        0 |    100% |           |
| courses\\apps.py                                |        7 |        0 |        0 |        0 |    100% |           |
| courses\\file\_views.py                         |      105 |        0 |       26 |        0 |    100% |           |
| courses\\management\\commands\\evaluate\_ai.py  |      109 |        0 |       20 |        0 |    100% |           |
| courses\\management\\commands\\seed\_courses.py |      126 |        0 |       38 |        0 |    100% |           |
| courses\\mixins.py                              |       56 |        0 |        2 |        0 |    100% |           |
| courses\\prof\_views.py                         |      314 |        0 |       30 |        0 |    100% |           |
| courses\\services\\ai.py                        |      377 |        0 |      122 |        0 |    100% |           |
| courses\\services\\ai\_metrics.py               |       70 |        0 |       20 |        0 |    100% |           |
| courses\\services\\jobs.py                      |       40 |        0 |        4 |        0 |    100% |           |
| courses\\signals.py                             |       12 |        0 |        2 |        0 |    100% |           |
| courses\\storage.py                             |       18 |        0 |        2 |        0 |    100% |           |
| courses\\student\_views.py                      |       91 |        0 |       18 |        0 |    100% |           |
| courses\\tasks.py                               |       12 |        0 |        0 |        0 |    100% |           |
| courses\\templatetags\\courses\_extras.py       |       10 |        0 |        0 |        0 |    100% |           |
| courses\\urls.py                                |        6 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                                       | **2646** |    **2** |  **518** |   **15** | **99%** |           |

4 empty files skipped.
