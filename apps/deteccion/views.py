"""
Modulo de deteccion: las cinco formas de alimentar al modelo de IA.

    1. Subir una imagen desde el dispositivo.
    2. Subir un video desde el dispositivo.
    3. Tomar una fotografia con la camara.
    4. Grabar un video con la camara.
    5. Deteccion en vivo (analisis continuo de la camara).

Los cinco caminos terminan en el mismo lugar: un `Analisis` guardado, con sus
baches clasificados por severidad.
"""

import base64
import binascii
import uuid

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.analisis.exif import coordenadas_exif
from apps.analisis.models import Analisis, TipoOrigen, Zona
from apps.analisis.services import ProcesadorAnalisis

from .forms import CapturaCamaraForm, SubirArchivoForm
from .services import FabricaDetectores, MotorYOLO

TAMANO_MAXIMO_CUADRO = 8 * 1024 * 1024        # 8 MB por cuadro en vivo
TAMANO_MAXIMO_GRABACION = 100 * 1024 * 1024   # 100 MB por grabacion


# ---------------------------------------------------------------------------
# Utilidades compartidas
# ---------------------------------------------------------------------------
def decodificar_data_url(valor: str, maximo: int = TAMANO_MAXIMO_CUADRO) -> bytes:
    """Convierte un `data:image/jpeg;base64,...` del navegador en bytes."""
    if not valor:
        raise ValueError("No se recibio ninguna imagen.")
    if "," in valor:
        valor = valor.split(",", 1)[1]
    try:
        datos = base64.b64decode(valor, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("La imagen recibida no es valida.") from exc
    if len(datos) > maximo:
        raise ValueError("La imagen recibida es demasiado grande.")
    return datos


class GuardarAnalisisMixin(LoginRequiredMixin):
    """Crea el `Analisis`, lo manda al modelo y avisa al usuario."""

    def crear_y_procesar(self, request, form, contenido: bytes, nombre: str, origen: str):
        analisis = form.save(commit=False)
        analisis.usuario = request.user
        analisis.origen = origen
        if not analisis.titulo:
            analisis.titulo = self.titulo_por_defecto(origen, analisis.zona)
        marcado_a_mano = form.cleaned_data.get("latitud") is not None
        analisis.archivo.save(nombre, ContentFile(contenido), save=False)
        analisis.save()
        self.georreferenciar_por_exif(request, analisis, marcado_a_mano)

        resultado = ProcesadorAnalisis(analisis).ejecutar()
        self.avisar(request, analisis, resultado)
        return analisis

    @staticmethod
    def titulo_por_defecto(origen, zona):
        etiqueta = TipoOrigen(origen).label
        return f"{etiqueta} - {zona.nombre}" if zona else etiqueta

    @staticmethod
    def georreferenciar_por_exif(request, analisis, marcado_a_mano):
        """Usa las coordenadas GPS de la foto cuando el usuario no marco el punto.

        Si marco un punto en el mapa, manda su eleccion. Si solo eligio una zona,
        el analisis quedo con el centro del sector: el GPS de la foto es mas
        preciso, asi que lo sustituye.
        """
        if marcado_a_mano:
            return False

        try:
            coordenadas = coordenadas_exif(analisis.archivo.path)
        except Exception:  # noqa: BLE001 - nunca debe impedir guardar el analisis
            return False

        if not coordenadas:
            return False

        analisis.latitud, analisis.longitud = coordenadas
        analisis.save(update_fields=["latitud", "longitud", "actualizado_en"])
        messages.info(
            request,
            "Se tomo la ubicacion de los datos GPS de la foto. "
            "Puede corregirla desde el analisis.",
        )
        return True

    @staticmethod
    def avisar(request, analisis, resultado):
        if not resultado.exitoso:
            messages.warning(
                request,
                f"El analisis {analisis.codigo} se guardo, pero la deteccion fallo: "
                f"{resultado.error}",
            )
        elif resultado.total == 0:
            messages.info(
                request,
                f"Analisis {analisis.codigo} completado en {resultado.tiempo} s. "
                f"El modelo no encontro danos viales.",
            )
        else:
            resumen = resultado.resumen_severidad()
            detalle = ", ".join(f"{n.title()}: {c}" for n, c in resumen.items() if c)
            messages.success(
                request,
                f"Analisis {analisis.codigo}: {resultado.total} dano(s) detectado(s) "
                f"en {resultado.tiempo} s. Severidad -> {detalle}.",
            )


# ---------------------------------------------------------------------------
# Pagina del modulo
# ---------------------------------------------------------------------------
def contexto_modulo(request, **sobrescribir):
    """Contexto de la pagina del modulo, reutilizable al remostrar errores."""
    ctx = {
        "form_archivo": SubirArchivoForm(),
        "form_captura": CapturaCamaraForm(prefix="foto"),
        "form_grabacion": CapturaCamaraForm(prefix="video"),
        "form_vivo": CapturaCamaraForm(prefix="vivo"),
        "zonas_json": list(
            Zona.objects.filter(activa=True).values("id", "nombre", "ciudad", "latitud", "longitud")
        ),
        "modo_inicial": request.GET.get("modo", "imagen"),
    }
    ctx.update(sobrescribir)
    return ctx


class ModuloDeteccionView(LoginRequiredMixin, TemplateView):
    """Pagina unica con las cinco formas de detectar."""

    template_name = "deteccion/modulo.html"

    def get_context_data(self, **kwargs):
        return contexto_modulo(self.request, **super().get_context_data(**kwargs))


# ---------------------------------------------------------------------------
# 1 y 2. Subir imagen o video
# ---------------------------------------------------------------------------
class SubirArchivoView(GuardarAnalisisMixin, View):
    def post(self, request):
        form = SubirArchivoForm(request.POST, request.FILES)
        if not form.is_valid():
            # Se vuelve a pintar el modulo con el formulario enlazado: asi el
            # error sale junto a su campo y no se pierde lo ya escrito. Antes se
            # redirigia con un mensaje generico y parecia que no pasaba nada.
            messages.error(
                request, "No se pudo analizar: revise los campos marcados en rojo."
            )
            modo = "imagen"
            subido = request.FILES.get("archivo")
            if subido and FabricaDetectores.estrategia_por_archivo_seguro(subido.name) == (
                FabricaDetectores.ESTRATEGIA_VIDEO
            ):
                modo = "video"
            return render(
                request,
                "deteccion/modulo.html",
                contexto_modulo(request, form_archivo=form, modo_inicial=modo),
            )

        archivo = form.cleaned_data["archivo"]
        estrategia = FabricaDetectores.estrategia_por_archivo(archivo.name)
        origen = (
            TipoOrigen.VIDEO
            if estrategia == FabricaDetectores.ESTRATEGIA_VIDEO
            else TipoOrigen.IMAGEN
        )

        analisis = form.save(commit=False)
        analisis.usuario = request.user
        analisis.origen = origen
        if not analisis.titulo:
            analisis.titulo = self.titulo_por_defecto(origen, analisis.zona)

        marcado_a_mano = form.cleaned_data.get("latitud") is not None
        analisis.save()
        self.georreferenciar_por_exif(request, analisis, marcado_a_mano)

        resultado = ProcesadorAnalisis(analisis).ejecutar()
        self.avisar(request, analisis, resultado)
        return redirect(analisis)


# ---------------------------------------------------------------------------
# 3. Tomar una fotografia con la camara
# ---------------------------------------------------------------------------
class CapturarFotoView(GuardarAnalisisMixin, View):
    def post(self, request):
        form = CapturaCamaraForm(request.POST, prefix="foto")
        if not form.is_valid():
            messages.error(request, "Revise los datos de la captura.")
            return redirect("deteccion:modulo")

        try:
            imagen = decodificar_data_url(request.POST.get("captura", ""))
        except ValueError as exc:
            messages.error(request, f"No se pudo guardar la foto: {exc}")
            return redirect("deteccion:modulo")

        analisis = self.crear_y_procesar(
            request, form, imagen,
            f"foto_{uuid.uuid4().hex[:10]}.jpg",
            TipoOrigen.FOTO_CAMARA,
        )
        return redirect(analisis)


# ---------------------------------------------------------------------------
# 4. Grabar un video con la camara
# ---------------------------------------------------------------------------
class GrabarVideoView(GuardarAnalisisMixin, View):
    EXTENSIONES = {"video/webm": ".webm", "video/mp4": ".mp4"}

    def post(self, request):
        form = CapturaCamaraForm(request.POST, prefix="video")
        if not form.is_valid():
            messages.error(request, "Revise los datos de la grabacion.")
            return redirect("deteccion:modulo")

        grabacion = request.FILES.get("grabacion")
        if grabacion is None:
            messages.error(request, "No se recibio ninguna grabacion.")
            return redirect("deteccion:modulo")
        if grabacion.size > TAMANO_MAXIMO_GRABACION:
            messages.error(request, "La grabacion supera los 100 MB.")
            return redirect("deteccion:modulo")

        extension = self.EXTENSIONES.get((grabacion.content_type or "").split(";")[0], ".webm")
        analisis = self.crear_y_procesar(
            request, form, grabacion.read(),
            f"grabacion_{uuid.uuid4().hex[:10]}{extension}",
            TipoOrigen.VIDEO_CAMARA,
        )
        return redirect(analisis)


# ---------------------------------------------------------------------------
# 5. Deteccion en vivo
# ---------------------------------------------------------------------------
class AnalizarCuadroView(LoginRequiredMixin, View):
    """Recibe un cuadro de la camara y devuelve las cajas ya clasificadas."""

    def post(self, request):
        try:
            datos = self._leer_cuadro(request)
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)

        detector = FabricaDetectores.crear(FabricaDetectores.ESTRATEGIA_CUADRO)
        resultado = detector.procesar(datos)

        if not resultado.exitoso:
            return JsonResponse({"ok": False, "error": resultado.error}, status=500)

        return JsonResponse(
            {
                "ok": True,
                "tiempo": resultado.tiempo,
                "total": resultado.total,
                "baches": resultado.contar_clase("pothole"),
                "grietas": resultado.contar_clase("crack"),
                "severidad": resultado.resumen_severidad(),
                "cajas": [c.como_dict() for c in resultado.cajas],
            }
        )

    @staticmethod
    def _leer_cuadro(request) -> bytes:
        archivo = request.FILES.get("frame")
        if archivo is not None:
            if archivo.size > TAMANO_MAXIMO_CUADRO:
                raise ValueError("El cuadro enviado es demasiado grande.")
            return archivo.read()
        return decodificar_data_url(request.POST.get("frame", ""))


