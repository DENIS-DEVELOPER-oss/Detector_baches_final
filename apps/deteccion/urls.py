from django.urls import path

from . import views

app_name = "deteccion"

urlpatterns = [
    path("", views.ModuloDeteccionView.as_view(), name="modulo"),
    # Los cinco modos de entrada
    path("subir/", views.SubirArchivoView.as_view(), name="subir_archivo"),
    path("foto/", views.CapturarFotoView.as_view(), name="capturar_foto"),
    path("grabar/", views.GrabarVideoView.as_view(), name="grabar_video"),
    path("vivo/analizar/", views.AnalizarCuadroView.as_view(), name="analizar_cuadro"),
    path("vivo/guardar/", views.GuardarDeteccionVivoView.as_view(), name="guardar_vivo"),
    # Diagnostico
    path("api/modelo/", views.EstadoModeloView.as_view(), name="estado_modelo"),
]
