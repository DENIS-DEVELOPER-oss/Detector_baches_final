from django.urls import path

from . import views

app_name = "analisis"

urlpatterns = [
    path("", views.PanelView.as_view(), name="panel"),
    path("historial/", views.HistorialListView.as_view(), name="historial"),
    path("historial/<int:pk>/", views.AnalisisDetailView.as_view(), name="detalle"),
    path("historial/<int:pk>/ubicacion/", views.EditarUbicacionView.as_view(), name="ubicacion"),
    path("historial/<int:pk>/eliminar/", views.AnalisisDeleteView.as_view(), name="eliminar"),
    path("historial/<int:pk>/reprocesar/", views.ReprocesarView.as_view(), name="reprocesar"),
    path("mapa/", views.MapaView.as_view(), name="mapa"),
    path("api/analisis.geojson", views.GeoJSONView.as_view(), name="geojson"),
    # Georreferenciacion (geopy / Nominatim)
    path("api/geocodificar/", views.BuscarDireccionView.as_view(), name="geocodificar"),
    path("api/geocodificar/inverso/", views.DireccionInversaView.as_view(), name="geocodificar_inverso"),
    path("estadisticas/", views.EstadisticasView.as_view(), name="estadisticas"),
]
