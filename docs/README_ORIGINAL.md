# EduSpark

Hub éducatif et créatif multimodal : landing page, authentification (sessions +
JWT) et gestion des rôles (admin / prof / étudiant).

## Démarrage rapide

Le code Django se trouve dans le dossier `EduSpark/` (là où se trouve `manage.py`).

```powershell
# 1) Environnement virtuel + dépendances
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) Configuration locale : les secrets vivent dans .env (non versionné)
Copy-Item EduSpark\.env.example EduSpark\.env
# Générer une clé secrète unique puis la coller dans EduSpark\.env : DJANGO_SECRET_KEY="..."
.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# 3) Base de données PostgreSQL : créer la base (une seule fois).
#    Adapter le chemin de psql.exe à la version installée de PostgreSQL.
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE eduspark ENCODING 'UTF8';"
#    Renseigner ensuite EduSpark\.env : DJANGO_DB_USER=postgres et
#    DJANGO_DB_PASSWORD=<mot de passe du superutilisateur postgres>.
#    Variante recommandée hors développement local : un rôle dédié, qui doit
#    posséder CREATEDB pour les tests —
#      CREATE ROLE eduspark WITH LOGIN PASSWORD '...' CREATEDB;
#      CREATE DATABASE eduspark OWNER eduspark ENCODING 'UTF8';
#    — puis DJANGO_DB_USER=eduspark dans .env.

# 4) Migrations
cd EduSpark
..\.venv\Scripts\python.exe manage.py migrate

# 5) Compte admin (back-office)
$env:DJANGO_SUPERUSER_PASSWORD='Admin12345!'
..\.venv\Scripts\python.exe manage.py createsuperuser --noinput --username admin@eduspark.local --email admin@eduspark.local

# 6) Serveur de développement
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

## Configuration (.env)

Aucun secret n'est écrit dans `settings.py` : la configuration vient du fichier
`.env`, qui n'est **jamais versionné** (cf. `.gitignore`). Le modèle
`EduSpark/.env.example` est, lui, versionné et sert de référence.

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Clé de signature (sessions, JWT, liens de réinitialisation). **Obligatoire** | — (le serveur refuse de démarrer) |
| `DJANGO_DEBUG` | Mode debug (tracebacks) | `False` |
| `DJANGO_ALLOWED_HOSTS` | Hôtes acceptés, séparés par des virgules | vide |
| `DJANGO_DB_NAME` | Nom de la base PostgreSQL | `eduspark` |
| `DJANGO_DB_USER` | Rôle PostgreSQL | `postgres` |
| `DJANGO_DB_PASSWORD` | Mot de passe du rôle | vide |
| `DJANGO_DB_HOST`, `DJANGO_DB_PORT` | Serveur PostgreSQL | `localhost`, `5432` |
| `DJANGO_LANGUAGE_CODE`, `DJANGO_TIME_ZONE` | Internationalisation | `en-us`, `UTC` |
| `DJANGO_EMAIL_BACKEND` | Backend e-mail (console par défaut en dev) | console |
| `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`, `DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD`, `DJANGO_EMAIL_USE_TLS` | SMTP de production | — |
| `GROQ_API_KEY` | Plan d'étude IA, examinateur et bilan du test de langue | — |
| `GROQ_MODEL` | Modèle Groq utilisé | `openai/gpt-oss-120b` |
| `ELEVENLABS_API_KEY` | Transcription temps réel du test de langue (facultatif) | — (repli navigateur) |
| `OPENAI_API_KEY` | Voix de l'examinateur (facultatif) | — (repli navigateur) |

Les variables déjà définies dans l'environnement du système sont prioritaires
sur celles de `.env`.

## Base de données

Le projet utilise **PostgreSQL** via le backend
`django.db.backends.postgresql` et le driver **psycopg 3** (cf.
`requirements.txt`). Aucune chaîne de connexion n'est écrite dans
`settings.py` : tout vient de `.env` (voir le tableau ci-dessus).

L'ancienne base de développement `EduSpark/db.sqlite3` n'est plus utilisée
(elle reste ignorée par git) ; voir « Reprendre les données de l'ancienne base
SQLite » plus bas si besoin.

Commandes utiles, depuis le dossier `EduSpark/` :

```powershell
# Appliquer les migrations
..\.venv\Scripts\python.exe manage.py migrate

