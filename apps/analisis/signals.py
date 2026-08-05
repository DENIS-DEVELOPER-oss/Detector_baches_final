"""
Limpieza de archivos en disco.

Django borra la fila de la base de datos, pero **no** los archivos asociados:
sin esto, cada analisis eliminado dejaria su imagen o su video ocupando espacio
para siempre. Con videos de decenas de MB, eso se nota rapido.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Analisis

logger = logging.getLogger(__name__)


def borrar_archivo(campo) -> bool:
    """Borra el archivo de un FileField sin tocar la base de datos."""
    if not campo:
        return False
    try:
        campo.delete(save=False)
        return True
    except Exception as exc:  # noqa: BLE001 - un archivo ya movido no es un error
        logger.warning("No se pudo borrar %s: %s", getattr(campo, "name", campo), exc)
        return False


@receiver(post_delete, sender=Analisis)
def limpiar_archivos_del_analisis(sender, instance, **kwargs):
    """Al eliminar un analisis, se llevan tambien sus archivos."""
    for campo in (instance.archivo, instance.archivo_resultado, instance.miniatura):
        borrar_archivo(campo)
