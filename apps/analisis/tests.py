"""Pruebas del dominio: severidad, permisos, georreferenciacion y vistas."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.analisis.exif import coordenadas_exif
from apps.analisis.geocodificacion import (
    ErrorGeocodificacion, GeocodificadorNominatim, Lugar, obtener_geocodificador,
)
from apps.analisis.models import Analisis, Bache, NivelSeveridad, TipoOrigen, Zona
from apps.usuarios.models import RolUsuario, Usuario

MEDIA_DE_PRUEBA = tempfile.mkdtemp()


def crear_zona(nombre="Centro", ciudad="JULIACA"):
    return Zona.objects.create(
        nombre=nombre, ciudad=ciudad, latitud="-15.4997", longitud="-70.1330"
    )


def crear_analisis(usuario, **extra):
    datos = {
        "titulo": "Analisis",
        "usuario": usuario,
        "origen": TipoOrigen.IMAGEN,
        "archivo": "analisis/originales/x.jpg",
        "procesado": True,
    }
    datos.update(extra)
    return Analisis.objects.create(**datos)


class ResumenDeSeveridadTest(TestCase):
    """Los contadores del analisis salen de sus baches, no al reves."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user("vecino", password="x")

    def test_recalcula_contadores_y_severidades(self):
        analisis = crear_analisis(self.usuario)
        reparto = {
            NivelSeveridad.BAJA: 1, NivelSeveridad.MEDIA: 3,
            NivelSeveridad.ALTA: 2, NivelSeveridad.CRITICA: 1,
        }
        for nivel, cantidad in reparto.items():
            for _ in range(cantidad):
                Bache.objects.create(
                    analisis=analisis, clase="pothole", severidad=nivel,
                    confianza=0.8, x1=0.1, y1=0.1, x2=0.2, y2=0.2,
                )
        Bache.objects.create(
            analisis=analisis, clase="crack", severidad=NivelSeveridad.BAJA,
            confianza=0.7, x1=0.3, y1=0.3, x2=0.35, y2=0.34,
        )

        analisis.recalcular_resumen()
        analisis.refresh_from_db()

        self.assertEqual(analisis.total_detecciones, 8)
        self.assertEqual((analisis.total_baches, analisis.total_grietas), (7, 1))
        self.assertEqual(analisis.sev_baja, 2)
        self.assertEqual(analisis.severidad_maxima, NivelSeveridad.CRITICA)
        self.assertEqual(analisis.severidad_predominante, NivelSeveridad.MEDIA)

    def test_los_porcentajes_suman_cien(self):
        analisis = crear_analisis(self.usuario)
        for nivel in (NivelSeveridad.BAJA, NivelSeveridad.ALTA):
            Bache.objects.create(
                analisis=analisis, clase="pothole", severidad=nivel,
                confianza=0.8, x1=0, y1=0, x2=0.1, y2=0.1,
            )
        analisis.recalcular_resumen()

        total = sum(d["porcentaje"] for d in analisis.conteo_por_severidad())
        self.assertAlmostEqual(total, 100.0, places=1)

    def test_sin_baches_no_hay_severidad(self):
        analisis = crear_analisis(self.usuario)
        analisis.recalcular_resumen()
        self.assertEqual(analisis.severidad_maxima, "")
        self.assertEqual(analisis.total_detecciones, 0)

    def test_el_nivel_maximo_ignora_valores_invalidos(self):
        self.assertEqual(NivelSeveridad.maxima(["BAJA", "CRITICA", "XX"]), "CRITICA")
        self.assertIsNone(NivelSeveridad.maxima([]))


