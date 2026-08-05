"""Vistas de autenticacion, perfil y gestion de usuarios."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Sum
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, UpdateView

from .cuentas_demo import cuentas_para_mostrar
from .forms import FiltroUsuarioForm, LoginForm, PerfilForm, UsuarioAdminForm
from .models import RolUsuario, Usuario

# Duracion de la sesion cuando el usuario marca "mantener sesion iniciada".
DIAS_RECORDAR = 14


class AccesoView(LoginView):
    """Unica puerta de entrada: no existe registro publico.

    Las cuentas las crea el administrador desde la gestion de usuarios.
    """

    template_name = "usuarios/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Solo se anuncian las cuentas que existen de verdad: si el
        # administrador borro alguna, deja de aparecer.
        if settings.MOSTRAR_CUENTAS_DEMO:
            existentes = set(
                Usuario.objects.activos().values_list("username", flat=True)
            )
            ctx["cuentas_demo"] = [
                c for c in cuentas_para_mostrar() if c["usuario"] in existentes
            ]
        return ctx

    def form_valid(self, form):
        # Sin marcar, la sesion muere al cerrar el navegador.
        if form.cleaned_data.get("recordarme"):
            self.request.session.set_expiry(DIAS_RECORDAR * 24 * 60 * 60)
        else:
            self.request.session.set_expiry(0)
        return super().form_valid(form)


class SalidaView(LogoutView):
    next_page = reverse_lazy("usuarios:login")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            messages.info(request, "Sesion cerrada correctamente.")
        return super().dispatch(request, *args, **kwargs)


class PerfilView(LoginRequiredMixin, UpdateView):
    model = Usuario
    form_class = PerfilForm
    template_name = "usuarios/perfil.html"
    success_url = reverse_lazy("usuarios:perfil")

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        analisis = self.request.user.analisis.all()
        ctx["total_analisis"] = analisis.count()
        ctx["total_danos"] = analisis.aggregate(t=Sum("total_detecciones"))["t"] or 0
        ctx["total_criticos"] = analisis.aggregate(t=Sum("sev_critica"))["t"] or 0
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Perfil actualizado correctamente.")
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Gestion de usuarios (solo administrador)
# ---------------------------------------------------------------------------
class AdminRequeridoMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.puede_administrar()

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "Solo el administrador puede gestionar usuarios.")
            return redirect("analisis:panel")
        return super().handle_no_permission()


class UsuarioListView(AdminRequeridoMixin, ListView):
    model = Usuario
    template_name = "usuarios/gestion.html"
    context_object_name = "usuarios"
    paginate_by = 20

    def get_queryset(self):
        base = Usuario.objects.annotate(
            total_analisis=Count("analisis", distinct=True),
            total_danos=Sum("analisis__total_detecciones"),
        ).order_by("rol", "-creado_en")
        self.filtro = FiltroUsuarioForm(self.request.GET or None)
        return self.filtro.aplicar(base) if self.request.GET else base

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filtro"] = getattr(self, "filtro", FiltroUsuarioForm())
        ctx["total_ciudadanos"] = Usuario.objects.ciudadanos().count()
        ctx["total_admins"] = Usuario.objects.administradores().count()
        ctx["total_activos"] = Usuario.objects.activos().count()
        return ctx


class UsuarioUpdateView(AdminRequeridoMixin, UpdateView):
    model = Usuario
    form_class = UsuarioAdminForm
    template_name = "usuarios/editar.html"
    success_url = reverse_lazy("usuarios:gestion")

    def form_valid(self, form):
        usuario = form.instance
        # No se permite que el administrador se degrade o desactive a si mismo.
        if usuario.pk == self.request.user.pk:
            if form.cleaned_data["rol"] != RolUsuario.ADMIN or not form.cleaned_data["is_active"]:
                messages.error(
                    self.request,
                    "No puede quitarse a si mismo el rol de administrador ni desactivar su cuenta.",
                )
                return self.form_invalid(form)

        messages.success(self.request, f"Usuario '{usuario.username}' actualizado.")
        return super().form_valid(form)
