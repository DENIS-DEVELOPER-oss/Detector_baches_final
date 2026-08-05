"""
Configuracion del proyecto "Detector de Baches - Juliaca y Puno".

Base de datos: MySQL / MariaDB servido por XAMPP.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import importlib.util
import os

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# Carpeta del paquete django-leaflet. Se localiza SIN importarlo: al importarlo
# se congelaria su configuracion antes de que este archivo defina LEAFLET_CONFIG.
LEAFLET_DIR = Path(importlib.util.find_spec("leaflet").origin).resolve().parent


def env(clave, defecto=""):
    return os.getenv(clave, defecto)


def env_bool(clave, defecto=False):
    return env(clave, str(defecto)).strip().lower() in ("1", "true", "yes", "on", "si")


def env_lista(clave, defecto=""):
    return [v.strip() for v in env(clave, defecto).split(",") if v.strip()]


SECRET_KEY = env("SECRET_KEY", "clave-de-desarrollo-insegura")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_lista("ALLOWED_HOSTS", "localhost,127.0.0.1")

# Obligatorio en produccion tras HTTPS; en desarrollo no hace falta.
CSRF_TRUSTED_ORIGINS = env_lista("CSRF_TRUSTED_ORIGINS")

if not DEBUG and SECRET_KEY == "clave-de-desarrollo-insegura":
    raise ImproperlyConfigured(
        "Defina SECRET_KEY en el archivo .env antes de desplegar con DEBUG=False."
    )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Apps del proyecto
    "apps.usuarios",
    "apps.analisis",
    "apps.deteccion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if not DEBUG:
    # Sirve los estaticos de collectstatic sin nginx ni Apache delante.
    # En desarrollo lo hace runserver, y activarlo aqui solo generaria avisos
    # por la carpeta staticfiles/ que aun no existe.
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # django-leaflet no esta en INSTALLED_APPS, asi que sus plantillas
        # (leaflet/css.html, leaflet/js.html) se buscan aqui explicitamente.
        "DIRS": [BASE_DIR / "templates", LEAFLET_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.analisis.context_processors.configuracion",
            ],
            # django-leaflet se usa por sus template tags, NO como app instalada.
            # Su `admin.py` importa django.contrib.gis (GDAL/GEOS) y romperia el
            # arranque; registrando solo la libreria de tags evitamos esa parte.
            "libraries": {
                "leaflet_tags": "leaflet.templatetags.leaflet_tags",
            },
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("DB_NAME", "baches_db"),
        "USER": env("DB_USER", "root"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_USER_MODEL = "usuarios.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "usuarios:login"
LOGIN_REDIRECT_URL = "analisis:panel"
LOGOUT_REDIRECT_URL = "usuarios:login"

LANGUAGE_CODE = "es-pe"
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Igual que con las plantillas: los estaticos de django-leaflet (leaflet.js,
# leaflet.css, iconos de los marcadores) salen de su propio paquete.
STATICFILES_DIRS = [
    BASE_DIR / "static",
    LEAFLET_DIR / "static",
]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Comprime y versiona los estaticos; imprescindible para servirlos con
    # WhiteNoise sin que el navegador se quede con copias viejas.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# ---------------------------------------------------------------------------
# Seguridad en produccion
# ---------------------------------------------------------------------------
# Solo se aplica con DEBUG=False, para no estorbar en desarrollo (donde no hay
# HTTPS y las cookies seguras impedirian iniciar sesion).
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30       # 30 dias
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    # Detras de un proxy (Render, Railway, nginx) la peticion llega por HTTP
    # y solo esta cabecera revela que el cliente uso HTTPS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Subidas grandes (videos) van a disco, no a memoria
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# ---------------------------------------------------------------------------
# Deteccion (YOLO)
# ---------------------------------------------------------------------------
AI_MODELS_DIR = BASE_DIR / "ai_models"
YOLO_MODEL_PATH = AI_MODELS_DIR / env("YOLO_MODEL", "detector_baches_v2_bache_grieta.pt")
YOLO_CONF = float(env("YOLO_CONF", "0.35"))
YOLO_IMGSZ = 640

# ---------------------------------------------------------------------------
# Mapas y georreferenciacion
# ---------------------------------------------------------------------------
# Encuadre geografico por defecto (Juliaca / Puno, region Puno - Peru)
MAPA_CENTRO = {"lat": -15.6500, "lng": -70.1000, "zoom": 9}

# Con clave se usa la Google Maps JavaScript API; sin clave, django-leaflet.
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY", "").strip()

# django-leaflet: unica fuente de verdad del encuadre, los tiles y los plugins.
# No necesita GDAL/GEOS mientras no se usen campos geometricos de GeoDjango.
LEAFLET_CONFIG = {
    "DEFAULT_CENTER": (MAPA_CENTRO["lat"], MAPA_CENTRO["lng"]),
    "DEFAULT_ZOOM": MAPA_CENTRO["zoom"],
    "MIN_ZOOM": 4,
    "MAX_ZOOM": 19,
    "TILES": [
        (
            "OpenStreetMap",
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            {"attribution": "&copy; OpenStreetMap", "maxZoom": 19},
        ),
    ],
    "PLUGINS": {
        "markercluster": {
            "css": [
                "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css",
                "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css",
            ],
            "js": [
                "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js",
            ],
            "auto-include": True,
        },
    },
    "RESET_VIEW": False,
    "SCALE": "metric",
    "ATTRIBUTION_PREFIX": "Detector de Baches",
}

# geopy / Nominatim (OpenStreetMap): direccion <-> coordenadas, sin clave.
# La politica de uso de Nominatim exige identificarse y no pasar de 1 peticion
# por segundo; ambas cosas las respeta apps.analisis.geocodificacion.
NOMINATIM_USER_AGENT = env("NOMINATIM_USER_AGENT", "detector-baches-juliaca-puno")
GEOCODIFICACION_TIEMPO_LIMITE = 8      # segundos
GEOCODIFICACION_PAIS = "pe"            # sesga los resultados a Peru
GEOCODIFICACION_CACHE_SEGUNDOS = 60 * 60 * 24
