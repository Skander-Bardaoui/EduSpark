# Module Coaching — scénario complet et fonctionnel

Ce document décrit le scénario de bout en bout du module **Suivi Référent** (application `coaching`) :
ce qui a été branché, comment préparer les données, puis le parcours détaillé pour chaque rôle.

---

## 1. Ce qui est maintenant fonctionnel

| Fonction | Étudiant | Professeur référent | Admin université |
| --- | --- | --- | --- |
| Tableau de bord | Données réelles : objectifs, heures, tâches, assiduité, prochain RDV, examens, journal, tests de langue | Portefeuille, demandes, alertes, fiches, rendez-vous, présences à saisir | Effectifs, affectation des référents, alertes, cohortes, remédiation, activité |
| Objectifs | Création, mise à jour de l'avancement et des compétences, report d'échéance | Consultation via le suivi et le journal | Agrégation dans le pilotage |
| Planning d'étude | Ajout manuel, clôture/rouverture, **génération IA (Groq)**, application des blocs au planning, export CSV | — | — |
| Tâches | Ajout, priorisation, clôture/réouverture | — | — |
| Rendez-vous de tutorat | Demande sur créneau ou créneau libre, report | Créneaux, acceptation, refus motivé, clôture avec compte-rendu | — |
| Journal | Écriture d'entrées, lecture des retours | Retour sur les entrées | — |
| Notifications | Lecture, réponse au référent | Relance, signalement, e-mails | — |
| Présences | — | Occurrences de l'emploi du temps, séances exceptionnelles, saisie, recalcul d'assiduité, alerte automatique < 75 % | — |
| Fiches de difficulté | Notification d'ouverture | Création, notes, plan d'accompagnement, export | — |
| Persévérance | — | Signalement d'un étudiant | Affectation, prise en charge et clôture des alertes, export |
| Test de langue orale | Test IELTS / Cambridge, bilan détaillé | Consultation des bilans de son portefeuille | — |

Les trois tableaux de bord ne contiennent plus de données de démonstration codées en dur : ils lisent la base.

### Clé IA

La clé `GROQ_API_KEY` déjà présente dans `EduSpark/.env` est utilisée. Le modèle par défaut a été corrigé en
`openai/gpt-oss-120b` (l'ancien `llama-3.3-70b-versatile` n'est plus accessible sur le compte).
Si besoin, dans `EduSpark/.env` :

```dotenv
GROQ_API_KEY=<votre clé Groq>
GROQ_MODEL=openai/gpt-oss-120b
# Optionnels : sans eux, le navigateur assure la transcription et la voix.
ELEVENLABS_API_KEY=
OPENAI_API_KEY=
```

> Le test de langue reste utilisable avec la seule clé Groq : si ElevenLabs ou OpenAI ne sont pas configurés,
> la reconnaissance vocale et la synthèse vocale du navigateur prennent le relais.

---

## 2. Préparation des données

Depuis le dossier `EduSpark/` :

```bash
../.venv/Scripts/python.exe manage.py migrate
../.venv/Scripts/python.exe manage.py seed_demo
../.venv/Scripts/python.exe manage.py seed_coaching
../.venv/Scripts/python.exe manage.py seed_language_tests
../.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000
```

Les commandes `seed_*` sont idempotentes : on peut les relancer sans doubler les données.

### Comptes de démonstration

| Rôle | Identifiant | Mot de passe | Université |
| --- | --- | --- | --- |
| Admin université | `admin.paris@u-paris.fr` | `Admin12345!` | Université Paris Cité |
| Professeur référent | `prof.test@eduspark.local` | `Prof12345!` | Paris Cité **et** Lyon |
| Étudiante suivie | `test.ui@example.com` | `Etudiant12345!` | Paris Cité |
| Étudiants en difficulté | `yanis.leroy@u-paris.fr` / `ines.bernard@u-paris.fr` | `Etudiant12345!` | Paris Cité |
| Étudiants Lyon | `lucas.moreau@univ-lyon.fr` / `sofia.benali@univ-lyon.fr` | `Etudiant12345!` | Université de Lyon |

Les e-mails sont envoyés dans la console du serveur (`DJANGO_EMAIL_BACKEND=console`), ce qui permet de vérifier
chaque notification sans boîte mail réelle.

---

## 3. Scénario étudiant — Camille Martin

Connexion : `test.ui@example.com` / `Etudiant12345!` → redirection vers `/etudiant/tableau-de-bord/`.

