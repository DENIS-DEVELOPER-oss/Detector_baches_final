"""
Cuentas de demostracion del sistema.

Unica fuente de verdad: de aqui las toman tanto el comando que las crea
(`cargar_datos_iniciales`) como la pantalla de acceso que las muestra. Asi no
puede pasar que la web anuncie una contrasena que ya no funciona.

AVISO: publicar estas credenciales solo tiene sentido en una demostracion.
Si el sistema pasa a uso real, ponga MOSTRAR_CUENTAS_DEMO=False en el .env y
cambie las contrasenas.
"""

from .models import RolUsuario

CUENTAS_DEMO = [
    {
        "usuario": "admin",
        "clave": "admin123",
        "nombres": "Admin",
        "apellidos": "General",
        "rol": RolUsuario.ADMIN,
        "ciudad": "JULIACA",
        "superusuario": True,
        "descripcion": "Ve todas las detecciones, estadisticas y gestion de usuarios",
    },
    {
        "usuario": "vanessa",
        "clave": "vanessa123",
        "nombres": "Vanessa",
        "apellidos": "Choquehuanca Mamani",
        "rol": RolUsuario.CIUDADANO,
        "ciudad": "JULIACA",
        "superusuario": False,
        "descripcion": "Analiza y consulta su propio historial",
    },
    {
        "usuario": "denis",
        "clave": "denis123",
        "nombres": "Denis",
        "apellidos": "Quispe Apaza",
        "rol": RolUsuario.CIUDADANO,
        "ciudad": "PUNO",
        "superusuario": False,
        "descripcion": "Analiza y consulta su propio historial",
    },
    {
        "usuario": "aldo",
        "clave": "aldo123",
        "nombres": "Aldo",
        "apellidos": "Ccama Condori",
        "rol": RolUsuario.CIUDADANO,
        "ciudad": "JULIACA",
        "superusuario": False,
        "descripcion": "Analiza y consulta su propio historial",
    },
]


def cuentas_para_mostrar():
    """Lo que necesita la pantalla de acceso, sin datos de mas."""
    return [
        {
            "usuario": c["usuario"],
            "clave": c["clave"],
            "rol": RolUsuario(c["rol"]).label,
            "es_admin": c["rol"] == RolUsuario.ADMIN,
            "descripcion": c["descripcion"],
        }
        for c in CUENTAS_DEMO
    ]