class VisibilidadTest(TestCase):
    """Cada ciudadano ve lo suyo; el administrador ve todo."""

    @classmethod
    def setUpTestData(cls):
        cls.uno = Usuario.objects.create_user("uno", password="x")
        cls.otro = Usuario.objects.create_user("otro", password="x")
        cls.admin = Usuario.objects.create_user("jefe", password="x", rol=RolUsuario.ADMIN)
        cls.suyo = crear_analisis(cls.uno, titulo="De uno")
        cls.ajeno = crear_analisis(cls.otro, titulo="De otro")

    def test_el_ciudadano_solo_ve_lo_suyo(self):
        visibles = Analisis.objects.visibles_para(self.uno)
        self.assertEqual(list(visibles), [self.suyo])

    def test_el_administrador_lo_ve_todo(self):
        self.assertEqual(Analisis.objects.visibles_para(self.admin).count(), 2)

    def test_no_se_puede_abrir_el_analisis_de_otro(self):
        self.client.force_login(self.uno)
        respuesta = self.client.get(reverse("analisis:detalle", args=[self.ajeno.pk]))
        self.assertEqual(respuesta.status_code, 404)

    def test_el_administrador_si_puede(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("analisis:detalle", args=[self.ajeno.pk]))
        self.assertEqual(respuesta.status_code, 200)

    def test_las_estadisticas_son_solo_del_administrador(self):
        self.client.force_login(self.uno)
        self.assertEqual(self.client.get(reverse("analisis:estadisticas")).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("analisis:estadisticas")).status_code, 200)