# Vérifier l'état des migrations / ouvrir un shell SQL (psql)
..\.venv\Scripts\python.exe manage.py showmigrations
..\.venv\Scripts\python.exe manage.py dbshell

# Tests : Django crée une base jetable, le rôle doit donc avoir CREATEDB
# (c'est le cas du superutilisateur postgres utilisé en local).
..\.venv\Scripts\python.exe manage.py test
```

### Reprendre les données de l'ancienne base SQLite

Le script ci-dessous exporte l'ancienne base sans rien modifier au projet
(il remplace le moteur de base uniquement dans le processus courant) :

```powershell
# 1) Export depuis SQLite -> backup_sqlite.json (à la racine du dépôt)
cd EduSpark
@'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EduSpark.settings")
# Le moteur de base est remplacé AVANT django.setup() : l'override doit être
# en place au moment où Django initialise ses connexions.
import EduSpark.settings as project_settings
project_settings.DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(project_settings.BASE_DIR / "db.sqlite3"),
    }
}
django.setup()
from django.core.management import call_command
with open("../backup_sqlite.json", "w", encoding="utf-8") as fh:
    call_command(
        "dumpdata",
        "--exclude=contenttypes",
        "--exclude=auth.permission",
        # Les groupes admin / prof / etudiant sont recréés par la migration
        # accounts.0002_role_groups : les exclure évite un conflit de clés.
        "--exclude=auth.group",
        "--exclude=token_blacklist",
        "--indent=2",
        stdout=fh,
    )
'@ | ..\.venv\Scripts\python.exe -

# 2) Import dans PostgreSQL (toujours depuis EduSpark/, base vide, migrations
#    déjà appliquées). Le signal post_save d'auth.User crée des profils « par
#    défaut » qui entreraient en conflit avec les pk du fichier : on le
#    déconnecte le temps de l'import, puis on resynchronise les groupes
#    Django depuis le rôle de chaque profil.
@'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EduSpark.settings")
django.setup()
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db.models.signals import post_save
from accounts.models import Profil, setup_user_profil

post_save.disconnect(setup_user_profil, sender=User)
call_command("loaddata", "../backup_sqlite.json")
post_save.connect(setup_user_profil, sender=User)
for profil in Profil.objects.all():
    profil.save()  # réaligne l'appartenance au groupe Django sur le rôle
