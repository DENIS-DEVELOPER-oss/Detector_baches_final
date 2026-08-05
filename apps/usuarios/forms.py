"""Formularios de acceso, perfil y gestion de usuarios.

No hay formulario de registro: el sistema no admite altas publicas. Las cuentas
las crea el administrador desde la gestion de usuarios.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import RolUsuario, Usuario


class MixinBootstrap:
    """Aplica clases de Bootstrap a todos los widgets del formulario."""

    def _estilizar(self):
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class LoginForm(MixinBootstrap, AuthenticationForm):
    """Acceso al sistema.

    `recordarme` no es un campo de autenticacion: la vista lo usa para decidir
    cuanto dura la sesion.
    """

    recordarme = forms.BooleanField(
        label="Mantener la sesion iniciada",
        required=False,
        initial=False,
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Usuario o contrasena incorrectos. Revise mayusculas y minusculas.",
        "inactive": "Esta cuenta esta desactivada. Contacte al administrador.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estilizar()

        self.fields["username"].widget.attrs.update({
            "placeholder": "Su usuario",
            "autofocus": True,
            "autocomplete": "username",
        })
        self.fields["password"].widget.attrs.update({
            "placeholder": "Su contrasena",
            "autocomplete": "current-password",
        })


class PerfilForm(MixinBootstrap, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "email", "dni", "telefono", "direccion", "ciudad", "foto"]
        labels = {"first_name": "Nombres", "last_name": "Apellidos"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estilizar()


class CrearUsuarioForm(MixinBootstrap, UserCreationForm):
    """Alta de una cuenta por parte del administrador.

    Sustituye al formulario del panel de Django: aqui el administrador elige
    el rol, cosa que el registro publico (inexistente) nunca podria hacer.
    """

    email = forms.EmailField(label="Correo electronico", required=False)

    class Meta:
        model = Usuario
        fields = ["username", "first_name", "last_name", "email",
                  "dni", "telefono", "ciudad", "rol"]
        labels = {
            "username": "Nombre de usuario",
            "first_name": "Nombres",
            "last_name": "Apellidos",
        }
        help_texts = {"username": "Sin espacios. Es con lo que iniciara sesion."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rol"].initial = RolUsuario.CIUDADANO
        self.fields["password1"].label = "Contrasena"
        self.fields["password2"].label = "Repita la contrasena"
        self._estilizar()

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").lower()
        if email and Usuario.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con ese correo.")
        return email


class UsuarioAdminForm(MixinBootstrap, forms.ModelForm):
    """Edicion de un usuario por parte del administrador."""

    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "email", "dni", "telefono",
                  "ciudad", "rol", "is_active"]
        labels = {"first_name": "Nombres", "last_name": "Apellidos", "is_active": "Cuenta activa"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estilizar()


class FiltroUsuarioForm(MixinBootstrap, forms.Form):
    q = forms.CharField(
        label="Buscar", required=False,
        widget=forms.TextInput(attrs={"placeholder": "Usuario, nombre o correo"}),
    )
    rol = forms.ChoiceField(
        label="Rol", required=False, choices=[("", "Todos")] + list(RolUsuario.choices)
    )
    activo = forms.ChoiceField(
        label="Estado de la cuenta", required=False,
        choices=[("", "Todos"), ("1", "Activos"), ("0", "Inactivos")],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estilizar()

    def aplicar(self, queryset):
        if not self.is_valid():
            return queryset
        datos = self.cleaned_data

        if datos.get("q"):
            from django.db.models import Q

            texto = datos["q"]
            queryset = queryset.filter(
                Q(username__icontains=texto)
                | Q(first_name__icontains=texto)
                | Q(last_name__icontains=texto)
                | Q(email__icontains=texto)
            )
        if datos.get("rol"):
            queryset = queryset.filter(rol=datos["rol"])
        if datos.get("activo") in ("0", "1"):
            queryset = queryset.filter(is_active=datos["activo"] == "1")
        return queryset
