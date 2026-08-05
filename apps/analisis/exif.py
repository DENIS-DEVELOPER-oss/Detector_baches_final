"""
Lectura de coordenadas GPS incrustadas en una fotografia (EXIF).

Casi todas las fotos tomadas con un celular con la ubicacion activada llevan
sus coordenadas dentro del archivo. Aprovecharlas evita que el usuario tenga
que marcar el punto a mano.

No lanza excepciones: si la foto no trae GPS, o viene corrupta, devuelve None.
Georreferenciar es una comodidad, nunca un motivo para perder un analisis.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ETIQUETA_GPS = 34853  # GPSInfo, segun la especificacion EXIF

# Claves dentro del bloque GPSInfo
LAT_REF, LAT, LNG_REF, LNG = 1, 2, 3, 4


def _a_grados(valor) -> float | None:
    """Convierte (grados, minutos, segundos) de EXIF a grados decimales."""
    try:
        grados, minutos, segundos = (float(v) for v in valor)
    except (TypeError, ValueError):
        return None
    return grados + minutos / 60 + segundos / 3600


def coordenadas_exif(ruta) -> tuple[float, float] | None:
    """Devuelve (latitud, longitud) de la foto, o None si no las trae."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return None

    try:
        with Image.open(ruta) as imagen:
            exif = imagen.getexif()
            if not exif:
                return None
            gps = exif.get_ifd(ETIQUETA_GPS)
    except Exception as exc:  # noqa: BLE001 - una foto ilegible no es un error fatal
        logger.debug("No se pudo leer el EXIF de %s: %s", ruta, exc)
        return None

    if not gps or LAT not in gps or LNG not in gps:
        return None

    latitud = _a_grados(gps[LAT])
    longitud = _a_grados(gps[LNG])
    if latitud is None or longitud is None:
        return None

    # El hemisferio va en una etiqueta aparte
    if str(gps.get(LAT_REF, "N")).upper().startswith("S"):
        latitud = -latitud
    if str(gps.get(LNG_REF, "E")).upper().startswith("W"):
        longitud = -longitud

    # Un GPS en (0, 0) es casi siempre basura, no el golfo de Guinea
    if abs(latitud) < 1e-6 and abs(longitud) < 1e-6:
        return None
    if not (-90 <= latitud <= 90) or not (-180 <= longitud <= 180):
        return None

    return round(latitud, 7), round(longitud, 7)