class UbicacionTest(TestCase):
    """Toda foto se puede situar en el mapa despues de analizarla."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user("vecino", password="x")
        cls.zona = crear_zona()

    def setUp(self):
        self.analisis = crear_analisis(self.usuario)
        self.client.force_login(self.usuario)
        self.url = reverse("analisis:ubicacion", args=[self.analisis.pk])

    def test_un_analisis_sin_coordenadas_no_esta_ubicado(self):
        self.assertFalse(self.analisis.tiene_ubicacion)

    def test_guarda_las_coordenadas(self):
        self.client.post(self.url, {
            "latitud": "-15.4930", "longitud": "-70.1420",
            "direccion_referencia": "Av. Circunvalacion", "zona": "",
        })
        self.analisis.refresh_from_db()
        self.assertTrue(self.analisis.tiene_ubicacion)
        self.assertEqual(self.analisis.direccion_referencia, "Av. Circunvalacion")

    def test_rechaza_media_coordenada(self):
        respuesta = self.client.post(self.url, {
            "latitud": "-15.49", "longitud": "", "zona": "",
        })
        self.assertContains(respuesta, "latitud y longitud")

    def test_rechaza_guardar_sin_punto_ni_zona(self):
        respuesta = self.client.post(self.url, {"latitud": "", "longitud": "", "zona": ""})
        self.assertContains(respuesta, "Marque un punto")

    def test_con_solo_la_zona_toma_su_centro(self):
        self.client.post(self.url, {"latitud": "", "longitud": "", "zona": self.zona.pk})
        self.analisis.refresh_from_db()
        self.assertTrue(self.analisis.tiene_ubicacion)

    def test_otro_ciudadano_no_puede_ubicarlo(self):
        intruso = Usuario.objects.create_user("intruso", password="x")
        self.client.force_login(intruso)
        self.assertIn(self.client.get(self.url).status_code, (302, 404))


class ExifTest(TestCase):
    def test_un_archivo_inexistente_no_revienta(self):
        self.assertIsNone(coordenadas_exif("/no/existe/foto.jpg"))

    def test_un_archivo_que_no_es_imagen_devuelve_none(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "x.jpg"
            ruta.write_bytes(b"no soy una imagen")
            self.assertIsNone(coordenadas_exif(ruta))


class GeocodificacionTest(TestCase):
    """geopy se simula: las pruebas no deben depender de la red."""

    def setUp(self):
        cache.clear()
        self.geo = obtener_geocodificador()

    def test_es_un_singleton(self):
        self.assertIs(GeocodificadorNominatim(), GeocodificadorNominatim())

    def test_busca_y_cachea(self):
        lugares = [Lugar("Av. Circunvalacion, Juliaca", -15.4930, -70.1420)]
        with patch.object(GeocodificadorNominatim, "_buscar", return_value=lugares) as falso:
            self.assertEqual(len(self.geo.buscar("Av. Circunvalacion")), 1)
            self.geo.buscar("Av. Circunvalacion")
            self.assertEqual(falso.call_count, 1, "La segunda busqueda debia salir de la cache")

    def test_un_texto_corto_no_consulta_al_servicio(self):
        with patch.object(GeocodificadorNominatim, "_buscar") as falso:
            self.assertEqual(self.geo.buscar("ab"), [])
            falso.assert_not_called()

    def test_el_endpoint_avisa_si_el_servicio_falla(self):
        usuario = Usuario.objects.create_user("vecino", password="x")
        self.client.force_login(usuario)
        with patch.object(
            GeocodificadorNominatim, "_buscar", side_effect=ErrorGeocodificacion("caido")
        ):
            respuesta = self.client.get(reverse("analisis:geocodificar"), {"q": "Juliaca"})
        self.assertEqual(respuesta.status_code, 503)

    def test_el_endpoint_rechaza_coordenadas_invalidas(self):
        usuario = Usuario.objects.create_user("vecino", password="x")
        self.client.force_login(usuario)
        respuesta = self.client.get(
            reverse("analisis:geocodificar_inverso"), {"lat": "abc", "lng": "-70"}
        )
        self.assertEqual(respuesta.status_code, 400)


@override_settings(MEDIA_ROOT=MEDIA_DE_PRUEBA)
class LimpiezaDeArchivosTest(TestCase):
    """Al borrar un analisis deben irse tambien sus archivos."""

    def test_borra_el_archivo_del_disco(self):
        usuario = Usuario.objects.create_user("vecino", password="x")
        ruta = Path(MEDIA_DE_PRUEBA) / "prueba_borrado.jpg"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"contenido")

        analisis = crear_analisis(usuario, archivo="prueba_borrado.jpg")
        self.assertTrue(ruta.exists())

        analisis.delete()
        self.assertFalse(ruta.exists(), "El archivo quedo huerfano en el disco")


class PaginasTest(TestCase):
    """Las paginas principales responden y no dejan etiquetas sin procesar."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user("vecino", password="x")
        crear_zona()

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_responden(self):
        for nombre in ("analisis:panel", "analisis:historial", "analisis:mapa",
                       "deteccion:modulo", "usuarios:perfil"):
            with self.subTest(pagina=nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 200)

    def test_el_geojson_es_valido(self):
        respuesta = self.client.get(reverse("analisis:geojson"))
        self.assertEqual(respuesta.json()["type"], "FeatureCollection")

    def test_las_coordenadas_no_se_localizan_en_el_javascript(self):
        """Con locale es-PE, -15.65 se escribiria -15,65 y romperia el mapa."""
        import re

        html = self.client.get(reverse("analisis:mapa")).content.decode()
        scripts = re.findall(
            r"<script(?![^>]*type=\"application/json\")[^>]*>(.*?)</script>", html, re.S
        )
        self.assertFalse(
            re.findall(r"-\d+,\d+", "\n".join(scripts)),
            "Hay coordenadas con coma decimal dentro del JavaScript",
        )

    def test_las_tablas_anchas_se_pueden_desplazar(self):
        """Sin envoltorio, una tabla de muchas columnas rompe la vista en movil."""
        import re

        for nombre in ("analisis:historial", "analisis:panel", "usuarios:perfil"):
            html = self.client.get(reverse(nombre)).content.decode()
            for tabla in re.finditer(r"<table.*?</table>", html, re.S):
                cabecera = re.search(r"<tr.*?</tr>", tabla.group(0), re.S)
                columnas = len(re.findall(r"<t[hd]", cabecera.group(0))) if cabecera else 0
                if columnas <= 3:
                    continue  # clave/valor: cabe de sobra
                envuelta = "table-responsive" in html[max(0, tabla.start() - 400):tabla.start()]
                self.assertTrue(
                    envuelta, f"Tabla de {columnas} columnas sin envolver en {nombre}"
                )

    def test_todas_las_paginas_declaran_el_viewport(self):
        for nombre in ("analisis:panel", "analisis:historial", "analisis:mapa",
                       "deteccion:modulo", "usuarios:perfil"):
            with self.subTest(pagina=nombre):
                html = self.client.get(reverse(nombre)).content.decode()
                self.assertIn('name="viewport"', html)

    def test_los_graficos_tienen_contenedor_con_altura(self):
        """Chart.js con maintainAspectRatio:false lo exige, o no dibuja nada."""
        import re

        html = self.client.get(reverse("analisis:panel")).content.decode()
        for ident in re.findall(r'<canvas[^>]*id="([^"]+)"', html):
            posicion = html.find(f'id="{ident}"')
            self.assertIn(
                "lienzo-grafico", html[max(0, posicion - 220):posicion],
                f"El lienzo {ident} no esta dentro de un contenedor con altura",
            )
