"""
Capa de servicio: conecta un `Analisis` con el motor de deteccion.

Mantiene las vistas delgadas y concentra la transaccion "analizar y persistir".
"""

from __future__ import annotations

from pathlib import Path
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.deteccion.services import FabricaDetectores, ResultadoProceso

from .models import Analisis, Bache

logger = logging.getLogger(__name__)


class ProcesadorAnalisis:
    """Ejecuta la deteccion sobre el archivo de un analisis y guarda el resultado."""

    def __init__(self, analisis: Analisis, conf: float | None = None):
        self.analisis = analisis
        self.conf = conf

    # -- API publica --------------------------------------------------------
    def ejecutar(self) -> ResultadoProceso:
        # La estrategia se elige por el archivo real, no por el origen: una foto
        # tomada con la camara llega como JPEG y se analiza igual que una imagen.
        estrategia = FabricaDetectores.estrategia_por_archivo(self.analisis.archivo.name)
        detector = FabricaDetectores.crear(estrategia, conf=self.conf)

        ruta_entrada = Path(self.analisis.archivo.path)
        ruta_salida = self._ruta_salida(estrategia)

        resultado = detector.procesar(ruta_entrada, ruta_salida)

        if resultado.exitoso:
            self._persistir(resultado)
        else:
            self.analisis.error_proceso = resultado.error
            self.analisis.procesado = False
            self.analisis.tiempo_proceso = resultado.tiempo
            self.analisis.save(
                update_fields=["error_proceso", "procesado", "tiempo_proceso", "actualizado_en"]
            )
        return resultado

    # -- Interno ------------------------------------------------------------
    def _ruta_salida(self, estrategia: str) -> Path:
        sufijo = ".mp4" if estrategia == FabricaDetectores.ESTRATEGIA_VIDEO else ".jpg"
        ahora = timezone.now()
        carpeta = (
            Path(settings.MEDIA_ROOT) / "analisis" / "resultados" / f"{ahora:%Y}" / f"{ahora:%m}"
        )
        return carpeta / f"{self.analisis.codigo}_detectado{sufijo}"

    @staticmethod
    def _descartar_anterior(campo, ruta_nueva) -> None:
        """Borra el archivo previo solo si el nuevo se escribio en otra ruta.

        Si coinciden, el detector ya lo sobrescribio: borrarlo eliminaria el
        resultado que se acaba de generar.
        """
        if not campo or not ruta_nueva:
            return
        from .signals import borrar_archivo

        try:
            if Path(campo.path).resolve() != Path(ruta_nueva).resolve():
                borrar_archivo(campo)
        except (ValueError, OSError):
            pass

    @transaction.atomic
    def _persistir(self, resultado: ResultadoProceso) -> None:
        self.analisis.baches.all().delete()

        # Al reprocesar, el archivo anterior quedaria huerfano si la ruta nueva
        # es distinta (la carpeta lleva ano y mes, asi que cambia con el tiempo).
        self._descartar_anterior(self.analisis.archivo_resultado, resultado.ruta_salida)
        self._descartar_anterior(self.analisis.miniatura, resultado.ruta_miniatura)

        Bache.objects.bulk_create(
            [
                Bache(
                    analisis=self.analisis,
                    clase=caja.clase,
                    severidad=caja.severidad,
                    confianza=caja.confianza,
                    x1=caja.x1, y1=caja.y1, x2=caja.x2, y2=caja.y2,
                    area_relativa=caja.area_relativa,
                    frame=caja.frame,
                    segundo=caja.segundo,
                )
                for caja in resultado.cajas
            ]
        )

        if resultado.ruta_salida and resultado.ruta_salida.exists():
            relativa = resultado.ruta_salida.relative_to(Path(settings.MEDIA_ROOT))
            self.analisis.archivo_resultado.name = relativa.as_posix()

        if resultado.ruta_miniatura and resultado.ruta_miniatura.exists():
            relativa = resultado.ruta_miniatura.relative_to(Path(settings.MEDIA_ROOT))
            self.analisis.miniatura.name = relativa.as_posix()

        self.analisis.procesado = True
        self.analisis.error_proceso = ""
        self.analisis.tiempo_proceso = resultado.tiempo
        self.analisis.frames_analizados = resultado.frames_analizados
        self.analisis.save(
            update_fields=[
                "archivo_resultado", "miniatura", "procesado", "error_proceso",
                "tiempo_proceso", "frames_analizados", "actualizado_en",
            ]
        )
        self.analisis.recalcular_resumen()
