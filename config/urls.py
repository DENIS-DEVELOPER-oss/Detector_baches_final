"""Rutas del proyecto: deteccion automatica de baches en Juliaca y Puno."""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path("cuentas/", include("apps.usuarios.urls")),
    path("deteccion/", include("apps.deteccion.urls")),
    path("", include("apps.analisis.urls")),
]

# El panel de administracion de Django queda fuera: tiene otro aspecto visual y
# no hace falta, porque la gestion de usuarios vive dentro de la aplicacion.
# Para una tarea de mantenimiento puntual se activa con ADMIN_DJANGO=True en el
# .env, y conviene volver a desactivarlo despues.
if settings.ADMIN_DJANGO:
    from django.contrib import admin

    admin.site.site_header = "Deteccion de Baches - Juliaca y Puno"
    admin.site.site_title = "Deteccion de Baches"
    admin.site.index_title = "Administracion del sistema"

    urlpatterns.insert(0, path(settings.ADMIN_DJANGO_URL, admin.site.urls))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
