"""
Modelos del dominio: zonas, analisis realizados y baches detectados.

El sistema no gestiona reportes ciudadanos ni flujos de trabajo: cada registro
es el resultado de pasar una imagen, un video o un cuadro de camara por el
modelo de inteligencia artificial.

Diseno POO
----------
    RegistroBase (abstracta)   -> marcas de tiempo comunes
        Zona                   -> sector de Juliaca o Puno
        Analisis               -> una ejecucion del modelo; agrega N Bache
        Bache                  -> un dano detectado, con su nivel de severidad
"""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


# ---------------------------------------------------------------------------
# Enumeraciones del dominio
# ---------------------------------------------------------------------------
class Ciudad(models.TextChoices):
    JULIACA = "JULIACA", "Juliaca"
    PUNO = "PUNO", "Puno"


class TipoOrigen(models.TextChoices):
    """Las cinco formas de alimentar al modelo desde el modulo de deteccion."""

    IMAGEN = "IMAGEN", "Imagen subida"
    VIDEO = "VIDEO", "Video subido"
    FOTO_CAMARA = "FOTO_CAMARA", "Foto tomada con la camara"
    VIDEO_CAMARA = "VIDEO_CAMARA", "Video grabado con la camara"
    VIVO = "VIVO", "Deteccion en vivo"


class TipoDano(models.TextChoices):
    """Clases que produce el modelo YOLO entrenado."""

    BACHE = "pothole", "Bache"
    GRIETA = "crack", "Grieta"


# Orden de gravedad. Vive fuera del TextChoices a proposito: cualquier atributo
# de clase dentro de un Choices se convertiria en un miembro mas del enum.
ORDEN_SEVERIDAD = ["BAJA", "MEDIA", "ALTA", "CRITICA"]


class NivelSeveridad(models.TextChoices):
    """Clasificacion automatica de cada dano detectado."""

    BAJA = "BAJA", "Baja"
    MEDIA = "MEDIA", "Media"
    ALTA = "ALTA", "Alta"
    CRITICA = "CRITICA", "Critica"

    @classmethod
    def peso(cls, nivel):
        """Posicion en la escala de gravedad; -1 si el nivel no es valido."""
        try:
            return ORDEN_SEVERIDAD.index(str(nivel))
        except ValueError:
            return -1

    @classmethod
    def maxima(cls, niveles):
        """Devuelve el nivel mas grave de una coleccion (None si esta vacia)."""
        validos = [n for n in niveles if str(n) in ORDEN_SEVERIDAD]
        return max(validos, key=cls.peso) if validos else None


COLOR_SEVERIDAD = {
    NivelSeveridad.BAJA: "success",
    NivelSeveridad.MEDIA: "warning",
    NivelSeveridad.ALTA: "orange",
    NivelSeveridad.CRITICA: "danger",
}

HEX_SEVERIDAD = {
    NivelSeveridad.BAJA: "#4fc98a",
    NivelSeveridad.MEDIA: "#f5b544",
    NivelSeveridad.ALTA: "#f2704f",
    NivelSeveridad.CRITICA: "#c0392b",
}


# ---------------------------------------------------------------------------
# Base abstracta
# ---------------------------------------------------------------------------
class RegistroBase(models.Model):
    creado_en = models.DateTimeField("Creado en", auto_now_add=True)
    actualizado_en = models.DateTimeField("Actualizado en", auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Zona geografica
# ---------------------------------------------------------------------------
class Zona(RegistroBase):
    """Distrito, urbanizacion o sector dentro de Juliaca / Puno."""

    nombre = models.CharField("Nombre", max_length=100)
    ciudad = models.CharField("Ciudad", max_length=10, choices=Ciudad.choices)
    latitud = models.DecimalField("Latitud", max_digits=10, decimal_places=7)
    longitud = models.DecimalField("Longitud", max_digits=10, decimal_places=7)
    descripcion = models.CharField("Descripcion", max_length=200, blank=True)
    activa = models.BooleanField("Activa", default=True)

    class Meta:
        db_table = "zona"
        verbose_name = "Zona"
        verbose_name_plural = "Zonas"
        ordering = ["ciudad", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["ciudad", "nombre"], name="zona_unica_por_ciudad")
        ]

    def __str__(self):
        return f"{self.nombre} - {self.get_ciudad_display()}"

    @property
    def total_analisis(self):
        return self.analisis.count()


