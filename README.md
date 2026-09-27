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

# 3) Base de données
cd EduSpark
..\.venv\Scripts\python.exe manage.py migrate

# 4) Compte admin (back-office)
$env:DJANGO_SUPERUSER_PASSWORD='Admin12345!'
..\.venv\Scripts\python.exe manage.py createsuperuser --noinput --username admin@eduspark.local --email admin@eduspark.local

# 5) Serveur de développement
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
| `DJANGO_LANGUAGE_CODE`, `DJANGO_TIME_ZONE` | Internationalisation | `en-us`, `UTC` |
| `DJANGO_EMAIL_BACKEND` | Backend e-mail (console par défaut en dev) | console |
| `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`, `DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD`, `DJANGO_EMAIL_USE_TLS` | SMTP de production | — |

Les variables déjà définies dans l'environnement du système sont prioritaires
sur celles de `.env`.

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
