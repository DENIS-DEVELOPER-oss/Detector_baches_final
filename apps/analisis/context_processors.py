"""Variables disponibles en todas las plantillas."""

from django.conf import settings


def configuracion(request):
    datos = {
        "MAPA_CENTRO": settings.MAPA_CENTRO,
        "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
    }

    usuario = getattr(request, "user", None)
    if usuario is not None and usuario.is_authenticated:
        from .models import Analisis, Bache, NivelSeveridad

        datos["nav_analisis"] = Analisis.objects.visibles_para(usuario).count()
        datos["nav_criticos"] = (
            Bache.objects.visibles_para(usuario).de_nivel(NivelSeveridad.CRITICA).count()
        )

    return datos
