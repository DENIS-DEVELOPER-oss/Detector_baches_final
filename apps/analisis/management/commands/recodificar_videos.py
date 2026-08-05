"""
Convierte a H.264 los videos anotados que el navegador no puede reproducir.

OpenCV los escribia en MPEG-4 Parte 2 (fourcc FMP4), que Chrome, Edge y Firefox
no decodifican: el reproductor se queda congelado en 0:00. Este comando los pasa
a H.264 con ffmpeg, sin volver a ejecutar el modelo.

Uso:
    python manage.py recodificar_videos
    python manage.py recodificar_videos --revisar   # solo informa, no toca nada
    python manage.py recodificar_videos --todos     # tambien los ya compatibles
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from apps.analisis.models import Analisis, TipoOrigen
from apps.deteccion.video import (
    codec_de, recodificar_para_web, reproducible_en_navegador, ruta_ffmpeg,
)


class Command(BaseCommand):
    help = "Recodifica a H.264 los videos anotados que el navegador no reproduce."

    def add_arguments(self, parser):
        parser.add_argument("--revisar", action="store_true",
                            help="Solo informa del estado de cada video.")
        parser.add_argument("--todos", action="store_true",
                            help="Recodifica incluso los que ya son compatibles.")

    def handle(self, *args, **opciones):
        if not opciones["revisar"] and not ruta_ffmpeg():
            self.stdout.write(self.style.ERROR(
                "No se encontro ffmpeg. Instale imageio-ffmpeg:\n"
                "    pip install imageio-ffmpeg"
            ))
            return

        videos = (
            Analisis.objects
            .filter(origen__in=[TipoOrigen.VIDEO, TipoOrigen.VIDEO_CAMARA])
            .exclude(archivo_resultado="")
            .exclude(archivo_resultado__isnull=True)
        )
        if not videos:
            self.stdout.write("No hay videos analizados.")
            return

        convertidos = compatibles = fallidos = 0

        for analisis in videos:
            try:
                ruta = Path(analisis.archivo_resultado.path)
            except (ValueError, NotImplementedError):
                continue
            if not ruta.exists():
                self.stdout.write(self.style.WARNING(f"  ? {analisis.codigo}: falta el archivo"))
                continue

            compatible = reproducible_en_navegador(ruta)
            etiqueta = f"{analisis.codigo} [{codec_de(ruta)}]"

            if opciones["revisar"]:
                estado = "reproducible" if compatible else "NO reproducible en navegador"
                estilo = self.style.SUCCESS if compatible else self.style.WARNING
                self.stdout.write(estilo(f"  {etiqueta}: {estado}"))
                continue

            if compatible and not opciones["todos"]:
                compatibles += 1
                self.stdout.write(f"  = {etiqueta}: ya era compatible")
                continue

            temporal = ruta.with_name(f"{ruta.stem}_h264.mp4")
            if recodificar_para_web(ruta, temporal):
                temporal.replace(ruta)
                convertidos += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  + {etiqueta} -> {codec_de(ruta)} ({ruta.stat().st_size // 1024} KB)"
                ))
            else:
                temporal.unlink(missing_ok=True)
                fallidos += 1
                self.stdout.write(self.style.ERROR(f"  x {etiqueta}: no se pudo convertir"))

        if not opciones["revisar"]:
            self.stdout.write(self.style.SUCCESS(
                f"\nListo. {convertidos} convertido(s), {compatibles} ya compatible(s), "
                f"{fallidos} con error."
            ))
