"""
Carga las zonas de Juliaca y Puno y crea los usuarios de demostracion.

Uso:
    python manage.py cargar_datos_iniciales
    python manage.py cargar_datos_iniciales --sin-usuarios

Las coordenadas son aproximadas (centro del sector); se pueden ajustar desde
el panel de administracion.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.analisis.models import Ciudad, Zona
from apps.usuarios.cuentas_demo import CUENTAS_DEMO

Usuario = get_user_model()

ZONAS = [
    # Juliaca (provincia de San Roman)
    ("Centro de Juliaca", Ciudad.JULIACA, -15.4997, -70.1330, "Plaza de Armas y jirones centricos"),
    ("Av. Circunvalacion", Ciudad.JULIACA, -15.4930, -70.1420, "Anillo vial de mayor transito"),
    ("Av. Ferrocarril", Ciudad.JULIACA, -15.4960, -70.1352, "Eje paralelo a la via ferrea"),
    ("Mercado Tupac Amaru", Ciudad.JULIACA, -15.4921, -70.1262, "Zona comercial de alta carga"),
    ("Urbanizacion Santa Maria", Ciudad.JULIACA, -15.4872, -70.1251, "Zona residencial norte"),
    ("Cerro Colorado", Ciudad.JULIACA, -15.4884, -70.1503, "Sector noroeste"),
    ("Salida a Cusco", Ciudad.JULIACA, -15.4781, -70.1424, "Carretera Juliaca - Cusco"),
    ("Salida a Arequipa", Ciudad.JULIACA, -15.4893, -70.1651, "Carretera Juliaca - Arequipa"),
    ("Terminal Terrestre", Ciudad.JULIACA, -15.5062, -70.1401, "Entorno del terminal"),
    ("Aeropuerto Inca Manco Capac", Ciudad.JULIACA, -15.4671, -70.1583, "Via de acceso al aeropuerto"),
    # Puno (capital de la region)
    ("Centro de Puno", Ciudad.PUNO, -15.8402, -70.0219, "Plaza de Armas y jr. Lima"),
    ("Av. El Sol", Ciudad.PUNO, -15.8381, -70.0252, "Eje comercial principal"),
    ("Av. Simon Bolivar", Ciudad.PUNO, -15.8424, -70.0301, "Via de acceso oeste"),
    ("Barrio Bellavista", Ciudad.PUNO, -15.8292, -70.0289, "Zona alta norte"),
    ("Chanu Chanu", Ciudad.PUNO, -15.8361, -70.0183, "Zona residencial junto al lago"),
    ("Salcedo", Ciudad.PUNO, -15.8592, -70.0134, "Sector sur de la ciudad"),
    ("Malecon Ecoturistico", Ciudad.PUNO, -15.8331, -70.0141, "Borde del lago Titicaca"),
    ("Alto Puno", Ciudad.PUNO, -15.8203, -70.0352, "Sector alto norte"),
    ("Jr. Los Incas", Ciudad.PUNO, -15.8433, -70.0261, "Corredor central"),
    ("Salida a Juliaca", Ciudad.PUNO, -15.8251, -70.0203, "Carretera Puno - Juliaca"),
]

# Las cuentas viven en apps.usuarios.cuentas_demo: de ahi las toma tambien la
# pantalla de acceso, para que no anuncie una contrasena que ya no funciona.
USUARIOS = CUENTAS_DEMO


class Command(BaseCommand):
    help = "Carga zonas de Juliaca y Puno y usuarios de demostracion."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sin-usuarios",
            action="store_true",
            help="Carga unicamente las zonas geograficas.",
        )
        parser.add_argument(
            "--reiniciar-usuarios",
            action="store_true",
            help="Actualiza datos y contrasena de los usuarios que ya existan.",
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        creadas = 0
        for nombre, ciudad, lat, lng, descripcion in ZONAS:
            _, nueva = Zona.objects.get_or_create(
                nombre=nombre,
                ciudad=ciudad,
                defaults={"latitud": lat, "longitud": lng, "descripcion": descripcion},
            )
            creadas += int(nueva)

        self.stdout.write(
            self.style.SUCCESS(f"Zonas: {creadas} creadas, {len(ZONAS) - creadas} ya existian.")
        )

        if opciones["sin_usuarios"]:
            return

        reiniciar = opciones["reiniciar_usuarios"]

        for cuenta in USUARIOS:
            username = cuenta["usuario"]
            usuario = Usuario.objects.filter(username=username).first()

            if usuario and not reiniciar:
                self.stdout.write(
                    f"  - Usuario '{username}' ya existe, se omite "
                    f"(use --reiniciar-usuarios para actualizarlo)."
                )
                continue

            accion = "actualizado" if usuario else "creado"
            usuario = usuario or Usuario(username=username)

            usuario.first_name = cuenta["nombres"]
            usuario.last_name = cuenta["apellidos"]
            usuario.email = f"{username}@baches.pe"
            usuario.rol = cuenta["rol"]
            usuario.ciudad = cuenta["ciudad"]
            usuario.is_superuser = cuenta["superusuario"]
            usuario.is_staff = cuenta["superusuario"]
            usuario.is_active = True
            # set_password no pasa por los validadores de AUTH_PASSWORD_VALIDATORS;
            # por eso claves cortas como "admin123" se aceptan aqui, aunque el
            # formulario de registro las rechazaria.
            usuario.set_password(cuenta["clave"])
            usuario.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"  + Usuario '{username}' {accion} (clave: {cuenta['clave']})"
                )
            )

        # Aviso, sin borrar nada: la limpieza es decision de quien administra.
        sobrantes = Usuario.objects.exclude(
            username__in=[c["usuario"] for c in USUARIOS]
        ).values_list("username", flat=True)
        if sobrantes:
            self.stdout.write(
                self.style.WARNING(
                    f"  ! Otros usuarios en la base de datos: {', '.join(sobrantes)}"
                )
            )

        self.stdout.write(self.style.SUCCESS("Datos iniciales cargados."))
