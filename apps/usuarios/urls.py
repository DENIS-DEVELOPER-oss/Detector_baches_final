from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("login/", views.AccesoView.as_view(), name="login"),
    path("logout/", views.SalidaView.as_view(), name="logout"),
    path("perfil/", views.PerfilView.as_view(), name="perfil"),
    # No hay registro publico: las cuentas las crea el administrador.
    # Gestion (solo administrador)
    path("gestion/", views.UsuarioListView.as_view(), name="gestion"),
    path("gestion/<int:pk>/editar/", views.UsuarioUpdateView.as_view(), name="editar"),
]