### Étape 1 — Lire son tableau de bord
1. Vérifier les quatre indicateurs : progression des objectifs, révision de la semaine, tâches terminées, assiduité.
2. Vérifier « Ma semaine » : les sessions de travail réelles issues du planning.
3. Vérifier « Mes priorités » : les tâches actives avec leur échéance.
4. Vérifier « Mon référent » : Hélène Vasseur, prochain rendez-vous et notifications non lues.
5. Vérifier « Prochain jalon » : l'examen d'algorithmique planifié.

### Étape 2 — Gérer ses objectifs
1. Aller dans **Mes Objectifs & Plans** (`/etudiant/progression/`).
2. Cliquer **Ajouter un objectif** : saisir par exemple « Réussir le projet web », code `INFO302`,
   échéance dans 3 semaines, 8 compétences visées → **Créer l'objectif**.
3. Sur la carte de l'objectif, saisir un avancement (ex. `35`) et des compétences acquises (ex. `2`) →
   **Mettre à jour**. Le statut passe automatiquement à « En cours », « En retard » ou « Objectif atteint » à 100 %.
4. Sur un objectif en retard, utiliser **Reprogrammer** pour repousser l'échéance d'une semaine.

### Étape 3 — Planifier une session manuellement
1. Toujours dans la progression, cliquer **Planifier une session**.
2. Saisir « Réviser les jointures SQL », `INFO303`, type Révision, une date future, une heure et 60 minutes.
3. La session apparaît dans « Sessions de travail programmées » et dans « Ma semaine » du tableau de bord.
4. Cliquer **Marquer terminée** : les heures de révision du tableau de bord augmentent.

### Étape 4 — Générer un plan d'étude avec l'IA
1. Dans le panneau **Assistant Plan d'Étude IA** (colonne de droite), choisir un objectif ou « Tous les objectifs actifs ».
2. Régler la disponibilité (ex. 8 h) et la stratégie « Échéances imminentes ».
3. Cliquer **Générer la planification** : Groq renvoie un résumé, un score de viabilité et jusqu'à 8 blocs.
4. Cliquer **Garder** : les blocs futurs sont ajoutés au planning, sans doublon ni chevauchement avec une session existante.
5. Vérifier le message de statut puis l'apparition des blocs dans la semaine.
6. Cliquer **Rapport Synthèse** pour télécharger le CSV de progression.

### Étape 5 — Gérer ses tâches
1. Aller dans **Mes Tâches** (`/etudiant/taches/`).
2. Ajouter une tâche « Préparer la soutenance » avec l'horizon « Cette semaine ».
3. Cocher la tâche pour la terminer, puis la rouvrir : le compteur du tableau de bord suit.

### Étape 6 — Prendre et reporter un rendez-vous
1. Aller dans **Mes Rendez-vous** (`/etudiant/rendez-vous/`).
2. Choisir un créneau ouvert d'Hélène Vasseur, saisir un motif (« Revoir le projet web ») → **Envoyer la demande**.
3. Le professeur reçoit un e-mail dans la console ; la demande passe en « En attente ».
4. Après confirmation par le professeur, le rendez-vous apparaît dans « Prochain RDV » du tableau de bord
   et une notification est créée.
5. Utiliser **Reporter** sur un rendez-vous confirmé : une nouvelle demande est envoyée avec un e-mail au professeur.
6. Si le professeur refuse avec un motif, l'étudiante reçoit une notification et un e-mail ; le motif est conservé.

