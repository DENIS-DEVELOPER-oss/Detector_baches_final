"""
Vistas de consulta: dashboard por severidad, historial, detalle, mapa y
estadisticas. El alta de datos vive en el modulo de deteccion.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Avg, Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import FiltroAnalisisForm, UbicacionForm
from .geocodificacion import ErrorGeocodificacion, obtener_geocodificador
from .models import (
    COLOR_SEVERIDAD, HEX_SEVERIDAD, Analisis, Bache, NivelSeveridad,
    TipoDano, TipoOrigen, Zona,
)
from .services import ProcesadorAnalisis


class AdminRequeridoMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restringe la vista al administrador."""

    def test_func(self):
        return self.request.user.puede_administrar()

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "Solo el administrador puede acceder a esa seccion.")
            return redirect("analisis:panel")
        return super().handle_no_permission()


class ResumenSeveridadMixin:
    """Calcula el desglose por severidad de un conjunto de baches."""

    @staticmethod
    def desglose(baches):
        conteo = dict(
            baches.values_list("severidad").annotate(n=Count("id")).values_list("severidad", "n")
        )
        total = sum(conteo.values())
        return [
            {
                "nivel": nivel,
                "etiqueta": NivelSeveridad(nivel).label,
                "total": conteo.get(nivel, 0),
                "porcentaje": round(conteo.get(nivel, 0) * 100 / total, 1) if total else 0.0,
                "color": COLOR_SEVERIDAD[nivel],
                "hex": HEX_SEVERIDAD[nivel],
            }
            for nivel in NivelSeveridad.values
        ], total


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class PanelView(LoginRequiredMixin, ResumenSeveridadMixin, TemplateView):
    template_name = "analisis/panel.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        usuario = self.request.user

        analisis = Analisis.objects.visibles_para(usuario)
        baches = Bache.objects.visibles_para(usuario)

        ctx["es_admin"] = usuario.puede_administrar()
        ctx["total_analisis"] = analisis.count()
        ctx["total_danos"] = baches.count()
        ctx["total_baches"] = baches.baches().count()
        ctx["total_grietas"] = baches.grietas().count()
        ctx["geolocalizados"] = analisis.geolocalizados().count()
        ctx["confianza"] = round((baches.aggregate(c=Avg("confianza"))["c"] or 0) * 100, 1)
        ctx["tiempo_medio"] = round(analisis.aggregate(t=Avg("tiempo_proceso"))["t"] or 0, 2)

        desglose, total = self.desglose(baches)
        ctx["desglose"] = desglose
        ctx["por_nivel"] = {d["nivel"]: d for d in desglose}
        ctx["total_clasificados"] = total

        ctx["por_origen"] = [
            {
                "origen": fila["origen"],
                "etiqueta": TipoOrigen(fila["origen"]).label,
                "total": fila["total"],
                "danos": fila["danos"] or 0,
            }
            for fila in analisis.values("origen").annotate(
                total=Count("id"), danos=Sum("total_detecciones")
            ).order_by("-total")
        ]

        ctx["ranking_zonas"] = list(
            Zona.objects.filter(analisis__in=analisis)
            .annotate(total=Count("analisis", distinct=True), danos=Sum("analisis__total_detecciones"))
            .filter(total__gt=0)
            .order_by("-danos", "-total")[:8]
        )

        ctx["serie_mensual"] = self._serie_mensual(analisis)
        ctx["historial"] = analisis.select_related("zona", "usuario")[:8]
        return ctx

    @staticmethod
    def _serie_mensual(analisis, meses=12):
        """Analisis y danos por mes.

        Se agrupa en Python a proposito: MariaDB de XAMPP no trae cargadas las
        tablas de zonas horarias, asi que TruncMonth no puede convertir fechas.
        """
        acumulado = {}
        for creado_en, danos in analisis.values_list("creado_en", "total_detecciones"):
            clave = timezone.localtime(creado_en).strftime("%Y-%m")
            registro = acumulado.setdefault(clave, {"mes": clave, "total": 0, "danos": 0})
            registro["total"] += 1
            registro["danos"] += danos or 0
        return [acumulado[k] for k in sorted(acumulado)][-meses:]


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------
class HistorialListView(LoginRequiredMixin, ListView):
    model = Analisis
    template_name = "analisis/historial.html"
    context_object_name = "analisis"
    paginate_by = 12

    def get_queryset(self):
        base = Analisis.objects.visibles_para(self.request.user).select_related("zona", "usuario")
        self.filtro = FiltroAnalisisForm(self.request.GET or None)
        return self.filtro.aplicar(base) if self.request.GET else base

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filtro"] = getattr(self, "filtro", FiltroAnalisisForm())
        ctx["es_admin"] = self.request.user.puede_administrar()
        return ctx