'@ | ..\.venv\Scripts\python.exe -
```

## Cours, matières et emplois du temps

Le module `courses` relie les trois rôles d'une université :

| Rôle | Ce qu'il fait |
| --- | --- |
| **Admin université** | Crée les départements, filières et matières, **affecte** un professeur à chaque matière d'une classe, puis planifie l'**emploi du temps** de chaque classe (séances CM / TD / TP, avec détection des conflits de classe, de groupe, de professeur et de salle). Supervise les cours en lecture seule. |
| **Professeur** | Voit ses matières et son emploi du temps (déduits de ses affectations), crée ses **cours**, leurs **chapitres** et leurs **supports** (PDF, présentations, vidéos, audios), puis **publie chaque cours classe par classe**. |
| **Étudiant** | Voit l'emploi du temps de sa classe (et de ses groupes de TD / TP), ses matières avec leurs enseignants, et les cours **publiés pour sa classe** avec leurs supports. |

Règles à connaître :

- Un étudiant appartient à une classe par ses **groupes** (`StudentGroup`) : sans groupe, il n'a ni emploi du temps ni cours.
- Un professeur ne peut créer un cours, et le publier pour une classe, que si l'admin lui a affecté la matière dans cette classe. Supprimer ou remplacer l'affectation retire ses cours de la classe.
- Supprimer un département, une filière ou une matière encore utilisés est refusé avec un message (la suppression d'une université entière, elle, emporte son catalogue).
- Les supports sont stockés dans **`EduSpark/protected_media/`** (hors `MEDIA_ROOT`, ignoré par git) et n'ont **aucune URL publique** : ils ne sont servis que par `/cours/supports/<id>/fichier/`, qui vérifie les droits (auteur, admin de l'université, étudiants des classes où le cours est publié) et gère la lecture partielle des vidéos et audios. Formats et tailles maximales : PDF (50 Mo), présentations `.ppt/.pptx/.pps/.ppsx/.odp` (100 Mo), documents Word `.doc/.docx/.odt` (50 Mo), vidéos `.mp4/.webm/.ogv/.mov/.m4v` (500 Mo), audios `.mp3/.wav/.ogg/.m4a/.aac/.flac` (100 Mo).
- Une classe peut être rattachée à une filière du catalogue (formulaire de la classe) ; son libellé « Filière » suit alors le nom de la filière.

Jeu de données de démonstration (développement uniquement, idempotent ; il lance d'abord `seed_demo`) :

```powershell
cd EduSpark
..\.venv\Scripts\python.exe manage.py seed_courses
# admin.paris@u-paris.fr / Admin12345!   -> catalogue, affectations, emploi du temps
# prof.test@eduspark.local / Prof12345!  -> cours, chapitres, supports, publication
#   (professeur de deux universités : choisir « Université Paris Cité » dans le sélecteur)
# test.ui@example.com / Etudiant12345!   -> L3 Informatique, groupe TD A
```

Pages principales :

| URL | Rôle | Description |
| --- | --- | --- |
| `/administration/offre-de-formation/` | Admin | Départements et filières |
| `/administration/matieres/` | Admin | Matières (semestre, coefficient, ECTS, volumes) |
| `/administration/affectations/` | Admin | Affectation des professeurs aux matières de chaque classe |
| `/administration/emploi-du-temps/` | Admin | Emploi du temps de chaque classe |
| `/administration/cours/` | Admin | Supervision des cours |
| `/prof/cours/` | Professeur | Mes cours (chapitres, supports, publication par classe) |
| `/prof/matieres/`, `/prof/emploi-du-temps/` | Professeur | Mes matières, mon emploi du temps |
| `/prof/supports-de-cours/` | Professeur | Bibliothèque de mes supports |
| `/etudiant/cours/` | Étudiant | Matières, enseignants et cours publiés de ma classe |
| `/etudiant/emploi-du-temps/` | Étudiant | Emploi du temps de ma classe et de mes groupes |
| `/etudiant/supports-de-cours/` | Étudiant | Supports des cours publiés |

## IA du module courses

Une seule fonctionnalité IA : le bouton **« Générer un plan de cours »** sur la page d'un cours (portail professeur). Le module fonctionne à 100 % sans IA.

### Pipeline en deux étapes (« lecture → écriture »)

```
Supports du cours (PDF, PPTX, DOCX)          ┌──────────── serveur de l'université ────────────┐
        │  texte extrait (pypdf, python-pptx) │                                                 │
        ▼                                     │                                                 │
 Étape 1 — LECTEUR local (Ollama, qwen2.5)  ──┼─► {"topics": ["...", ...]}  (8 thèmes max)      │
        │                                     └─────────────────────────────────────────────────┘
        │  titre + niveau + options + thèmes   (jamais les documents)
        ▼
 Étape 2 — RÉDACTEUR API (Groq, Google Gemini ou Anthropic)
        │  {"chapters": [{"title", "objectives", "duration_hours"}]}  validé strictement
        ▼
 Aperçu modifiable ─► le professeur ajoute / retire / réordonne / corrige ─► « Enregistrer le plan »