### Étape 7 — Journal et retour du référent
1. Aller dans **Journal de progression** (`/etudiant/journal/`).
2. Écrire une entrée : titre, ressenti (Confiance / Point d'attention…), réflexion (20 caractères minimum).
3. L'entrée apparaît aussi sur le tableau de bord (dernière entrée).
4. Après le retour d'Hélène, le commentaire du référent s'affiche sous l'entrée.

### Étape 8 — Notifications et réponse
1. Aller dans **Mes notifications** (`/etudiant/notifications/`).
2. Lire la relance d'Hélène, puis **Répondre** (« Je reprends les devoirs cette semaine… »).
3. La réponse est visible dans le suivi du professeur ; un e-mail lui est envoyé.
4. Le compteur de la sidebar et du tableau de bord diminue.

### Étape 9 — Test de langue orale
1. Aller dans **Test de langue** (`/etudiant/tests-langue/`) → **Nouveau test**.
2. Choisir Anglais, IELTS ou Cambridge B2, niveau B2, type d'exercice, puis **Démarrer la session**.
3. Autoriser le micro, cliquer **Connecter le micro**, écouter la première question,
   répondre à voix haute, puis **Envoyer la réponse**.
4. Répéter 2–3 échanges, puis **Terminer la session** : Groq produit le bilan.
5. Consulter le bilan : niveau global, verdict, quatre scores, notes par compétence, recommandations.
6. Le professeur référent voit ce bilan dans **Tests de langue** de son espace.

---

## 4. Scénario professeur référent — Hélène Vasseur

Connexion : `prof.test@eduspark.local` / `Prof12345!` → `/prof/tableau-de-bord/`.

> Le compte professeur appartient à **deux** universités. Par défaut (`resolve_tenant`), la première
> appartenance alphabétique est **Université de Lyon**. Pour suivre le scénario Paris avec Camille,
> ouvrir le sélecteur d'université (`/universite/changer/`) et choisir **Université Paris Cité**.
> Le scénario Lyon est identique avec Lucas Moreau et Sofia Benali.

### Étape 1 — Tableau de bord
1. Vérifier le portefeuille : Camille, Inès, Yanis.
2. Vérifier la répartition du risque : Yanis en vigilance haute, Camille en vigilance modérée, Inès autonome.
3. Vérifier les demandes en attente, les alertes ouvertes, les rendez-vous à venir,
   les fiches d'accompagnement et les relevés de présence à saisir.

### Étape 2 — Suivi des étudiants
1. Ouvrir **Suivi des étudiants** (`/prof/suivi/`).
2. Filtrer par risque « Vigilance », rechercher « Yanis », filtrer par classe.
3. Cliquer **Relancer** sur Yanis : l'objet et le message sont pré-remplis, puis envoyer.
   → Une notification est créée pour l'étudiant et un e-mail part dans la console.
4. Cliquer **Signaler** sur Yanis, choisir la priorité haute, envoyer :
   → une alerte de persévérance est créée/mise à jour et un e-mail part aux admins de l'université.
5. Vérifier que le dernier contact et l'historique de relance se mettent à jour.
6. Cliquer **Exporter** pour obtenir le CSV du portefeuille.

### Étape 3 — Rendez-vous de tutorat
1. Ouvrir **Rendez-vous de tutorat** (`/prof/tutorat/`).
2. **Créer un créneau** : date future, heure, modalité (individuel / collectif / visio).
3. Sur une demande en attente : **Accepter** → le créneau passe en réservé, un lien de visioconférence
   réellement accessible est généré (Jitsi Meet par défaut, Google Meet si configuré), et l'étudiant
   reçoit une notification et un e-mail avec le lien.
4. Sur une autre demande : **Refuser** avec un motif → l'étudiant reçoit une notification et un e-mail,
   et peut proposer un autre créneau.
5. Sur un rendez-vous confirmé : **Clôturer** avec les points abordés et les actions décidées
   → le rendez-vous passe en « Réalisé », le dernier contact du tutorat est mis à jour, le compte-rendu
   et le lien visio sont envoyés automatiquement à l'étudiant.
6. Vérifier les compteurs « cette semaine » (individuels / collectifs) et les créneaux ouverts.

### Étape 4 — Présences
1. Ouvrir **Présences** (`/prof/presences/`) ou cliquer sur **Appel** depuis l'emploi du temps.
2. Les occurrences de la semaine et les séances passées non relevées viennent de l'emploi du temps : cliquer sur **Saisir**.
3. Saisir Présent / Retard / Absent / Absence justifiée pour chaque étudiant, puis **Enregistrer**.
4. Pour un cours hors emploi du temps, utiliser **Séance exceptionnelle** (classe, module, type, date, heure, durée).
5. Le taux d'assiduité est recalculé et propagé au tutorat et aux fiches ouvertes.
6. Si un étudiant passe sous 75 %, une alerte de persévérance « Assiduité faible » est ouverte automatiquement.
7. Vérifier le tableau des taux par étudiant.

### Étape 5 — Fiches de difficulté
1. Ouvrir **Fiches & Difficultés** (`/prof/fiches-difficultes/`).
2. **Nouvelle fiche** : choisir un étudiant suivi, un type (Méthodologie, Assiduité, Charge, Orientation),
   une gravité et un constat → créer.
   → L'étudiant reçoit une notification et un e-mail d'ouverture d'accompagnement.
3. Ajouter une **note de suivi** : la fiche passe « En cours ».
4. Mettre à jour le **plan d'accompagnement**.
5. Exporter les fiches en CSV.

### Étape 6 — Journal des étudiants
1. Ouvrir **Journal de progression** (`/prof/journal-etudiants/`).
2. Sélectionner un étudiant, lire ses entrées et son niveau de confiance.
3. Écrire un **retour de tuteur** sur une entrée : il devient visible côté étudiant.

### Étape 7 — Tests de langue
1. Ouvrir **Tests de langue** (`/prof/tests-langue/`).
2. Filtrer par classe ou étudiant.
3. Ouvrir le bilan d'un test : scores, notes, recommandations et transcription.

---

## 5. Scénario administration — Sophie Bernard

Connexion : `admin.paris@u-paris.fr` / `Admin12345!` → `/administration/tableau-de-bord/`.

### Étape 1 — Tableau de bord de supervision
1. Vérifier les effectifs réels (étudiants, enseignants, classes).
2. Vérifier le taux d'affectation des référents et le nombre d'étudiants en attente.
3. Vérifier les alertes actives et le taux de persévérance.
4. Lire le tableau des cohortes : étudiants, alertes, vigilance haute, objectifs, assiduité, moyenne.
5. Consulter l'activité récente (alertes, fiches, entretiens) et les actions de remédiation.

### Étape 2 — Attribution des référents
1. Ouvrir **Attribution des tuteurs** (`/administration/perseverance/`).
2. Choisir une classe et un référent, puis **Affecter un référent** :
   → tous les étudiants de la classe sont affectés au même référent pour l'année,
   et chacun reçoit une notification « Votre référent pédagogique est désigné ».
3. Vérifier le taux d'affectation et les statuts « Complet / À compléter / Référents multiples ».
4. Exporter l'attribution en CSV.

### Étape 3 — Pilotage et alertes
1. Ouvrir **Suivi & Pilotage** (`/administration/suivi/`).
2. Filtrer les alertes ouvertes / prises en charge / clôturées.
3. **Prendre en charge** l'alerte « Absences répétées · Yanis Leroy » avec une note.
4. **Clôturer** l'alerte avec une note de résolution :
   → l'étudiant reçoit une notification et un e-mail « Votre suivi a été clôturé ».
5. Vérifier la mise à jour des cohortes, du taux de persévérance et du flux d'activité.
6. Exporter le rapport de pilotage en CSV.

### Étape 4 — Vérification transverse
1. Se reconnecter en professeur : l'alerte clôturée n'apparaît plus dans les alertes actives,
   mais reste dans l'historique du pilotage.
2. Se reconnecter en étudiante : la notification de clôture et le motif de résolution sont visibles.
3. Vérifier que le tableau de bord étudiant reflète les nouvelles heures, tâches et objectifs.

---

## 6. Scénario continu (histoire cohérente)

1. **Camille** crée un objectif « Réussir le projet web » et planifie une session.
2. Elle demande un rendez-vous à **Hélène** sur un créneau ouvert.
3. **Hélène** accepte : Camille reçoit une notification et un e-mail.
4. **Hélène** saisit les présences ; Yanis passe sous 75 %, une alerte est ouverte automatiquement.
5. **Hélène** relance Yanis et signale le décrochage ; **Sophie** reçoit l'e-mail d'alerte.
6. **Hélène** ouvre une fiche « Méthodologie » pour Yanis ; il reçoit une notification.
7. **Sophie** prend en charge puis clôture l'alerte ; Yanis reçoit la résolution.
8. **Camille** génère un plan d'étude IA, le garde, puis passe son test de langue ;
   **Hélène** consulte le bilan.
9. **Sophie** exporte le rapport de pilotage : les alertes, fiches et affectations reflètent toutes les actions.

---

## 7. Vérifications rapides

```bash
cd EduSpark
../.venv/Scripts/python.exe manage.py check
../.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
```

Les pages suivantes doivent répondre en 200 pour leurs rôles respectifs :

- `/etudiant/tableau-de-bord/`, `/etudiant/progression/`, `/etudiant/taches/`, `/etudiant/rendez-vous/`,
  `/etudiant/journal/`, `/etudiant/notifications/`, `/etudiant/tests-langue/`
- `/prof/tableau-de-bord/`, `/prof/suivi/`, `/prof/tutorat/`, `/prof/presences/`,
  `/prof/fiches-difficultes/`, `/prof/journal-etudiants/`, `/prof/tests-langue/`
- `/administration/tableau-de-bord/`, `/administration/perseverance/`, `/administration/suivi/`
