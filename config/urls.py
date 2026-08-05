"""Rutas del proyecto: deteccion automatica de baches en Juliaca y Puno."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Deteccion de Baches - Juliaca y Puno"
admin.site.site_title = "Deteccion de Baches"
admin.site.index_title = "Administracion del sistema"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cuentas/", include("apps.usuarios.urls")),
    path("deteccion/", include("apps.deteccion.urls")),
    path("", include("apps.analisis.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
