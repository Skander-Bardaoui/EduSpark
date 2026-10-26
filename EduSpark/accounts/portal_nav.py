from .models import Profil

ROLE_META = {
    Profil.ROLE_ETUDIANT: {
        "label": "Étudiant",
        "portal_label": "Portail Étudiant",
        "home_url_name": "coaching:student_dashboard",
        "profile_url_name": "portal:student_profile",
        "notifications": (
            {
                "icon": "assignment",
                "title": "Nouveau devoir en Systèmes Distribués",
                "detail": "À rendre avant vendredi, 23 h 59.",
                "url_name": "exercises:student_assignments",
            },
            {
                "icon": "grade",
                "title": "Note publiée : Algorithmique avancée",
                "detail": "Votre note du TP 2 est disponible.",
                "url_name": "exams:student_transcript",
            },
            {
                "icon": "forum",
                "title": "Réponse sur le forum",
                "detail": "Une réponse à votre question sur les réseaux de neurones.",
                "url_name": "community:student_forums",
            },
        ),
    },
    Profil.ROLE_PROF: {
        "label": "Enseignant",
        "portal_label": "Portail Enseignant",
        "home_url_name": "coaching:prof_dashboard",
        "profile_url_name": "portal:prof_profile",
        "notifications": (
            {
                "icon": "draw",
                "title": "14 copies urgentes à corriger",
                "detail": "Jury INF501 dans 3 jours.",
                "url_name": "exams:prof_corrections",
            },
            {
                "icon": "forum",
                "title": "3 questions sans réponse",
                "detail": "Forums de vos cours, en attente depuis 24 h.",
                "url_name": "community:prof_forums",
            },
            {
                "icon": "support_agent",
                "title": "Tutorat demain à 16 h 30",
                "detail": "Entretien individuel avec Camille Martin.",
                "url_name": "coaching:prof_tutoring",
            },
        ),
    },
    Profil.ROLE_ADMIN: {
        "label": "Administration",
        "portal_label": "Portail Administration",
        "home_url_name": "coaching:admin_dashboard",
        "profile_url_name": "portal:admin_profile",
        "notifications": (
            {
                "icon": "mark_email_read",
                "title": "12 invitations en attente",
                "detail": "Dont 4 invitations expirant sous 48 h.",
                "url_name": "portal:admin_invitations",
            },
            {
                "icon": "warning",
                "title": "5 signalements à modérer",
                "detail": "Priorité haute sur le forum INFO501.",
                "url_name": "community:admin_reports",
            },
            {
                "icon": "event_available",
                "title": "Sessions d’examen à valider",
                "detail": "3 sessions attendent votre approbation.",
                "url_name": "exams:admin_exam_sessions",
            },
        ),
    },
}

