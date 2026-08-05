"""
Georreferenciacion con geopy sobre Nominatim (OpenStreetMap).

Resuelve las dos direcciones del problema:

    direccion  ->  coordenadas   (`buscar`)
    coordenadas -> direccion     (`direccion_de`)

No necesita clave de API. A cambio, Nominatim exige identificarse con un
`user_agent` propio y no pasar de una peticion por segundo: de eso se encargan
`RateLimiter` y la cache.

Diseno POO
----------
    GeocodificadorBase (abstracta) -> contrato + cache comun
        GeocodificadorNominatim    -> implementacion sobre OpenStreetMap

Si algun dia se cambia a Google Geocoding o Mapbox, basta con otra subclase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
import logging
import threading

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class ErrorGeocodificacion(Exception):
    """El servicio de geocodificacion no pudo responder."""


@dataclass(frozen=True)
class Lugar:
    """Un resultado de busqueda ya normalizado."""

    direccion: str
    latitud: float
    longitud: float

    def como_dict(self) -> dict:
        return {
            "direccion": self.direccion,
            "latitud": round(self.latitud, 7),
            "longitud": round(self.longitud, 7),
        }


class GeocodificadorBase(ABC):
    """Contrato comun a cualquier proveedor de geocodificacion."""

    PREFIJO_CACHE = "geo"

    @abstractmethod
    def _buscar(self, texto: str, limite: int) -> list[Lugar]:
        """Busca lugares que coincidan con el texto."""

    @abstractmethod
    def _direccion_de(self, latitud: float, longitud: float) -> str | None:
        """Devuelve la direccion legible de un punto."""

    # -- API publica (con cache) -------------------------------------------
    def buscar(self, texto: str, limite: int = 5) -> list[Lugar]:
        texto = (texto or "").strip()
        if len(texto) < 3:
            return []

        clave = self._clave("b", texto.lower(), limite)
        guardado = cache.get(clave)
        if guardado is not None:
            return [Lugar(**d) for d in guardado]

        lugares = self._buscar(texto, limite)
        cache.set(clave, [l.__dict__ for l in lugares], settings.GEOCODIFICACION_CACHE_SEGUNDOS)
        return lugares

    def direccion_de(self, latitud: float, longitud: float) -> str | None:
        # 5 decimales ~ 1 m: suficiente para que la cache acierte
        clave = self._clave("i", round(latitud, 5), round(longitud, 5))
        guardado = cache.get(clave)
        if guardado is not None:
            return guardado or None

        direccion = self._direccion_de(latitud, longitud)
        cache.set(clave, direccion or "", settings.GEOCODIFICACION_CACHE_SEGUNDOS)
        return direccion

    @classmethod
    def _clave(cls, *partes) -> str:
        crudo = "|".join(str(p) for p in partes)
        return f"{cls.PREFIJO_CACHE}:{hashlib.md5(crudo.encode()).hexdigest()}"


class GeocodificadorNominatim(GeocodificadorBase):
    """Nominatim (OpenStreetMap). Singleton: una sola sesion por proceso."""

    _instancia: "GeocodificadorNominatim | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instancia is None:
            with cls._lock:
                if cls._instancia is None:
                    cls._instancia = super().__new__(cls)
                    cls._instancia._inicializado = False
        return cls._instancia

    def __init__(self):
        if getattr(self, "_inicializado", False):
            return

        from geopy.extra.rate_limiter import RateLimiter
        from geopy.geocoders import Nominatim

        self._servicio = Nominatim(
            user_agent=settings.NOMINATIM_USER_AGENT,
            timeout=settings.GEOCODIFICACION_TIEMPO_LIMITE,
        )
        # Nominatim permite 1 peticion por segundo como maximo.
        self._geocodificar = RateLimiter(self._servicio.geocode, min_delay_seconds=1)
        self._inverso = RateLimiter(self._servicio.reverse, min_delay_seconds=1)
        self._inicializado = True

    def _buscar(self, texto, limite):
        from geopy.exc import GeocoderServiceError

        try:
            crudos = self._geocodificar(
                texto,
                exactly_one=False,
                limit=limite,
                country_codes=settings.GEOCODIFICACION_PAIS,
                addressdetails=False,
            )
        except GeocoderServiceError as exc:
            logger.warning("Nominatim no respondio: %s", exc)
            raise ErrorGeocodificacion(
                "El servicio de busqueda de direcciones no esta disponible."
            ) from exc

        return [
            Lugar(direccion=r.address, latitud=r.latitude, longitud=r.longitude)
            for r in (crudos or [])
        ]

    def _direccion_de(self, latitud, longitud):
        from geopy.exc import GeocoderServiceError

        try:
            resultado = self._inverso((latitud, longitud), exactly_one=True, zoom=18)
        except GeocoderServiceError as exc:
            logger.warning("Nominatim (inverso) no respondio: %s", exc)
            raise ErrorGeocodificacion(
                "El servicio de direcciones no esta disponible."
            ) from exc

        return resultado.address if resultado else None


def obtener_geocodificador() -> GeocodificadorBase:
    """Punto unico de acceso; facilita cambiar de proveedor o simularlo."""
    return GeocodificadorNominatim()
