"""
Recodificacion de los videos anotados a un formato que el navegador reproduzca.

El problema
-----------
`cv2.VideoWriter` con el fourcc `mp4v` produce MPEG-4 Parte 2 (FMP4). Es valido
y cualquier reproductor de escritorio lo abre, pero **Chrome, Edge y Firefox no
lo decodifican**: el reproductor se queda en 0:00 y no pasa nada.

Los codecs que si aceptan dentro de un MP4 son H.264 (avc1), HEVC y AV1.
opencv-python no trae el codificador de H.264 por licencia, asi que el video se
escribe primero con OpenCV y despues se recodifica con ffmpeg.

ffmpeg llega con `imageio-ffmpeg`, que ya viene entre las dependencias de
ultralytics; si faltara, se conserva el archivo original y solo se avisa.
"""

from __future__ import annotations

from pathlib import Path
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

TIEMPO_LIMITE = 900  # segundos; un video largo puede tardar

# En Windows evita que parpadee una consola por cada llamada
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ruta_ffmpeg() -> str | None:
    """Devuelve el ejecutable de ffmpeg disponible, o None si no hay ninguno."""
    del_sistema = shutil.which("ffmpeg")
    if del_sistema:
        return del_sistema

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - sin ffmpeg simplemente no se recodifica
        return None


def recodificar_para_web(origen: Path, destino: Path) -> bool:
    """Convierte `origen` a H.264 en `destino`. Devuelve si lo consiguio.

    - `yuv420p` es el espacio de color que entienden todos los navegadores.
    - El filtro de escala fuerza dimensiones pares: H.264 no admite impares.
    - `+faststart` mueve el indice al principio para que empiece a reproducirse
      sin descargar el archivo entero.
    """
    ejecutable = ruta_ffmpeg()
    if not ejecutable:
        logger.warning("No hay ffmpeg: el video quedara en un formato que el navegador no abre.")
        return False

    destino.parent.mkdir(parents=True, exist_ok=True)
    orden = [
        ejecutable, "-y", "-loglevel", "error",
        "-i", str(origen),
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",                       # el analisis no necesita audio
        str(destino),
    ]

    try:
        proceso = subprocess.run(
            orden, capture_output=True, timeout=TIEMPO_LIMITE, creationflags=_SIN_VENTANA
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg tardo demasiado recodificando %s", origen.name)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo ejecutar ffmpeg: %s", exc)
        return False

    if proceso.returncode != 0:
        logger.warning(
            "ffmpeg fallo con %s: %s", origen.name,
            proceso.stderr.decode("utf-8", "replace")[:300],
        )
        return False

    return destino.exists() and destino.stat().st_size > 0


def codec_de(ruta: Path) -> str:
    """Fourcc del video, util para diagnosticar por que no se reproduce."""
    import cv2

    captura = cv2.VideoCapture(str(ruta))
    if not captura.isOpened():
        return "?"
    codigo = int(captura.get(cv2.CAP_PROP_FOURCC))
    captura.release()
    return "".join(chr((codigo >> 8 * i) & 0xFF) for i in range(4)).strip()


def reproducible_en_navegador(ruta: Path) -> bool:
    """Heuristica rapida: mira si el contenedor declara un codec compatible."""
    try:
        cabecera = ruta.open("rb").read(400_000)
    except OSError:
        return False
    return any(marca in cabecera for marca in (b"avc1", b"hev1", b"av01", b"vp09", b"vp08"))
