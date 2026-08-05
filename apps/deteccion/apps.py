from django.apps import AppConfig


class DeteccionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.deteccion"
    label = "deteccion"
    verbose_name = "Motor de deteccion YOLO"
