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
