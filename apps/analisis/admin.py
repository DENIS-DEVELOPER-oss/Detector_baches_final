from django.contrib import admin

from .models import Analisis, Bache, Zona


class BacheInline(admin.TabularInline):
    model = Bache
    extra = 0
    readonly_fields = ("clase", "severidad", "confianza", "area_relativa", "frame", "segundo")
    fields = readonly_fields
    can_delete = False
    max_num = 0


@admin.register(Zona)
class ZonaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "ciudad", "latitud", "longitud", "total_analisis", "activa")
    list_filter = ("ciudad", "activa")
    search_fields = ("nombre", "descripcion")


@admin.register(Analisis)
class AnalisisAdmin(admin.ModelAdmin):
    list_display = (
        "codigo", "titulo", "usuario", "origen", "severidad_maxima",
        "total_baches", "total_grietas", "sev_critica", "creado_en",
    )
    list_filter = ("origen", "severidad_maxima", "procesado", "zona__ciudad")
    search_fields = ("codigo", "titulo", "direccion_referencia", "usuario__username")
    date_hierarchy = "creado_en"
    autocomplete_fields = ("zona",)
    readonly_fields = (
        "codigo", "procesado", "error_proceso", "tiempo_proceso", "frames_analizados",
        "total_detecciones", "total_baches", "total_grietas",
        "sev_baja", "sev_media", "sev_alta", "sev_critica",
        "severidad_maxima", "severidad_predominante",
        "confianza_promedio", "area_danada_pct", "creado_en", "actualizado_en",
    )
    inlines = [BacheInline]


@admin.register(Bache)
class BacheAdmin(admin.ModelAdmin):
    list_display = ("analisis", "clase", "severidad", "confianza", "area_relativa", "segundo")
    list_filter = ("clase", "severidad")
    search_fields = ("analisis__codigo",)
