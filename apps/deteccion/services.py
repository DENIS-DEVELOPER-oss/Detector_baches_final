"""
Motor de deteccion de baches y grietas basado en YOLO (Ultralytics).

Esta capa no conoce Django: recibe rutas o bytes y devuelve objetos de valor.
Eso permite probar el modelo de forma aislada y cambiar la capa web sin tocar
la inteligencia artificial.

Diseno POO
----------
    MotorYOLO             -> Singleton: carga el modelo .pt una sola vez.
    ClasificadorSeveridad -> Regla de negocio: convierte una caja en un nivel.
    CajaDetectada         -> objeto de valor con una deteccion ya clasificada.
    ResultadoProceso      -> objeto de valor con el resultado completo.
    DetectorBase          -> clase abstracta (Strategy) con el algoritmo comun.
        DetectorImagen      -> foto subida o tomada con la camara.
        DetectorVideo       -> video subido o grabado con la camara.
        DetectorCuadro      -> un cuadro suelto (deteccion en vivo).
    FabricaDetectores     -> Factory: entrega la estrategia segun el origen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import logging
import threading
import time

from django.conf import settings

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Niveles de severidad. Se replican en apps.analisis.models.NivelSeveridad;
# aqui se usan como cadenas para que el motor no dependa del ORM.
BAJA, MEDIA, ALTA, CRITICA = "BAJA", "MEDIA", "ALTA", "CRITICA"

CLASE_BACHE = "pothole"
CLASE_GRIETA = "crack"

# Colores BGR por nivel de severidad (OpenCV usa BGR). Coinciden con la web.
COLOR_SEVERIDAD = {
    BAJA: (138, 201, 79),      # #4fc98a verde
    MEDIA: (68, 181, 245),     # #f5b544 ambar
    ALTA: (79, 112, 242),      # #f2704f naranja
    CRITICA: (43, 57, 192),    # #c0392b rojo
}
COLOR_POR_DEFECTO = (221, 200, 46)


# ---------------------------------------------------------------------------
# Clasificador de severidad
# ---------------------------------------------------------------------------
class ClasificadorSeveridad:
    """Asigna un nivel de severidad a cada dano detectado.

    Criterio (documentado para poder defenderlo):

    1. El area que el dano ocupa en el cuadro es el factor principal: un bache
       que cubre buena parte de la imagen es mas peligroso que uno lejano.
    2. Una grieta baja un nivel respecto de un bache del mismo tamano, porque
       no representa el mismo riesgo para el vehiculo.
    3. Una deteccion poco confiable tambien baja un nivel, para no exagerar la
       gravedad cuando el modelo duda.

    Los umbrales son fraccion del area del cuadro (0 a 1).
    """

    UMBRALES = ((0.010, BAJA), (0.035, MEDIA), (0.090, ALTA))
    NIVEL_MAXIMO = CRITICA
    CONFIANZA_DUDOSA = 0.45
    ESCALA = [BAJA, MEDIA, ALTA, CRITICA]

    def __init__(self, umbrales=None, confianza_dudosa=None):
        self.umbrales = umbrales or self.UMBRALES
        self.confianza_dudosa = (
            confianza_dudosa if confianza_dudosa is not None else self.CONFIANZA_DUDOSA
        )

    def clasificar(self, clase: str, confianza: float, area_relativa: float) -> str:
        nivel = self._por_area(area_relativa)

        if clase == CLASE_GRIETA:
            nivel = self._descender(nivel)
        if confianza < self.confianza_dudosa:
            nivel = self._descender(nivel)

        return nivel

    # -- Interno ------------------------------------------------------------
    def _por_area(self, area_relativa: float) -> str:
        for limite, nivel in self.umbrales:
            if area_relativa < limite:
                return nivel
        return self.NIVEL_MAXIMO

    def _descender(self, nivel: str) -> str:
        indice = self.ESCALA.index(nivel)
        return self.ESCALA[max(0, indice - 1)]


# ---------------------------------------------------------------------------
# Objetos de valor
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CajaDetectada:
    """Una deteccion con coordenadas normalizadas al rango [0, 1]."""

    clase: str
    confianza: float
    x1: float
    y1: float
    x2: float
    y2: float
    severidad: str = BAJA
    frame: int | None = None
    segundo: float | None = None

    @property
    def area_relativa(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    @property
    def es_bache(self) -> bool:
        return self.clase == CLASE_BACHE

    def como_dict(self) -> dict:
        return {
            "clase": self.clase,
            "severidad": self.severidad,
            "confianza": round(self.confianza, 4),
            "area": round(self.area_relativa, 5),
            "x1": round(self.x1, 5),
            "y1": round(self.y1, 5),
            "x2": round(self.x2, 5),
            "y2": round(self.y2, 5),
            "frame": self.frame,
            "segundo": self.segundo,
        }


@dataclass
class ResultadoProceso:
    """Resultado devuelto por cualquier detector."""

    cajas: list[CajaDetectada] = field(default_factory=list)
    ruta_salida: Path | None = None
    # Solo para video: cuadro representativo, ya anotado, para usar de portada.
    ruta_miniatura: Path | None = None
    tiempo: float = 0.0
    frames_analizados: int = 0
    error: str = ""

    @property
    def exitoso(self) -> bool:
        return not self.error

    @property
    def total(self) -> int:
        return len(self.cajas)

    def contar_clase(self, clase: str) -> int:
        return sum(1 for c in self.cajas if c.clase == clase)

    def contar_severidad(self, nivel: str) -> int:
        return sum(1 for c in self.cajas if c.severidad == nivel)

    def resumen_severidad(self) -> dict:
        return {n: self.contar_severidad(n) for n in (BAJA, MEDIA, ALTA, CRITICA)}


# ---------------------------------------------------------------------------
# Singleton del modelo
# ---------------------------------------------------------------------------
class MotorYOLO:
    """Carga perezosa y unica del modelo YOLO (thread-safe)."""

    _instancia: "MotorYOLO | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instancia is None:
            with cls._lock:
                if cls._instancia is None:
                    cls._instancia = super().__new__(cls)
                    cls._instancia._inicializado = False
        return cls._instancia

    def __init__(self, ruta_modelo: str | Path | None = None):
        if getattr(self, "_inicializado", False):
            return
        self.ruta_modelo = Path(ruta_modelo or settings.YOLO_MODEL_PATH)
        self._modelo = None
        self._carga_lock = threading.Lock()
        self._inicializado = True

    @property
    def modelo(self):
        if self._modelo is None:
            with self._carga_lock:
                if self._modelo is None:
                    if not self.ruta_modelo.exists():
                        raise FileNotFoundError(
                            f"No se encontro el modelo YOLO en: {self.ruta_modelo}"
                        )
                    from ultralytics import YOLO  # import diferido: acelera el arranque

                    logger.info("Cargando modelo YOLO: %s", self.ruta_modelo)
                    self._modelo = YOLO(str(self.ruta_modelo))
        return self._modelo

    @property
    def clases(self) -> dict:
        return self.modelo.names

    def predecir(self, imagen, conf: float | None = None):
        """Ejecuta inferencia sobre un arreglo BGR y devuelve las cajas."""
        return self.modelo.predict(
            source=imagen,
            conf=conf if conf is not None else settings.YOLO_CONF,
            imgsz=settings.YOLO_IMGSZ,
            verbose=False,
        )


# ---------------------------------------------------------------------------
# Estrategias de deteccion
# ---------------------------------------------------------------------------
class DetectorBase(ABC):
    """Plantilla comun a todas las estrategias de deteccion."""

    def __init__(self, conf: float | None = None, clasificador: ClasificadorSeveridad | None = None):
        self.motor = MotorYOLO()
        self.conf = conf if conf is not None else settings.YOLO_CONF
        self.clasificador = clasificador or ClasificadorSeveridad()

    # -- Metodo plantilla ---------------------------------------------------
    def procesar(self, entrada, ruta_salida: Path | None = None) -> ResultadoProceso:
        inicio = time.perf_counter()
        try:
            resultado = self._ejecutar(entrada, ruta_salida)
        except Exception as exc:  # noqa: BLE001 - se reporta al usuario
            logger.exception("Fallo la deteccion")
            resultado = ResultadoProceso(error=str(exc))
        resultado.tiempo = round(time.perf_counter() - inicio, 3)
        return resultado

    @abstractmethod
    def _ejecutar(self, entrada, ruta_salida: Path | None) -> ResultadoProceso:
        """Cada estrategia implementa su propio recorrido de la entrada."""

    # -- Utilidades compartidas --------------------------------------------
    def _extraer_cajas(self, resultado_yolo, alto, ancho, frame=None, segundo=None):
        cajas = []
        nombres = resultado_yolo.names

        for caja in resultado_yolo.boxes:
            x1, y1, x2, y2 = caja.xyxy[0].tolist()
            clase = nombres[int(caja.cls[0])]
            confianza = float(caja.conf[0])

            nx1, ny1 = x1 / ancho, y1 / alto
            nx2, ny2 = x2 / ancho, y2 / alto
            area = max(0.0, nx2 - nx1) * max(0.0, ny2 - ny1)

            cajas.append(
                CajaDetectada(
                    clase=clase,
                    confianza=confianza,
                    x1=nx1, y1=ny1, x2=nx2, y2=ny2,
                    severidad=self.clasificador.clasificar(clase, confianza, area),
                    frame=frame,
                    segundo=segundo,
                )
            )
        return cajas

    def _dibujar(self, imagen, cajas):
        """Pinta las cajas sobre el cuadro, coloreadas por severidad."""
        alto, ancho = imagen.shape[:2]
        grosor = max(2, int(round(min(alto, ancho) / 320)))
        escala = max(0.45, min(alto, ancho) / 950)

        for caja in cajas:
            color = COLOR_SEVERIDAD.get(caja.severidad, COLOR_POR_DEFECTO)
            p1 = (int(caja.x1 * ancho), int(caja.y1 * alto))
            p2 = (int(caja.x2 * ancho), int(caja.y2 * alto))
            cv2.rectangle(imagen, p1, p2, color, grosor)

            nombre = "Bache" if caja.es_bache else "Grieta"
            etiqueta = f"{nombre} | {caja.severidad.title()} {caja.confianza:.0%}"
            (tw, th), _ = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, escala, grosor)
            y_texto = max(p1[1], th + 8)
            cv2.rectangle(imagen, (p1[0], y_texto - th - 8), (p1[0] + tw + 8, y_texto), color, -1)
            cv2.putText(
                imagen, etiqueta, (p1[0] + 4, y_texto - 5),
                cv2.FONT_HERSHEY_SIMPLEX, escala, (255, 255, 255), grosor, cv2.LINE_AA,
            )
        return imagen


class DetectorImagen(DetectorBase):
    """Analiza una imagen (subida o tomada con la camara) y la anota."""

    def _ejecutar(self, entrada, ruta_salida):
        imagen = self._leer(entrada)
        if imagen is None:
            raise ValueError("No se pudo leer la imagen. Formato no soportado o archivo danado.")

        alto, ancho = imagen.shape[:2]
        salida_yolo = self.motor.predecir(imagen, self.conf)[0]
        cajas = self._extraer_cajas(salida_yolo, alto, ancho)

        destino = None
        if ruta_salida:
            destino = Path(ruta_salida)
            destino.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(destino), self._dibujar(imagen.copy(), cajas))

        return ResultadoProceso(cajas=cajas, ruta_salida=destino, frames_analizados=1)

    @staticmethod
    def _leer(entrada):
        if isinstance(entrada, np.ndarray):
            return entrada
        if isinstance(entrada, (bytes, bytearray)):
            return cv2.imdecode(np.frombuffer(entrada, dtype=np.uint8), cv2.IMREAD_COLOR)
        return cv2.imread(str(entrada))


class DetectorVideo(DetectorBase):
    """Recorre un video, analiza cuadros muestreados y escribe el MP4 anotado."""

    FPS_ANALISIS = 4          # cuadros analizados por segundo de video
    MAX_DETECCIONES = 400     # tope de filas que se guardan en la BD

    # Peso de cada nivel al elegir el cuadro que representa al video
    PESO_SEVERIDAD = {BAJA: 1, MEDIA: 2, ALTA: 3, CRITICA: 4}

    @classmethod
    def _puntuar(cls, cajas):
        """Cuanto 'representa' un cuadro al video: mas danos y mas graves, mejor."""
        return sum(cls.PESO_SEVERIDAD.get(c.severidad, 1) for c in cajas)

    def _ejecutar(self, entrada, ruta_salida):
        captura = cv2.VideoCapture(str(entrada))
        if not captura.isOpened():
            raise ValueError(
                "No se pudo abrir el video. Formatos recomendados: MP4 (H.264) o WEBM."
            )

        try:
            fps = captura.get(cv2.CAP_PROP_FPS)
            if not fps or fps <= 0 or fps > 240:
                fps = 25.0  # algunos WEBM del navegador no traen FPS confiable
            ancho = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
            alto = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if ancho <= 0 or alto <= 0:
                raise ValueError("El video no declara un tamano de cuadro valido.")

            paso = max(1, int(round(fps / self.FPS_ANALISIS)))

            escritor = None
            destino = None
            crudo = None
            if ruta_salida:
                destino = Path(ruta_salida)
                destino.parent.mkdir(parents=True, exist_ok=True)
                # OpenCV solo sabe escribir MPEG-4 Parte 2, que el navegador no
                # reproduce. Se escribe aparte y luego se pasa a H.264.
                crudo = destino.with_name(f"{destino.stem}_crudo.mp4")
                escritor = cv2.VideoWriter(
                    str(crudo), cv2.VideoWriter_fourcc(*"mp4v"), fps, (ancho, alto)
                )

            cajas_totales: list[CajaDetectada] = []
            ultimas: list[CajaDetectada] = []
            indice = 0
            analizados = 0

            # Mejor cuadro visto hasta ahora, para la portada del video
            mejor_puntaje = -1
            mejor_cuadro = None

            while True:
                ok, cuadro = captura.read()
                if not ok:
                    break

                analizado_ahora = indice % paso == 0
                if analizado_ahora:
                    segundo = round(indice / fps, 2)
                    salida_yolo = self.motor.predecir(cuadro, self.conf)[0]
                    ultimas = self._extraer_cajas(
                        salida_yolo, alto, ancho, frame=indice, segundo=segundo
                    )
                    cajas_totales.extend(ultimas)
                    analizados += 1

                # _dibujar modifica el cuadro en el sitio y lo devuelve
                anotado = self._dibujar(cuadro, ultimas)

                if escritor is not None:
                    escritor.write(anotado)

                # Solo compiten los cuadros realmente analizados: en los demas
                # las cajas son las del ultimo analisis y podrian no cuadrar.
                if analizado_ahora:
                    puntaje = self._puntuar(ultimas)
                    if puntaje > mejor_puntaje:
                        mejor_puntaje = puntaje
                        mejor_cuadro = anotado.copy()

                indice += 1

            if escritor is not None:
                escritor.release()

            if analizados == 0:
                raise ValueError("El video no contiene cuadros legibles.")

            self._preparar_para_navegador(crudo, destino)
            miniatura = self._guardar_miniatura(destino, mejor_cuadro)

            # Se conservan las detecciones mas confiables para no inflar la BD
            cajas_totales.sort(key=lambda c: c.confianza, reverse=True)
            return ResultadoProceso(
                cajas=cajas_totales[: self.MAX_DETECCIONES],
                ruta_salida=destino,
                ruta_miniatura=miniatura,
                frames_analizados=analizados,
            )
        finally:
            captura.release()

    @staticmethod
    def _preparar_para_navegador(crudo, destino):
        """Pasa el video de MPEG-4 Parte 2 a H.264 y borra el intermedio.

        Si ffmpeg no esta disponible, se conserva el archivo tal cual: el
        analisis sigue siendo valido aunque el navegador no lo reproduzca.
        """
        if crudo is None or destino is None or not crudo.exists():
            return

        from .video import recodificar_para_web

        if recodificar_para_web(crudo, destino):
            crudo.unlink(missing_ok=True)
        else:
            crudo.replace(destino)
            logger.warning(
                "El video %s quedo en MPEG-4 Parte 2: el navegador no podra reproducirlo.",
                destino.name,
            )

    @staticmethod
    def _guardar_miniatura(destino, cuadro):
        """Escribe la portada del video junto al archivo anotado."""
        if destino is None or cuadro is None:
            return None

        ruta = destino.with_name(f"{destino.stem}_miniatura.jpg")
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            if cv2.imwrite(str(ruta), cuadro):
                return ruta
        except Exception as exc:  # noqa: BLE001 - una portada no vale un analisis
            logger.warning("No se pudo guardar la miniatura del video: %s", exc)
        return None


class DetectorCuadro(DetectorBase):
    """Analiza un cuadro suelto llegado desde la camara (deteccion en vivo).

    No escribe archivos: devuelve las cajas para que el cliente las dibuje
    sobre un canvas, que es mucho mas fluido que reenviar la imagen anotada.
    """

    def _ejecutar(self, entrada, ruta_salida=None):
        imagen = DetectorImagen._leer(entrada)
        if imagen is None:
            raise ValueError("Cuadro invalido recibido desde la camara.")

        alto, ancho = imagen.shape[:2]
        salida_yolo = self.motor.predecir(imagen, self.conf)[0]
        cajas = self._extraer_cajas(salida_yolo, alto, ancho)
        return ResultadoProceso(cajas=cajas, frames_analizados=1)


# ---------------------------------------------------------------------------
# Fabrica
# ---------------------------------------------------------------------------
class FabricaDetectores:
    """Devuelve la estrategia correcta segun el tipo de entrada."""

    ESTRATEGIA_IMAGEN = "IMAGEN"
    ESTRATEGIA_VIDEO = "VIDEO"
    ESTRATEGIA_CUADRO = "CUADRO"

    _registro: dict[str, type[DetectorBase]] = {
        ESTRATEGIA_IMAGEN: DetectorImagen,
        ESTRATEGIA_VIDEO: DetectorVideo,
        ESTRATEGIA_CUADRO: DetectorCuadro,
    }

    EXTENSIONES_VIDEO = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

    @classmethod
    def crear(cls, estrategia: str, conf: float | None = None) -> DetectorBase:
        try:
            return cls._registro[estrategia](conf=conf)
        except KeyError as exc:
            raise ValueError(f"Estrategia de deteccion no soportada: {estrategia}") from exc

    @classmethod
    def estrategia_por_archivo(cls, nombre_archivo: str) -> str:
        """Elige entre imagen y video mirando la extension del archivo."""
        ext = Path(nombre_archivo).suffix.lower()
        if ext in cls.EXTENSIONES_VIDEO:
            return cls.ESTRATEGIA_VIDEO
        if ext in cls.EXTENSIONES_IMAGEN:
            return cls.ESTRATEGIA_IMAGEN
        raise ValueError(f"Extension no soportada: {ext or 'sin extension'}")

    @classmethod
    def estrategia_por_archivo_seguro(cls, nombre_archivo: str) -> str | None:
        """Como `estrategia_por_archivo`, pero devuelve None en vez de fallar.

        Util cuando solo se quiere saber que pestana mostrar y una extension
        desconocida no debe interrumpir nada.
        """
        try:
            return cls.estrategia_por_archivo(nombre_archivo)
        except ValueError:
            return None

    @classmethod
    def extensiones_validas(cls) -> set[str]:
        return cls.EXTENSIONES_IMAGEN | cls.EXTENSIONES_VIDEO
