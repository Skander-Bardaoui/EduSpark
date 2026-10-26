from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "courses"
    verbose_name = "Cours et emplois du temps"

    def ready(self):
        from . import signals  # noqa: F401  (branche les signaux)
