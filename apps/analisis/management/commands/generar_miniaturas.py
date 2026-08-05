"""
Genera la portada de los videos analizados antes de que existiera el campo.

No vuelve a ejecutar YOLO: el video anotado ya tiene las cajas dibujadas y la
base de datos ya sabe en que cuadro aparecio cada dano. Basta con elegir el
mejor cuadro y extraerlo.

Uso:
    python manage.py generar_miniaturas
    python manage.py generar_miniaturas --rehacer   # tambien los que ya tienen
"""

from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

import cv2

from apps.analisis.models import Analisis, TipoOrigen

PESO_SEVERIDAD = {"BAJA": 1, "MEDIA": 2, "ALTA": 3, "CRITICA": 4}


class Command(BaseCommand):
    help = "Crea la miniatura de los analisis de video que no la tengan."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rehacer", action="store_true",
            help="Regenera tambien las miniaturas ya existentes.",
        )

    def handle(self, *args, **opciones):
        videos = (
            Analisis.objects.filter(origen__in=[TipoOrigen.VIDEO, TipoOrigen.VIDEO_CAMARA])
            .exclude(archivo_resultado="")
            .exclude(archivo_resultado__isnull=True)
        )

        if not opciones["rehacer"]:
            # El campo admite nulos, asi que las filas anteriores a la migracion
            # traen NULL y no cadena vacia: hay que contemplar los dos casos.
            videos = videos.filter(Q(miniatura="") | Q(miniatura__isnull=True))

        total = videos.count()
        if not total:
            self.stdout.write("No hay videos pendientes de miniatura.")
            return

        self.stdout.write(f"Videos por procesar: {total}\n")
        hechas = fallidas = 0

        for analisis in videos:
            resultado = self._procesar(analisis)
            if resultado:
                hechas += 1
                self.stdout.write(self.style.SUCCESS(f"  + {analisis.codigo}: {resultado}"))
            else:
                fallidas += 1
                self.stdout.write(self.style.WARNING(f"  - {analisis.codigo}: no se pudo generar"))

        self.stdout.write(
            self.style.SUCCESS(f"\nListo. {hechas} miniatura(s) creada(s), {fallidas} sin generar.")
        )

    # -- Interno ------------------------------------------------------------
    def _procesar(self, analisis):
        try:
            ruta_video = Path(analisis.archivo_resultado.path)
        except (ValueError, NotImplementedError):
            return None
        if not ruta_video.exists():
            return None

        captura = cv2.VideoCapture(str(ruta_video))
        if not captura.isOpened():
            return None

        try:
            cuadros = int(captura.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            objetivo = self._mejor_cuadro(analisis, cuadros)

            captura.set(cv2.CAP_PROP_POS_FRAMES, objetivo)
            ok, imagen = captura.read()
            if not ok:
                # Algunos contenedores no permiten saltar: se lee desde el inicio
                captura.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, imagen = captura.read()
            if not ok or imagen is None:
                return None

            destino = (
                Path(settings.MEDIA_ROOT) / "analisis" / "miniaturas"
                / f"{analisis.creado_en:%Y}" / f"{analisis.creado_en:%m}"
                / f"{analisis.codigo}_miniatura.jpg"
            )
            destino.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(destino), imagen):
                return None

            analisis.miniatura.name = destino.relative_to(Path(settings.MEDIA_ROOT)).as_posix()
            analisis.save(update_fields=["miniatura", "actualizado_en"])
            return f"cuadro {objetivo}"
        finally:
            captura.release()

    @staticmethod
    def _mejor_cuadro(analisis, total_cuadros):
        """Cuadro con mas danos y mas graves; si no hay datos, uno intermedio."""
        puntajes = defaultdict(int)
        for numero, severidad in analisis.baches.exclude(frame__isnull=True).values_list(
            "frame", "severidad"
        ):
            puntajes[numero] += PESO_SEVERIDAD.get(severidad, 1)

        if puntajes:
            mejor = max(puntajes, key=puntajes.get)
            if total_cuadros <= 0 or mejor < total_cuadros:
                return mejor
        return max(0, total_cuadros // 3)