class GuardarDeteccionVivoView(GuardarAnalisisMixin, View):
    """Congela el cuadro actual de la deteccion en vivo y lo guarda."""

    def post(self, request):
        form = CapturaCamaraForm(request.POST, prefix="vivo")
        if not form.is_valid():
            messages.error(request, "Revise los datos de la deteccion en vivo.")
            return redirect("deteccion:modulo")

        try:
            imagen = decodificar_data_url(request.POST.get("captura", ""))
        except ValueError as exc:
            messages.error(request, f"No se pudo guardar el cuadro: {exc}")
            return redirect("deteccion:modulo")

        analisis = self.crear_y_procesar(
            request, form, imagen,
            f"vivo_{uuid.uuid4().hex[:10]}.jpg",
            TipoOrigen.VIVO,
        )
        return redirect(analisis)


# ---------------------------------------------------------------------------
# Diagnostico
# ---------------------------------------------------------------------------
class EstadoModeloView(LoginRequiredMixin, View):
    """Confirma que el archivo .pt carga y expone sus clases."""

    def get(self, request):
        motor = MotorYOLO()
        try:
            return JsonResponse(
                {"ok": True, "modelo": motor.ruta_modelo.name, "clases": motor.clases}
            )
        except Exception as exc:  # noqa: BLE001
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)
