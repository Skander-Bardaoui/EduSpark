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