# ---------------------------------------------------------------------------
# Analisis
# ---------------------------------------------------------------------------
class AnalisisQuerySet(models.QuerySet):
    """Consultas reutilizables; evita repetir filtros en las vistas."""

    def procesados(self):
        return self.filter(procesado=True)

    def con_danos(self):
        return self.filter(total_detecciones__gt=0)

    def geolocalizados(self):
        return self.filter(latitud__isnull=False, longitud__isnull=False)

    def de_ciudad(self, ciudad):
        return self.filter(zona__ciudad=ciudad) if ciudad else self

    def de_severidad(self, nivel):
        return self.filter(severidad_maxima=nivel) if nivel else self

    def visibles_para(self, usuario):
        """El ciudadano ve solo su historial; el administrador ve todo."""
        if usuario.is_authenticated and usuario.puede_ver_todas_las_detecciones():
            return self
        return self.filter(usuario=usuario)


class Analisis(RegistroBase):
    """Una ejecucion del modelo sobre un archivo o un cuadro de camara."""

    codigo = models.CharField("Codigo", max_length=20, unique=True, editable=False)
    titulo = models.CharField("Titulo", max_length=140)
    descripcion = models.TextField("Descripcion", blank=True)

    origen = models.CharField(
        "Origen", max_length=14, choices=TipoOrigen.choices, default=TipoOrigen.IMAGEN
    )
    archivo = models.FileField("Archivo analizado", upload_to="analisis/originales/%Y/%m/")
    archivo_resultado = models.FileField(
        "Archivo con detecciones", upload_to="analisis/resultados/%Y/%m/", blank=True, null=True
    )
    # Solo para video: cuadro con mas danos, ya anotado. Un video no se puede
    # mostrar como portada en las tarjetas, y el icono generico no dice nada.
    miniatura = models.ImageField(
        "Miniatura", upload_to="analisis/miniaturas/%Y/%m/", blank=True, null=True
    )

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Analizado por",
        on_delete=models.CASCADE,
        related_name="analisis",
    )

    zona = models.ForeignKey(
        Zona,
        verbose_name="Zona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analisis",
    )
    direccion_referencia = models.CharField("Direccion / referencia", max_length=200, blank=True)
    latitud = models.DecimalField(
        "Latitud", max_digits=10, decimal_places=7, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitud = models.DecimalField(
        "Longitud", max_digits=10, decimal_places=7, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    # Resultado del modelo (desnormalizado; se recalcula tras procesar)
    procesado = models.BooleanField("Procesado por IA", default=False)
    error_proceso = models.TextField("Error de proceso", blank=True)
    tiempo_proceso = models.FloatField("Tiempo de proceso (s)", default=0.0)
    frames_analizados = models.PositiveIntegerField("Cuadros analizados", default=0)

    total_detecciones = models.PositiveIntegerField("Total de danos", default=0)
    total_baches = models.PositiveIntegerField("Baches", default=0)
    total_grietas = models.PositiveIntegerField("Grietas", default=0)

    sev_baja = models.PositiveIntegerField("Severidad baja", default=0)
    sev_media = models.PositiveIntegerField("Severidad media", default=0)
    sev_alta = models.PositiveIntegerField("Severidad alta", default=0)
    sev_critica = models.PositiveIntegerField("Severidad critica", default=0)

    severidad_maxima = models.CharField(
        "Severidad maxima", max_length=10, choices=NivelSeveridad.choices, blank=True
    )
    severidad_predominante = models.CharField(
        "Severidad predominante", max_length=10, choices=NivelSeveridad.choices, blank=True
    )

    confianza_promedio = models.FloatField("Confianza promedio", default=0.0)
    area_danada_pct = models.FloatField("Area danada (%)", default=0.0)

    objects = AnalisisQuerySet.as_manager()

    class Meta:
        db_table = "analisis"
        verbose_name = "Analisis"
        verbose_name_plural = "Analisis"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["severidad_maxima"]),
            models.Index(fields=["origen"]),
            models.Index(fields=["-creado_en"]),
        ]

    def __str__(self):
        return f"{self.codigo} - {self.titulo}"

    def get_absolute_url(self):
        return reverse("analisis:detalle", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = self._generar_codigo()
        if self.latitud is None and self.zona_id:
            self.latitud = self.zona.latitud
            self.longitud = self.zona.longitud
        super().save(*args, **kwargs)

    @staticmethod
    def _generar_codigo():
        return f"DET-{timezone.now():%Y%m}-{uuid.uuid4().hex[:6].upper()}"

    # -- Presentacion -------------------------------------------------------
    @property
    def color_severidad(self):
        return COLOR_SEVERIDAD.get(self.severidad_maxima, "secondary")

    @property
    def hex_severidad(self):
        return HEX_SEVERIDAD.get(self.severidad_maxima, "#ced5dc")

    @property
    def tiene_ubicacion(self):
        return self.latitud is not None and self.longitud is not None

    @property
    def es_video(self):
        return self.origen in (TipoOrigen.VIDEO, TipoOrigen.VIDEO_CAMARA)

    @property
    def viene_de_camara(self):
        return self.origen in (TipoOrigen.FOTO_CAMARA, TipoOrigen.VIDEO_CAMARA, TipoOrigen.VIVO)

    @property
    def imagen_previa(self):
        """Imagen que representa al analisis en listados y tarjetas.

        Para un video es la miniatura del cuadro con mas danos; para una foto,
        la version anotada, y si algo falta, el archivo original.
        """
        if self.es_video:
            return self.miniatura or None
        return self.archivo_resultado or self.archivo or None

    @property
    def icono_origen(self):
        return {
            TipoOrigen.IMAGEN: "bi-image",
            TipoOrigen.VIDEO: "bi-film",
            TipoOrigen.FOTO_CAMARA: "bi-camera",
            TipoOrigen.VIDEO_CAMARA: "bi-record-circle",
            TipoOrigen.VIVO: "bi-broadcast",
        }.get(self.origen, "bi-file-earmark")

    def conteo_por_severidad(self):
        """Lista lista para graficar: nivel, etiqueta, total, porcentaje, color."""
        totales = {
            NivelSeveridad.BAJA: self.sev_baja,
            NivelSeveridad.MEDIA: self.sev_media,
            NivelSeveridad.ALTA: self.sev_alta,
            NivelSeveridad.CRITICA: self.sev_critica,
        }
        total = self.total_detecciones or 0
        return [
            {
                "nivel": nivel,
                "etiqueta": NivelSeveridad(nivel).label,
                "total": cantidad,
                "porcentaje": round(cantidad * 100 / total, 1) if total else 0.0,
                "color": COLOR_SEVERIDAD[nivel],
                "hex": HEX_SEVERIDAD[nivel],
            }
            for nivel, cantidad in totales.items()
        ]

    # -- Reglas de negocio --------------------------------------------------
    def recalcular_resumen(self, guardar=True):
        """Recalcula contadores y severidades a partir de sus baches."""
        danos = self.baches.all()

        self.total_detecciones = danos.count()
        self.total_baches = danos.filter(clase=TipoDano.BACHE).count()
        self.total_grietas = danos.filter(clase=TipoDano.GRIETA).count()

        self.sev_baja = danos.filter(severidad=NivelSeveridad.BAJA).count()
        self.sev_media = danos.filter(severidad=NivelSeveridad.MEDIA).count()
        self.sev_alta = danos.filter(severidad=NivelSeveridad.ALTA).count()
        self.sev_critica = danos.filter(severidad=NivelSeveridad.CRITICA).count()

        conteos = {
            NivelSeveridad.BAJA: self.sev_baja,
            NivelSeveridad.MEDIA: self.sev_media,
            NivelSeveridad.ALTA: self.sev_alta,
            NivelSeveridad.CRITICA: self.sev_critica,
        }
        presentes = [nivel for nivel, cantidad in conteos.items() if cantidad]
        self.severidad_maxima = NivelSeveridad.maxima(presentes) or ""
        # Ante empate gana el nivel mas grave.
        self.severidad_predominante = (
            max(presentes, key=lambda n: (conteos[n], NivelSeveridad.peso(n))) if presentes else ""
        )

        agregado = danos.aggregate(
            promedio=models.Avg("confianza"), area=models.Sum("area_relativa")
        )
        self.confianza_promedio = round(agregado["promedio"] or 0.0, 4)
        self.area_danada_pct = round(min((agregado["area"] or 0.0) * 100, 100.0), 2)

        if guardar:
            self.save(
                update_fields=[
                    "total_detecciones", "total_baches", "total_grietas",
                    "sev_baja", "sev_media", "sev_alta", "sev_critica",
                    "severidad_maxima", "severidad_predominante",
                    "confianza_promedio", "area_danada_pct", "actualizado_en",
                ]
            )
        return self


# ---------------------------------------------------------------------------
# Bache detectado
# ---------------------------------------------------------------------------
class BacheQuerySet(models.QuerySet):
    def baches(self):
        return self.filter(clase=TipoDano.BACHE)

    def grietas(self):
        return self.filter(clase=TipoDano.GRIETA)

    def de_nivel(self, nivel):
        return self.filter(severidad=nivel) if nivel else self

    def visibles_para(self, usuario):
        if usuario.is_authenticated and usuario.puede_ver_todas_las_detecciones():
            return self
        return self.filter(analisis__usuario=usuario)


class Bache(models.Model):
    """Un dano detectado por YOLO, con su severidad ya clasificada."""

    analisis = models.ForeignKey(
        Analisis, verbose_name="Analisis", on_delete=models.CASCADE, related_name="baches"
    )
    clase = models.CharField("Tipo de dano", max_length=20, choices=TipoDano.choices)
    severidad = models.CharField("Severidad", max_length=10, choices=NivelSeveridad.choices)
    confianza = models.FloatField("Confianza")

    # Caja delimitadora normalizada a [0, 1]
    x1 = models.FloatField("X1")
    y1 = models.FloatField("Y1")
    x2 = models.FloatField("X2")
    y2 = models.FloatField("Y2")
    area_relativa = models.FloatField("Area relativa", default=0.0)

    # Solo para video: numero y segundo del cuadro donde aparecio
    frame = models.PositiveIntegerField("Cuadro", null=True, blank=True)
    segundo = models.FloatField("Segundo", null=True, blank=True)

    detectado_en = models.DateTimeField("Detectado en", auto_now_add=True)

    objects = BacheQuerySet.as_manager()

    class Meta:
        db_table = "bache"
        verbose_name = "Bache detectado"
        verbose_name_plural = "Baches detectados"
        ordering = ["-confianza"]
        indexes = [
            models.Index(fields=["clase"]),
            models.Index(fields=["severidad"]),
        ]

    def __str__(self):
        return f"{self.get_clase_display()} {self.get_severidad_display()} ({self.confianza:.0%})"

    @property
    def confianza_pct(self):
        return round(self.confianza * 100, 1)

    @property
    def area_pct(self):
        return round(self.area_relativa * 100, 2)

    @property
    def color_severidad(self):
        return COLOR_SEVERIDAD.get(self.severidad, "secondary")

    def save(self, *args, **kwargs):
        self.area_relativa = max(0.0, (self.x2 - self.x1)) * max(0.0, (self.y2 - self.y1))
        super().save(*args, **kwargs)