class AnalisisDetailView(LoginRequiredMixin, ResumenSeveridadMixin, DetailView):
    model = Analisis
    template_name = "analisis/detalle.html"
    context_object_name = "analisis"

    def get_queryset(self):
        return Analisis.objects.visibles_para(self.request.user).select_related("zona", "usuario")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        analisis = self.object
        ctx["baches"] = analisis.baches.all()[:80]
        ctx["desglose"] = analisis.conteo_por_severidad()
        ctx["puede_editar"] = self.request.user.puede_editar_analisis(analisis)
        # Se entrega como dict para que la plantilla lo pase por json_script:
        # interpolar Decimals en JavaScript los escribe con coma decimal (es-PE).
        ctx["punto"] = (
            {
                "lat": float(analisis.latitud),
                "lng": float(analisis.longitud),
                "color": analisis.hex_severidad,
                "codigo": analisis.codigo,
                "titulo": analisis.titulo,
            }
            if analisis.tiene_ubicacion
            else None
        )
        return ctx


class AnalisisDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Analisis
    template_name = "analisis/confirmar_eliminar.html"
    success_url = reverse_lazy("analisis:historial")

    def test_func(self):
        return self.request.user.puede_editar_analisis(self.get_object())

    def form_valid(self, form):
        messages.success(self.request, f"Analisis {self.get_object().codigo} eliminado.")
        return super().form_valid(form)


class EditarUbicacionView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """Sitúa (o corrige) en el mapa un analisis ya guardado."""

    model = Analisis
    form_class = UbicacionForm
    template_name = "analisis/ubicacion.html"
    context_object_name = "analisis"

    def test_func(self):
        return self.request.user.puede_editar_analisis(self.get_object())

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "No tiene permisos sobre este analisis.")
            return redirect("analisis:historial")
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        analisis = self.object
        ctx["zonas_json"] = list(
            Zona.objects.filter(activa=True).values("id", "nombre", "ciudad", "latitud", "longitud")
        )
        # Punto inicial del mapa: el que ya tenga, si es que tiene alguno.
        ctx["punto"] = (
            {"lat": float(analisis.latitud), "lng": float(analisis.longitud)}
            if analisis.tiene_ubicacion
            else None
        )
        return ctx

    def form_valid(self, form):
        messages.success(
            self.request, f"Ubicacion del analisis {self.object.codigo} actualizada."
        )
        return super().form_valid(form)

    def get_success_url(self):
        return self.object.get_absolute_url()


class ReprocesarView(LoginRequiredMixin, View):
    """Vuelve a correr el modelo sobre el archivo original."""

    def post(self, request, pk):
        analisis = get_object_or_404(Analisis, pk=pk)
        if not request.user.puede_editar_analisis(analisis):
            messages.error(request, "No tiene permisos sobre este analisis.")
            return redirect("analisis:historial")

        resultado = ProcesadorAnalisis(analisis).ejecutar()
        if resultado.exitoso:
            messages.success(
                request, f"Reprocesado: {resultado.total} dano(s) en {resultado.tiempo} s."
            )
        else:
            messages.error(request, f"No se pudo reprocesar: {resultado.error}")
        return redirect(analisis)


# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------
class MapaView(LoginRequiredMixin, TemplateView):
    template_name = "analisis/mapa.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filtro"] = FiltroAnalisisForm(self.request.GET or None)
        return ctx


