"""
Diagnostico del modelo desde la terminal, sin pasar por la web.

Responde a "el detector no encuentra nada": dice si el problema es la foto, el
umbral de confianza o el modelo elegido.

Uso:
    python manage.py probar_deteccion C:\\ruta\\a\\una\\foto.jpg
    python manage.py probar_deteccion foto.jpg --todos-los-modelos
    python manage.py probar_deteccion foto.jpg --conf 0.15
    python manage.py probar_deteccion foto.jpg --guardar salida.jpg
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.deteccion.services import (
    ClasificadorSeveridad, DetectorImagen, FabricaDetectores, MotorYOLO,
)

UMBRALES = [0.50, 0.35, 0.25, 0.15, 0.05]


class Command(BaseCommand):
    help = "Prueba el modelo YOLO sobre una imagen o un video y muestra que encuentra."

    def add_arguments(self, parser):
        parser.add_argument("ruta", help="Imagen o video a analizar.")
        parser.add_argument(
            "--todos-los-modelos", action="store_true",
            help="Compara los tres archivos .pt de ai_models/.",
        )
        parser.add_argument(
            "--conf", type=float, default=None,
            help="Umbral de confianza (por defecto, el de YOLO_CONF).",
        )
        parser.add_argument(
            "--guardar", default=None,
            help="Ruta donde escribir el archivo anotado.",
        )

    def handle(self, *args, **opciones):
        ruta = Path(opciones["ruta"]).expanduser()
        if not ruta.exists():
            raise CommandError(f"No existe el archivo: {ruta}")

        try:
            estrategia = FabricaDetectores.estrategia_por_archivo(ruta.name)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.MIGRATE_HEADING("Configuracion"))
        self.stdout.write(f"  Modelo activo : {settings.YOLO_MODEL_PATH.name}")
        self.stdout.write(f"  Confianza     : {settings.YOLO_CONF}")
        self.stdout.write(f"  Tamano imagen : {settings.YOLO_IMGSZ}")
        self.stdout.write(f"  Archivo       : {ruta.name} ({ruta.stat().st_size // 1024} KB)")
        self.stdout.write(f"  Estrategia    : {estrategia}\n")

        if opciones["todos_los_modelos"]:
            self._comparar_modelos(ruta, estrategia)
            return

        self._analizar(ruta, estrategia, opciones["conf"], opciones["guardar"])

    # -- Un solo modelo -----------------------------------------------------
    def _analizar(self, ruta, estrategia, conf, guardar):
        detector = FabricaDetectores.crear(estrategia, conf=conf)
        resultado = detector.procesar(ruta, Path(guardar) if guardar else None)

        if not resultado.exitoso:
            self.stdout.write(self.style.ERROR(f"Fallo el analisis: {resultado.error}"))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Resultado"))
        self.stdout.write(f"  Tiempo            : {resultado.tiempo} s")
        self.stdout.write(f"  Cuadros analizados: {resultado.frames_analizados}")
        self.stdout.write(f"  Danos encontrados : {resultado.total}")

        if not resultado.total:
            self.stdout.write(self.style.WARNING(
                "\n  El modelo no encontro nada con este umbral.\n"
                "  Pruebe a bajarlo:  python manage.py probar_deteccion "
                f"\"{ruta}\" --conf 0.15\n"
                "  O compare los modelos:  --todos-los-modelos"
            ))
            self._barrido(ruta, estrategia)
            return

        self.stdout.write(f"  Baches            : {resultado.contar_clase('pothole')}")
        self.stdout.write(f"  Grietas           : {resultado.contar_clase('crack')}")
        self.stdout.write("  Severidad         : " + ", ".join(
            f"{n}={c}" for n, c in resultado.resumen_severidad().items() if c
        ))

        self.stdout.write(self.style.MIGRATE_HEADING("\nDetalle"))
        for i, caja in enumerate(sorted(resultado.cajas, key=lambda c: -c.confianza)[:15], 1):
            momento = f" | seg {caja.segundo}" if caja.segundo is not None else ""
            self.stdout.write(
                f"  {i:>2}. {caja.clase:<8} conf {caja.confianza:.1%} | "
                f"severidad {caja.severidad:<8} | area {caja.area_relativa * 100:.2f}%{momento}"
            )

        if guardar and resultado.ruta_salida:
            self.stdout.write(self.style.SUCCESS(f"\nArchivo anotado: {resultado.ruta_salida}"))

    # -- Barrido de umbrales ------------------------------------------------
    def _barrido(self, ruta, estrategia):
        self.stdout.write(self.style.MIGRATE_HEADING("\nBarrido de umbrales"))
        for umbral in UMBRALES:
            detector = FabricaDetectores.crear(estrategia, conf=umbral)
            r = detector.procesar(ruta)
            marca = "<-- aqui empieza a detectar" if r.total else ""
            self.stdout.write(f"  conf >= {umbral:<5} danos = {r.total:<3} {marca}")

    # -- Comparativa de modelos --------------------------------------------
    def _comparar_modelos(self, ruta, estrategia):
        modelos = sorted(Path(settings.AI_MODELS_DIR).glob("*.pt"))
        if not modelos:
            raise CommandError(f"No hay modelos .pt en {settings.AI_MODELS_DIR}")

        clasificador = ClasificadorSeveridad()
        self.stdout.write(self.style.MIGRATE_HEADING("Comparativa de modelos"))

        for archivo in modelos:
            # Se instancia el motor sin pasar por el singleton para no
            # contaminar el modelo que usa la aplicacion.
            motor = object.__new__(MotorYOLO)
            motor.ruta_modelo = archivo
            motor._modelo = None
            import threading
            motor._carga_lock = threading.Lock()
            motor._inicializado = True

            detector = DetectorImagen.__new__(DetectorImagen)
            detector.motor = motor
            detector.clasificador = clasificador

            self.stdout.write(f"\n  {archivo.name}  clases={motor.clases}")
            for umbral in UMBRALES:
                detector.conf = umbral
                r = detector.procesar(ruta)
                if not r.exitoso:
                    self.stdout.write(self.style.ERROR(f"    conf {umbral}: {r.error}"))
                    continue
                mejor = max((c.confianza for c in r.cajas), default=0.0)
                self.stdout.write(
                    f"    conf >= {umbral:<5} danos = {r.total:<3} "
                    f"mejor = {mejor:.1%}"
                )
