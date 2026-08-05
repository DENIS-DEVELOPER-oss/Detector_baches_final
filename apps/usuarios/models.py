"""
Modelos de usuario del sistema.

Diseno POO
----------
    PersonaBase (abstracta)  ->  datos comunes a cualquier persona del sistema
        Usuario              ->  extiende AbstractUser de Django + PersonaBase

El sistema maneja unicamente dos roles:

    ADMINISTRADOR -> acceso completo: gestiona usuarios y ve todas las detecciones.
    CIUDADANO     -> usa el modulo de deteccion y consulta su propio historial.
"""

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import RegexValidator
from django.db import models


class RolUsuario(models.TextChoices):
    """Roles disponibles. Cada rol define hasta donde llega el usuario."""

    CIUDADANO = "CIUDADANO", "Ciudadano"
    ADMIN = "ADMIN", "Administrador"


class PersonaBase(models.Model):
    """Clase abstracta con los datos personales comunes."""

    dni = models.CharField(
        "DNI",
        max_length=8,
        blank=True,
        validators=[RegexValidator(r"^\d{8}$", "El DNI debe tener 8 digitos.")],
    )
    telefono = models.CharField(
        "Telefono",
        max_length=15,
        blank=True,
        validators=[RegexValidator(r"^\+?\d{6,15}$", "Ingrese un telefono valido.")],
    )
    direccion = models.CharField("Direccion", max_length=180, blank=True)

    class Meta:
        abstract = True

    def nombre_para_mostrar(self):
        """Nombre legible; las subclases pueden refinarlo."""
        completo = f"{self.first_name} {self.last_name}".strip()
        return completo or self.get_username()


class UsuarioQuerySet(models.QuerySet):
    def ciudadanos(self):
        return self.filter(rol=RolUsuario.CIUDADANO)

    def administradores(self):
        return self.filter(rol=RolUsuario.ADMIN)

    def activos(self):
        return self.filter(is_active=True)


class UsuarioManager(UserManager.from_queryset(UsuarioQuerySet)):
    """Une los consultas propias con las de Django.

    Hereda de UserManager a proposito: `create_user`, `create_superuser` y
    `normalize_email` deben seguir existiendo para que funcionen el registro,
    el admin y `manage.py createsuperuser`.
    """


class Usuario(AbstractUser, PersonaBase):
    """Usuario del sistema de deteccion automatica de baches."""

    rol = models.CharField(
        "Rol",
        max_length=12,
        choices=RolUsuario.choices,
        default=RolUsuario.CIUDADANO,
    )
    ciudad = models.CharField(
        "Ciudad",
        max_length=40,
        choices=[("JULIACA", "Juliaca"), ("PUNO", "Puno"), ("OTRO", "Otro")],
        default="JULIACA",
    )
    foto = models.ImageField("Foto de perfil", upload_to="perfiles/", blank=True, null=True)
    creado_en = models.DateTimeField("Creado en", auto_now_add=True)

    objects = UsuarioManager()

    class Meta:
        db_table = "usuario"
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.nombre_para_mostrar()} ({self.get_rol_display()})"

    # -- Consultas de rol ---------------------------------------------------
    @property
    def es_ciudadano(self):
        return self.rol == RolUsuario.CIUDADANO and not self.is_superuser

    @property
    def es_admin(self):
        return self.rol == RolUsuario.ADMIN or self.is_superuser

    # -- Reglas de permiso del dominio -------------------------------------
    def puede_administrar(self):
        """Solo el administrador gestiona usuarios y ve todo el sistema."""
        return self.es_admin

    def puede_ver_todas_las_detecciones(self):
        return self.es_admin

    def puede_editar_analisis(self, analisis):
        """El ciudadano solo toca lo suyo; el administrador toca todo."""
        if self.es_admin:
            return True
        return analisis.usuario_id == self.pk

    def save(self, *args, **kwargs):
        # Un ADMIN del dominio tambien entra al panel de administracion Django.
        if self.rol == RolUsuario.ADMIN:
            self.is_staff = True
        super().save(*args, **kwargs)
