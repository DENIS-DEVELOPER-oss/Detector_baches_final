from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "nombre_para_mostrar", "email", "rol", "ciudad", "is_active")
    list_filter = ("rol", "ciudad", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email", "dni")
    ordering = ("-creado_en",)

    fieldsets = UserAdmin.fieldsets + (
        ("Datos del sistema", {"fields": ("rol", "ciudad", "dni", "telefono", "direccion", "foto")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Datos del sistema", {"fields": ("rol", "ciudad", "email")}),
    )