class GeoJSONView(LoginRequiredMixin, View):
    """Alimenta el mapa Leaflet con los analisis geolocalizados."""

    def get(self, request):
        base = Analisis.objects.visibles_para(request.user).geolocalizados().select_related("zona")
        filtro = FiltroAnalisisForm(request.GET or None)
        registros = filtro.aplicar(base) if request.GET else base

        rasgos = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(a.longitud), float(a.latitud)]},
                "properties": {
                    "codigo": a.codigo,
                    "titulo": a.titulo,
                    "zona": str(a.zona) if a.zona else "Sin zona",
                    "origen": a.get_origen_display(),
                    "severidad": a.get_severidad_maxima_display() or "Sin danos",
                    "hex": a.hex_severidad,
                    "baches": a.total_baches,
                    "grietas": a.total_grietas,
                    "criticos": a.sev_critica,
                    "fecha": timezone.localtime(a.creado_en).strftime("%d/%m/%Y %H:%M"),
                    "url": a.get_absolute_url(),
                },
            }
            for a in registros[:1000]
        ]
        return JsonResponse({"type": "FeatureCollection", "features": rasgos})


# ---------------------------------------------------------------------------
# Georreferenciacion (geopy / Nominatim)
# ---------------------------------------------------------------------------
class BuscarDireccionView(LoginRequiredMixin, View):
    """Direccion escrita -> coordenadas. Alimenta el buscador del mapa."""

    def get(self, request):
        texto = request.GET.get("q", "")
        try:
            lugares = obtener_geocodificador().buscar(texto, limite=5)
        except ErrorGeocodificacion as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=503)
        return JsonResponse({"ok": True, "resultados": [l.como_dict() for l in lugares]})


class DireccionInversaView(LoginRequiredMixin, View):
    """Coordenadas -> direccion legible. Rellena la referencia al marcar el mapa."""

    def get(self, request):
        try:
            latitud = float(request.GET["lat"])
            longitud = float(request.GET["lng"])
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Coordenadas invalidas."}, status=400)

        try:
            direccion = obtener_geocodificador().direccion_de(latitud, longitud)
        except ErrorGeocodificacion as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=503)
        return JsonResponse({"ok": True, "direccion": direccion or ""})


# ---------------------------------------------------------------------------
# Estadisticas (solo administrador)
# ---------------------------------------------------------------------------
class EstadisticasView(AdminRequeridoMixin, ResumenSeveridadMixin, TemplateView):
    template_name = "analisis/estadisticas.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        baches = Bache.objects.all()

        desglose, total = self.desglose(baches)
        ctx["desglose"] = desglose
        ctx["total_clasificados"] = total

        ctx["por_tipo"] = [
            {
                "tipo": fila["clase"],
                "etiqueta": TipoDano(fila["clase"]).label,
                "total": fila["total"],
                "confianza": round((fila["confianza"] or 0) * 100, 1),
                "area": round((fila["area"] or 0) * 100, 2),
            }
            for fila in baches.values("clase").annotate(
                total=Count("id"), confianza=Avg("confianza"), area=Avg("area_relativa")
            )
        ]

        ctx["zonas"] = (
            Zona.objects.annotate(
                total=Count("analisis", distinct=True),
                danos=Sum("analisis__total_detecciones"),
                criticos=Sum("analisis__sev_critica"),
                altos=Sum("analisis__sev_alta"),
            )
            .filter(total__gt=0)
            .order_by("-danos")
        )

        ctx["usuarios"] = (
            Analisis.objects.values("usuario__username", "usuario__first_name", "usuario__last_name")
            .annotate(total=Count("id"), danos=Sum("total_detecciones"))
            .order_by("-total")[:10]
        )

        ctx["por_origen"] = [
            {
                "etiqueta": TipoOrigen(fila["origen"]).label,
                "total": fila["total"],
                "danos": fila["danos"] or 0,
            }
            for fila in Analisis.objects.values("origen").annotate(
                total=Count("id"), danos=Sum("total_detecciones")
            )
        ]

        ctx["tiempo_medio"] = round(
            Analisis.objects.aggregate(t=Avg("tiempo_proceso"))["t"] or 0, 2
        )
        return ctx
