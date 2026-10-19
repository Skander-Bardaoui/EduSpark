# EduSpark

Hub éducatif et créatif multimodal, multi-universités : 6 modules Django
indépendants partageant une même base. Ce dépôt contient la landing page et le
**module 0 — `users`** : universités (tenants), comptes, rôles par université,
profils professeurs / étudiants, classes et groupes, invitations, et une
fonctionnalité IA (génération de bio).

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

# 6) (Optionnel) Données de démonstration : 2 universités, profs, étudiants, classes.
#    Mot de passe de tous les comptes de démo : Demo-2026!
..\.venv\Scripts\python.exe manage.py seed_demo

# 7) Serveur de développement
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
| `DJANGO_LANGUAGE_CODE`, `DJANGO_TIME_ZONE` | Internationalisation | `fr`, `UTC` |
| `ANTHROPIC_API_KEY` | Clé de l'API Claude pour le bouton IA. Vide = IA désactivée (message affiché, le reste fonctionne) | vide |
| `EDUSPARK_AI_MODEL` | Modèle utilisé par `users/services/ai.py` | `claude-opus-5-5` |
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

### ⚠️ Nouveau modèle utilisateur : repartir d'une base vide

Le module `users` définit `AUTH_USER_MODEL = 'users.User'` et
`TENANT_MODEL = 'users.University'`. Les migrations ont été régénérées : une
base créée avec l'ancienne app `accounts` est **incompatible**. En local :

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "DROP DATABASE IF EXISTS eduspark;" -c "CREATE DATABASE eduspark ENCODING 'UTF8';"
..\.venv\Scripts\python.exe manage.py migrate
```

## URL principales

| URL | Description | Accès |
| --- | --- | --- |
| `/` | Landing page (`landing:index`) | public |
| `/accounts/connexion/`, `/accounts/inscription/`, `/accounts/deconnexion/` | Authentification (l'inscription crée une demande d'adhésion à une université) | public |
| `/accounts/mot-de-passe-oublie/` | Réinitialisation du mot de passe (e-mail en console) | public |
| `/accounts/invitation/<token>/` | Accepter une invitation | public |
| `/tableau-de-bord/` | Tableau de bord selon le rôle (+ inscriptions à valider) | connecté |
| `/profil/` | Mon profil + bouton IA « Générer ma bio » | connecté |
| `/universite/changer/` | Choisir l'université courante | connecté |
| `/universites/` | CRUD universités | admin plateforme |
| `/comptes/` | Comptes de la plateforme (liste, détail, modification, suppression) | admin plateforme |
| `/professeurs/` | CRUD professeurs de l'université courante | lecture : membres — écriture : admin université |
| `/etudiants/` | CRUD étudiants | lecture : professeurs — écriture : admin université |
| `/classes/` | CRUD classes et groupes | lecture : membres — écriture : admin université |
| `/invitations/` | CRUD invitations (renvoyer, révoquer) | admin université |
| `/admin/` | Back-office Django | admin plateforme |

Toutes les listes ont une recherche (`?q=`), des filtres et une pagination.

## Rôles

| Rôle | Porté par | Peut |
| --- | --- | --- |
| Admin plateforme | `User.is_superuser` (global) | créer les universités, gérer tous les comptes, inviter les admins université, entrer dans n'importe quelle université |
| Admin université | `Membership(role="admin_universite")` | gérer professeurs, étudiants, classes, groupes, invitations de **son** université ; valider les inscriptions |
| Professeur | `Membership(role="professeur")` + `ProfessorProfile` | consulter professeurs, étudiants, classes — un même compte peut enseigner dans plusieurs universités |
| Étudiant | `Membership(role="etudiant")` + `StudentProfile` | consulter professeurs et classes |

Chacun édite son propre profil (`/profil/`).

## Multi-tenant : guide pour les autres modules

Le socle est dans `users/tenancy.py`. C'est le **seul** code partagé avec
`AUTH_USER_MODEL` et `TENANT_MODEL` : aucun module métier n'importe les modèles
d'un autre module, les liens se font par champs simples (matière, niveau).

```python
# exercices/models.py
from django.conf import settings
from django.db import models
from users.tenancy import TenantModel

class Exercice(TenantModel):                 # ajoute la colonne « university »
    titre = models.CharField(max_length=200)
    matiere = models.CharField(max_length=100)    # lien par champ simple
    niveau = models.CharField(max_length=50)
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

# exercices/views.py
from django.views.generic import ListView
from users.tenancy import Role, TenantScopedMixin

class ExerciceListView(TenantScopedMixin, ListView):
    model = Exercice                              # filtré sur request.university
    allowed_roles = (Role.PROFESSOR, Role.STUDENT)  # l'admin plateforme passe toujours
```

- `TenantMiddleware` place `request.university`, `request.membership` et
  `request.university_role` sur chaque requête (session, ou en-tête
  `X-University: <slug ou id>` pour l'API).
- `TenantScopedMixin` filtre le queryset (un objet d'une autre université → 404)
  et impose l'université à la création. Pour les vues fonctions :
  `@tenant_required(Role.UNIVERSITY_ADMIN, ...)`.
- Vues DRF : ajouter `TenantAPIMixin` (résout l'université après l'authentification JWT).
- IA : un seul appel isolé dans `<module>/services/ai.py`, qui lève une
  exception métier si l'IA est indisponible — voir `users/services/ai.py`.

## Tests

```powershell
..\.venv\Scripts\python.exe manage.py test users
```

Couvrent l'isolation entre universités, la matrice des permissions, les CRUD,
les invitations, l'inscription, l'API et le bouton IA (indisponible / simulé).

## API JWT

| Méthode | URL | Corps / En-tête |
| --- | --- | --- |
| POST | `/accounts/api/token/` | `{"username": "<email>", "password": "..."}` → `access`, `refresh`, `email`, `platform_role`, `memberships` |
| POST | `/accounts/api/token/refresh/` | `{"refresh": "<token>"}` |
| POST | `/accounts/api/logout/` | `{"refresh": "<token>"}` (blacklist, `Bearer` requis) |
| GET | `/accounts/api/me/` | `Authorization: Bearer <access>` (+ `X-University: <slug>` optionnel) → profil, universités, université et rôle courants |
