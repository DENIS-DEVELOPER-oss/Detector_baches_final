"""Pruebas de usuarios: roles, permisos y acceso."""

from django.test import TestCase
from django.urls import reverse

from apps.usuarios.models import RolUsuario, Usuario


class RolesTest(TestCase):
    """El sistema maneja exactamente dos roles."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_user(
            "jefe", password="x", rol=RolUsuario.ADMIN, first_name="Ana"
        )
        cls.ciudadano = Usuario.objects.create_user(
            "vecino", password="x", rol=RolUsuario.CIUDADANO
        )

    def test_solo_existen_dos_roles(self):
        self.assertEqual(set(RolUsuario.values), {"ADMIN", "CIUDADANO"})
        self.assertNotIn("INSPECTOR", RolUsuario.values)

    def test_el_administrador_administra(self):
        self.assertTrue(self.admin.es_admin)
        self.assertTrue(self.admin.puede_administrar())
        self.assertTrue(self.admin.puede_ver_todas_las_detecciones())

    def test_el_ciudadano_no_administra(self):
        self.assertTrue(self.ciudadano.es_ciudadano)
        self.assertFalse(self.ciudadano.puede_administrar())
        self.assertFalse(self.ciudadano.puede_ver_todas_las_detecciones())

    def test_el_rol_admin_da_acceso_al_panel_de_django(self):
        self.assertTrue(self.admin.is_staff)
        self.assertFalse(self.ciudadano.is_staff)

    def test_nombre_para_mostrar_cae_al_usuario_si_no_hay_nombre(self):
        self.assertEqual(self.admin.nombre_para_mostrar(), "Ana")
        self.assertEqual(self.ciudadano.nombre_para_mostrar(), "vecino")


class ManagerTest(TestCase):
    """El manager propio no debe romper lo que Django espera de un usuario."""

    def test_conserva_los_metodos_de_django(self):
        # Si se sustituye por un QuerySet.as_manager() se pierden estos metodos
        # y dejan de funcionar el alta de usuarios y createsuperuser.
        for metodo in ("create_user", "create_superuser", "normalize_email"):
            self.assertTrue(
                hasattr(Usuario.objects, metodo),
                f"El manager perdio {metodo}()",
            )

    def test_anade_sus_propias_consultas(self):
        Usuario.objects.create_user("a", password="x", rol=RolUsuario.ADMIN)
        Usuario.objects.create_user("b", password="x", rol=RolUsuario.CIUDADANO)
        Usuario.objects.create_user("c", password="x", rol=RolUsuario.CIUDADANO)

        self.assertEqual(Usuario.objects.ciudadanos().count(), 2)
        self.assertEqual(Usuario.objects.administradores().count(), 1)
        self.assertEqual(Usuario.objects.activos().count(), 3)


class AccesoTest(TestCase):
    """No hay registro publico: las cuentas las crea el administrador."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user("vecino", password="Clave-2026")

    def test_la_pagina_de_acceso_responde(self):
        self.assertEqual(self.client.get(reverse("usuarios:login")).status_code, 200)

    def test_no_existe_el_registro_publico(self):
        self.assertEqual(self.client.get("/cuentas/registro/").status_code, 404)

    def test_credenciales_correctas_entran(self):
        respuesta = self.client.post(
            reverse("usuarios:login"),
            {"username": "vecino", "password": "Clave-2026"},
            follow=True,
        )
        self.assertTrue(respuesta.context["user"].is_authenticated)

    def test_credenciales_incorrectas_muestran_el_error(self):
        respuesta = self.client.post(
            reverse("usuarios:login"), {"username": "vecino", "password": "mal"}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "incorrectos")

    def test_la_sesion_caduca_al_cerrar_si_no_se_marca_recordarme(self):
        self.client.post(
            reverse("usuarios:login"),
            {"username": "vecino", "password": "Clave-2026"},
        )
        # get_expiry_age() devuelve SESSION_COOKIE_AGE cuando la caducidad es 0,
        # asi que hay que preguntar por el cierre del navegador explicitamente.
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_recordarme_alarga_la_sesion(self):
        self.client.post(
            reverse("usuarios:login"),
            {"username": "vecino", "password": "Clave-2026", "recordarme": "on"},
        )
        self.assertGreater(self.client.session.get_expiry_age(), 60 * 60 * 24)


class PanelDjangoTest(TestCase):
    """El panel de Django esta desmontado: la gestion vive en la aplicacion."""

    def test_no_existe_la_url_del_admin(self):
        for ruta in ("/admin/", "/admin/login/", "/panel-interno/"):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 404)

    def test_ninguna_pagina_enlaza_al_admin(self):
        admin = Usuario.objects.create_user("jefe", password="x", rol=RolUsuario.ADMIN)
        self.client.force_login(admin)
        for nombre in ("analisis:panel", "usuarios:gestion", "usuarios:perfil"):
            with self.subTest(pagina=nombre):
                html = self.client.get(reverse(nombre)).content.decode()
                self.assertNotIn("/admin/", html)


class CrearUsuarioTest(TestCase):
    """Alta de cuentas sin pasar por el panel de Django."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_user("jefe", password="x", rol=RolUsuario.ADMIN)
        cls.ciudadano = Usuario.objects.create_user("vecino", password="x")

    def test_el_administrador_crea_una_cuenta(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("usuarios:crear"), {
            "username": "nueva", "first_name": "Ana", "last_name": "Mamani",
            "email": "ana@x.pe", "dni": "", "telefono": "", "ciudad": "PUNO",
            "rol": RolUsuario.CIUDADANO,
            "password1": "Clave-Larga-2026", "password2": "Clave-Larga-2026",
        })
        creada = Usuario.objects.filter(username="nueva").first()
        self.assertIsNotNone(creada)
        self.assertEqual(creada.rol, RolUsuario.CIUDADANO)
        self.assertTrue(creada.is_active)

    def test_puede_crear_administradores(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("usuarios:crear"), {
            "username": "otrojefe", "first_name": "", "last_name": "", "email": "",
            "dni": "", "telefono": "", "ciudad": "JULIACA", "rol": RolUsuario.ADMIN,
            "password1": "Clave-Larga-2026", "password2": "Clave-Larga-2026",
        })
        creada = Usuario.objects.filter(username="otrojefe").first()
        self.assertIsNotNone(creada)
        self.assertTrue(creada.es_admin)
        self.assertTrue(creada.is_staff)

    def test_un_ciudadano_no_puede_crear_cuentas(self):
        self.client.force_login(self.ciudadano)
        self.assertEqual(self.client.get(reverse("usuarios:crear")).status_code, 302)
        self.assertEqual(Usuario.objects.count(), 2)


class GestionDeUsuariosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_user(
            "jefe", password="x", rol=RolUsuario.ADMIN
        )
        cls.ciudadano = Usuario.objects.create_user("vecino", password="x")

    def test_el_ciudadano_no_entra_a_la_gestion(self):
        self.client.force_login(self.ciudadano)
        self.assertEqual(self.client.get(reverse("usuarios:gestion")).status_code, 302)

    def test_el_administrador_si_entra(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("usuarios:gestion")).status_code, 200)

    def test_el_administrador_no_puede_degradarse_a_si_mismo(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("usuarios:editar", args=[self.admin.pk]),
            {"first_name": "", "last_name": "", "email": "", "dni": "",
             "telefono": "", "ciudad": "JULIACA", "rol": RolUsuario.CIUDADANO,
             "is_active": "on"},
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.rol, RolUsuario.ADMIN)