```

**Les documents restent sur le serveur, seul un résumé (la liste des thèmes) part vers l'API.**

| Situation | Comportement |
| --- | --- |
| Pas de support lisible (aucun, ou seulement vidéos/audios) | Étape 1 sautée, badge « Rédaction API seule » |
| Ollama arrêté ou trop lent (`AI_LOCAL_TIMEOUT`) | L'API rédige seule, l'aperçu l'indique |
| Réponse de l'API invalide | Un nouvel essai, puis bascule en saisie manuelle |
| API en panne, clé absente, limite horaire atteinte | Avertissement + aperçu vide pour saisir le plan à la main |

Rien n'est écrit en base avant le clic sur **« Enregistrer le plan »** : les chapitres sont alors créés dans une transaction, à la suite des chapitres existants. Le code IA est isolé dans `courses/services/ai.py` ; les vues (`courses/ai_views.py`) n'appellent jamais une API directement. Un cache (1 h, invalidé quand un support change) évite les appels en double, et chaque professeur est limité à `AI_RATE_LIMIT_PER_HOUR` générations par heure.

### Variables d'environnement (`EduSpark/.env`)

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `AI_PROVIDER` | `groq` (offre gratuite), `gemini` (offre gratuite d'AI Studio), `anthropic` (payant) ou `fake` (plan fixe, aucun appel réseau) | `groq` (`fake` dans `.env.example`) |
| `AI_API_TIMEOUT` | Délai max d'un appel au rédacteur (s) | `60` |
| `COURSES_GROQ_API_KEY` | Clé Groq du module cours (distincte de `GROQ_API_KEY` du coaching). Absente = saisie manuelle | vide |
| `COURSES_GROQ_MODEL` | Modèle rédacteur Groq (modèle « Production » ; `openai/gpt-oss-20b` pour plus de vitesse) | `openai/gpt-oss-120b` |
| `GEMINI_API_KEY` | Clé Google AI Studio. Absente = saisie manuelle | vide |
| `GEMINI_MODEL` | Modèle rédacteur Gemini | `gemini-2.5-flash` |
| `ANTHROPIC_API_KEY` | Clé Anthropic. Absente = saisie manuelle | vide |
| `ANTHROPIC_MODEL` | Modèle rédacteur Anthropic | `claude-sonnet-5-5` |
| `ANTHROPIC_EFFORT` | Profondeur de réflexion : `low`, `medium`, `high` | `medium` |
| `ANTHROPIC_FALLBACKS` | Si le modèle décline la demande, l'API la rejoue sur un modèle de repli | `True` |
| `OLLAMA_URL` | Adresse d'Ollama | `http://localhost:11434` |
| `OLLAMA_MODEL` | Modèle lecteur | `qwen2.5:3b` |
| `OLLAMA_KEEP_ALIVE` | Durée de maintien du modèle en mémoire | `30m` |
| `AI_LOCAL_TIMEOUT` | Délai max du lecteur local (s) ; au-delà, l'API rédige seule | `120` |
| `AI_LOCAL_TEXT_LIMIT` | Caractères de supports envoyés au lecteur | `4000` |
| `AI_RATE_LIMIT_PER_HOUR` | Générations par professeur et par heure | `10` |

### Choisir le rédacteur

