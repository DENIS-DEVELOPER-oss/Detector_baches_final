from django.apps import AppConfig


class AnalisisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analisis"
    label = "analisis"
    verbose_name = "Analisis y baches detectados"

    def ready(self):
        # Registra la limpieza de archivos al eliminar un analisis
        from . import signals  # noqa: F401