NAV_SECTIONS = {
    Profil.ROLE_ETUDIANT: (
        {
            "label": "Tableau de bord",
            "items": (
                {"label": "Mon Tableau de bord", "icon": "home", "url_name": "coaching:student_dashboard"},
            ),
        },
        {
            "label": "Cours",
            "items": (
                {"label": "Catalogue des cours", "icon": "menu_book", "url_name": "courses:student_catalogue"},
                {"label": "Supports de cours", "icon": "folder_shared", "url_name": "courses:student_course_materials"},
                {"label": "Mon Emploi du temps", "icon": "calendar_month", "url_name": "courses:student_timetable"},
            ),
        },
        {
            "label": "Exercices",
            "items": (
                {"label": "Mes Devoirs", "icon": "assignment", "url_name": "exercises:student_assignments"},
                {"label": "S'entraîner", "icon": "model_training", "url_name": "exercises:student_practice"},
            ),
        },
        {
            "label": "Examens & Notes",
            "items": (
                {"label": "Mes Examens", "icon": "history_edu", "url_name": "exams:student_exams"},
                {"label": "Mes Relevés de notes", "icon": "grade", "url_name": "exams:student_transcript"},
            ),
        },
        {
            "label": "Échanges",
            "items": (
                {"label": "Annonces", "icon": "campaign", "url_name": "community:student_announcements"},
                {"label": "Forums & Questions", "icon": "forum", "url_name": "community:student_forums"},
                {"label": "Messagerie", "icon": "chat_bubble_outline", "url_name": "community:student_messages"},
            ),
        },
        {
            "label": "Suivi & Progression",
            "items": (
                {"label": "Mes Objectifs & Plans", "icon": "flag", "url_name": "coaching:student_progress"},
                {"label": "Mes Tâches", "icon": "check_circle_outline", "url_name": "coaching:student_tasks"},
                {"label": "Mes Rendez-vous", "icon": "event_available", "url_name": "coaching:student_appointments"},
                {"label": "Journal de progression", "icon": "monitoring", "url_name": "coaching:student_journal"},
                {"label": "Test de langue", "icon": "record_voice_over", "url_name": "coaching:student_language_tests"},
            ),
        },
    ),
    Profil.ROLE_PROF: (
        {
            "label": "Tableau de bord",
            "items": (
                {"label": "Mon Tableau de bord", "icon": "space_dashboard", "url_name": "coaching:prof_dashboard"},
            ),
        },
        {
            "label": "Cours",
            "items": (
                {"label": "Mes Cours", "icon": "menu_book", "url_name": "courses:prof_course"},
                {"label": "Supports de cours", "icon": "folder_shared", "url_name": "courses:prof_course_materials"},
                {"label": "Emploi du temps", "icon": "calendar_month", "url_name": "courses:prof_timetable"},
                {"label": "Gestion des matières", "icon": "auto_stories", "url_name": "courses:prof_subjects"},
            ),
        },
        {
            "label": "Exercices",
            "items": (
                {"label": "Banque d'exercices", "icon": "quiz", "url_name": "exercises:prof_exercise_bank"},
                {"label": "Devoirs créés", "icon": "assignment", "url_name": "exercises:prof_assignments"},
                {"label": "Séries & Barèmes", "icon": "checklist", "url_name": "exercises:prof_rubrics"},
            ),
        },
        {
            "label": "Examens & Notes",
            "items": (
                {"label": "Sessions d'examen", "icon": "event_available", "url_name": "exams:prof_exam_sessions"},
                {"label": "Copies à corriger", "icon": "draw", "url_name": "exams:prof_corrections"},
                {"label": "Relevés & Jurys", "icon": "fact_check", "url_name": "exams:prof_grade_sheets"},
            ),
        },
        {
            "label": "Échanges",
            "items": (
                {"label": "Annonces", "icon": "campaign", "url_name": "community:prof_announcements"},
                {"label": "Forums & Questions", "icon": "forum", "url_name": "community:prof_forums"},
                {"label": "Messagerie", "icon": "mail", "url_name": "community:prof_messages"},
                {"label": "Modération", "icon": "gavel", "url_name": "community:prof_moderation"},
            ),
        },
        {
            "label": "Suivi Référent",
            "items": (
                {"label": "Tableau de bord étudiants", "icon": "monitoring", "url_name": "coaching:prof_followup"},
                {"label": "Fiches & Difficultés", "icon": "person_search", "url_name": "coaching:prof_followup_cards"},
                {"label": "Rendez-vous de tutorat", "icon": "support_agent", "url_name": "coaching:prof_tutoring"},
                {"label": "Journal de progression", "icon": "trending_up", "url_name": "coaching:prof_student_journal"},
                {"label": "Tests de langue", "icon": "record_voice_over", "url_name": "coaching:prof_language_tests"},
            ),
        },
    ),
    Profil.ROLE_ADMIN: (
        {
            "label": "Tableau de bord",
            "items": (
                {"label": "Mon Tableau de bord Admin", "icon": "dashboard", "url_name": "coaching:admin_dashboard"},
            ),
        },
        {
            "label": "Utilisateurs & Organisation",
            "items": (
                {"label": "Enseignants & Chercheurs", "icon": "school", "url_name": "portal:admin_teachers"},
                {"label": "Étudiants & Inscriptions", "icon": "group", "url_name": "portal:admin_students"},
                {"label": "Classes, Groupes & Promos", "icon": "layers", "url_name": "portal:admin_classes"},
                {"label": "Invitations & Rôles", "icon": "mark_email_read", "url_name": "portal:admin_invitations"},
                {"label": "Profil de l'Université", "icon": "corporate_fare", "url_name": "portal:admin_university"},
            ),
        },
        {
            "label": "Plateforme",
            "items": (
                {"label": "Universités", "icon": "account_balance", "url_name": "portal:admin_universities",
                 "platform_only": True, "tenant_free": True},
                {"label": "Comptes & Accès", "icon": "manage_accounts", "url_name": "portal:admin_accounts",
                 "platform_only": True, "tenant_free": True},
                {"label": "Paramètres de la plateforme", "icon": "settings",
                 "url_name": "portal:admin_platform_settings", "platform_only": True, "tenant_free": True},
            ),
        },
        {
            "label": "Cours & Catalogue",
            "items": (
                {"label": "Départements & Filières", "icon": "account_tree", "url_name": "courses:admin_program_offer"},
                {"label": "Tous les cours", "icon": "menu_book", "url_name": "courses:admin_courses"},
                {"label": "Emploi du temps global", "icon": "calendar_today", "url_name": "courses:admin_timetable"},
            ),
        },
        {
            "label": "Exercices & Évaluations",
            "items": (
                {"label": "Supervision des Banques", "icon": "fact_check", "url_name": "exercises:admin_exercise_banks"},
                {"label": "Catégories & Niveaux", "icon": "tune", "url_name": "exercises:admin_categories"},
            ),
        },
        {
            "label": "Examens & Notes",
            "items": (
                {"label": "Sessions d'examen", "icon": "event_available", "url_name": "exams:admin_exam_sessions"},
                {"label": "Relevés officiels & Jurys", "icon": "workspace_premium", "url_name": "exams:admin_official_records", "related_url_names": ("exams:admin_grade_record_detail",)},
                {"label": "Statistiques & réussite", "icon": "insights", "url_name": "exams:admin_statistics"},
            ),
        },
        {
            "label": "Échanges & Modération",
            "items": (
                {"label": "Annonces institutionnelles", "icon": "campaign", "url_name": "community:admin_communication"},
                {"label": "Supervision des forums", "icon": "forum", "url_name": "community:admin_forum_supervision"},
                {"label": "Signalements & Modération", "icon": "warning", "url_name": "community:admin_reports"},
            ),
        },
        {
            "label": "Suivi & Pilotage",
            "items": (
                {"label": "Tableau de bord de suivi", "icon": "monitoring", "url_name": "coaching:admin_monitoring"},
                {"label": "Attribution des tuteurs", "icon": "how_to_reg", "url_name": "coaching:admin_perseverance"},
            ),
        },
    ),
}