- **Groq (`AI_PROVIDER=groq`, par défaut)** : clé propre au module cours, `COURSES_GROQ_API_KEY`, créée sur <https://console.groq.com> → *API Keys*. Elle est distincte de `GROQ_API_KEY` (test de langue du module coaching) : chaque module garde sa clé et son quota. Offre gratuite avec limites de requêtes. Groq n'impose pas de schéma à la sortie : la forme JSON est demandée dans la consigne puis vérifiée strictement, avec un nouvel essai si besoin.
- **Gemini (`AI_PROVIDER=gemini`)** : créer une clé sur <https://aistudio.google.com> → *Get API key*, puis la mettre dans `EduSpark/.env` (`GEMINI_API_KEY=...`). L'offre gratuite suffit pour le développement et la démo (nombre de requêtes limité par minute et par jour). Sur l'offre gratuite, Google peut utiliser les requêtes pour améliorer ses produits : ici, il ne reçoit que le titre, le niveau et les thèmes, jamais les supports. Si `GEMINI_MODEL` n'existe plus, prendre un modèle « Flash » listé dans AI Studio.
- **Anthropic (`AI_PROVIDER=anthropic`)** : payant à l'usage (`ANTHROPIC_API_KEY`).
- Une clé ne doit **jamais** être commitée ni partagée (chat, capture d'écran). Si c'est arrivé, la supprimer et en créer une nouvelle.

### Installer Ollama

1. Installer Ollama sur le PC : <https://ollama.com/download> (recommandé sous Windows / macOS : utilise le GPU).
2. Télécharger le modèle lecteur :

   ```powershell
   ollama pull qwen2.5:3b     # ~2 Go, ~4 Go de RAM : suffit pour extraire des thèmes
   # ollama pull qwen2.5:7b   # seulement avec 16 Go de RAM ou un GPU (OLLAMA_MODEL=qwen2.5:7b)
   ```

3. Avec Docker (`docker-compose.yml` : Django, PostgreSQL et Ollama) :

   ```powershell
   docker compose up -d
   docker compose exec ollama ollama pull qwen2.5:3b
   ```

   Dans Docker, Django joint Ollama à `OLLAMA_URL=http://ollama:11434` (valeur déjà posée par le compose). Si Ollama tourne sur le PC et Django dans Docker : `OLLAMA_URL=http://host.docker.internal:11434`.

Conseils de démo : lancer une première génération deux minutes avant (le premier appel charge le modèle en mémoire), utiliser un PDF de 5 à 10 pages, et garder `AI_PROVIDER=fake` en secours.

### Tests

Aucun test n'appelle le réseau : Ollama (`requests.post`) et le client Anthropic sont simulés, ou `AI_PROVIDER=fake` est utilisé.

```powershell
cd EduSpark
..\.venv\Scripts\python.exe manage.py test courses.tests.test_ai   # tests de l'IA
..\.venv\Scripts\python.exe manage.py test courses                 # tout le module
# avec pytest :  pip install pytest pytest-django  puis  pytest courses/tests/test_ai.py
```

## Thème clair / sombre

Toute la plateforme partage un seul système de thème, avec trois choix :
**Système** (par défaut), **Clair** et **Sombre**. Le bouton se trouve dans la
barre du haut du portail. Le choix est mémorisé dans le navigateur
(`localStorage`, aucune donnée en base) et appliqué avant le premier rendu,
sans flash. En mode Système, le thème suit l'OS en direct.

### Architecture partagée (aucune dépendance Python entre modules)

| Fichier | Rôle |
| --- | --- |
| `EduSpark/static/theme/theme.css` | Tokens : palette claire (inchangée) et sombre, en variables CSS `R G B` |
| `EduSpark/static/theme/components.css` | Adaptations communes : ombres, edge lighting, menus et modales, formulaires, médias, transition |
| `EduSpark/static/theme/theme.js` | Bouton Système → Clair → Sombre (< 2 Ko), annonce `aria-live`, événement `themechange` |
| `EduSpark/templates/includes/theme_init.html` | Script anti-flash en tête de `<head>` + chargement du CSS et du JS |
| `EduSpark/templates/includes/theme_toggle.html` | Bouton accessible (inclus dans `portal/_topbar.html`) |
| `EduSpark/templates/includes/tailwind_theme_colors.html` | Couleurs Tailwind lues dans les variables (`rgb(var(--md-x) / <alpha-value>)`) |

Les pages du portail (`portal/base.html`) chargent tout automatiquement. Les
classes Tailwind existantes (`bg-surface-container-lowest`, `text-on-surface`,
`text-primary`…) changent donc de valeur avec le thème, sans modification des
templates.

### Philosophie

- **Nuances, pas de noir pur** : fond gris très sombre légèrement bleuté (teinte
  froide), texte principal blanc cassé, texte secondaire moins contrasté.
- **Élévation** : plus un élément est au premier plan, plus il est clair (fond <
  champs < cartes < menus / modales). Les ombres sont renforcées en sombre, les
  cartes, menus et modales ont un liseré lumineux de 1 px (*edge lighting*), et
  l'overlay des modales assombrit l'arrière-plan. Un état sélectionné change de
  fond **sans** liseré : c'est un état, pas une couche.
- **Accents** éclaircis et désaturés en sombre. Un statut n'est jamais porté par
  la couleur seule (icône ou texte).
- **Impression / PDF** toujours en thème clair (les blocs sombres sont limités à
  `@media screen`).

### Tokens

Rôles génériques (pour du CSS maison) : `--bg`, `--surface-1` … `--surface-6`,
`--text`, `--text-muted`, `--border`, `--edge-light`, `--accent`,
`--accent-contrast`, `--success`, `--warning`, `--danger`, `--info`,
`--shadow-sm/md/lg`, `--overlay`. Classes Tailwind : la palette Material du
portail (`surface…`, `on-surface…`, `primary…`, `outline…`) plus `scrim`
(voile des modales), `hero-from/via/to` et `on-hero` (bandeaux dégradés
sombres), `success`, `warning`, `info` et leurs conteneurs.

Valeurs claires et sombres, échelle des surfaces et ratios de contraste :
[`docs/theme-tokens.md`](docs/theme-tokens.md).

### Comment mon module adopte le thème (5 étapes)

1. **Hériter du portail** : `{% extends portal_base_template %}`. Une page hors
   portail inclut `{% include "includes/theme_init.html" %}` juste après la
   balise viewport.
2. **Utiliser les classes par rôle**, jamais une couleur : `bg-surface-container-lowest`
   plutôt que `bg-white`, `text-on-surface-variant` plutôt que `text-gray-600`,
   `bg-scrim/60` pour un overlay de modale, `text-success` / `text-warning` pour
   un statut (toujours avec une icône ou un texte).
3. **Bandeau dégradé sombre** : `bg-gradient-to-br from-hero-from via-hero-via
   to-hero-to text-on-hero`, et `bg-on-hero text-hero-via` pour un bouton clair
   posé dessus.
4. **Zone qui doit rester claire** (photo avec voile, aperçu inversé) : ajouter
   `data-theme-scope="light"` sur son conteneur.
5. **CSS ou JS maison** : `rgb(var(--text))`, `rgb(var(--md-primary) / .2)` ;
   écouter `window.addEventListener('themechange', …)` pour redessiner un
   graphique ou un calendrier.

### Tester

```powershell
cd EduSpark
..\.venv\Scripts\python.exe manage.py test EduSpark.tests      # gabarits, une page par module, multi-tenant
..\.venv\Scripts\python.exe scripts/check_contrast.py         # échoue si une paire passe sous WCAG AA
..\.venv\Scripts\python.exe scripts/find_hardcoded_colors.py  # inventaire des couleurs en dur restantes
```

Vérification manuelle de chaque module : clair puis sombre (bouton de la barre
du haut), mobile, zoom 200 %, navigation au clavier seul (focus visible),
`prefers-contrast: more` et `prefers-reduced-motion` (outils de rendu du
navigateur), aperçu avant impression (toujours clair).

### Limites connues

- Tailwind est chargé par CDN, en JavaScript : sans JS, le portail n'est pas mis
  en forme du tout. Le thème, lui, suit `prefers-color-scheme` sans JS.
- Hors thème, volontairement : la landing page, `accounts/auth.html` (sombre par
  conception) et les pages de réinitialisation du mot de passe (claires).
- Écarts de contraste du thème clair conservés pour ne pas changer le rendu :
  ambre `warning` sur `surface-container` (2,75:1, icônes des forums) et
  `on-tertiary-container` sur `tertiary-container` du portail admin (2,2:1).
- Quelques classes de champs définies en Python (`accounts/forms.py`) gardent une
  ombre de focus `rgba(...)` en dur ; elles restent lisibles dans les deux thèmes.
- Les universités n'ont pas encore de couleur ni de logo propre : si on en
  ajoute, prévoir une variante éclaircie de la couleur d'accent pour le sombre.

## URL principales

| URL | Description |
| --- | --- |
| `/` | Landing page (`landing:index`) |
| `/accounts/connexion/` | Connexion (`accounts:login`) |
| `/accounts/inscription/` | Inscription (`accounts:signup`) |
| `/accounts/deconnexion/` | Déconnexion (`accounts:logout`) |
| `/accounts/mot-de-passe-oublie/` | Réinitialisation du mot de passe (e-mail en console) |
| `/admin/` | Back-office Django (réservé au rôle `admin`) |

## API JWT

| Méthode | URL | Corps / En-tête |
| --- | --- | --- |
| POST | `/accounts/api/token/` | `{"username": "<email>", "password": "..."}` → `access`, `refresh`, `role`, `email` |
| POST | `/accounts/api/token/refresh/` | `{"refresh": "<token>"}` |
| POST | `/accounts/api/logout/` | `{"refresh": "<token>"}` (blacklist, `Bearer` requis) |
| GET | `/accounts/api/me/` | En-tête `Authorization: Bearer <access>` |
