"""
Pruebas del motor de deteccion.

Se ejecutan con:
    python manage.py test

Las que necesitan el modelo YOLO se saltan si falta el archivo .pt, para que la
suite siga siendo util en una copia recien clonada del repositorio.
"""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, TestCase

from apps.deteccion.services import (
    ALTA, BAJA, CRITICA, MEDIA, CajaDetectada, ClasificadorSeveridad,
    FabricaDetectores, ResultadoProceso,
)
from apps.deteccion.video import codec_de, recodificar_para_web, ruta_ffmpeg

HAY_MODELO = Path(settings.YOLO_MODEL_PATH).exists()


class ClasificadorSeveridadTest(SimpleTestCase):
    """La regla de clasificacion, sin tocar la red neuronal."""

    def setUp(self):
        self.clasificador = ClasificadorSeveridad()

    def test_el_area_marca_el_nivel(self):
        casos = [(0.005, BAJA), (0.020, MEDIA), (0.050, ALTA), (0.200, CRITICA)]
        for area, esperado in casos:
            with self.subTest(area=area):
                self.assertEqual(
                    self.clasificador.clasificar("pothole", 0.9, area), esperado
                )

    def test_una_grieta_baja_un_nivel(self):
        """Una grieta no supone el mismo riesgo que un bache del mismo tamano."""
        self.assertEqual(self.clasificador.clasificar("pothole", 0.9, 0.05), ALTA)
        self.assertEqual(self.clasificador.clasificar("crack", 0.9, 0.05), MEDIA)

    def test_la_confianza_dudosa_baja_un_nivel(self):
        self.assertEqual(self.clasificador.clasificar("pothole", 0.90, 0.05), ALTA)
        self.assertEqual(self.clasificador.clasificar("pothole", 0.30, 0.05), MEDIA)

    def test_nunca_baja_de_baja(self):
        self.assertEqual(self.clasificador.clasificar("crack", 0.1, 0.0001), BAJA)

    def test_los_umbrales_son_configurables(self):
        estricto = ClasificadorSeveridad(
            umbrales=((0.001, BAJA), (0.002, MEDIA), (0.003, ALTA))
        )
        self.assertEqual(estricto.clasificar("pothole", 0.9, 0.05), CRITICA)


class CajaDetectadaTest(SimpleTestCase):
    def test_calcula_su_area(self):
        caja = CajaDetectada("pothole", 0.9, 0.1, 0.1, 0.3, 0.6)
        self.assertAlmostEqual(caja.area_relativa, 0.2 * 0.5)

    def test_area_cero_si_la_caja_esta_invertida(self):
        caja = CajaDetectada("pothole", 0.9, 0.5, 0.5, 0.2, 0.2)
        self.assertEqual(caja.area_relativa, 0.0)

    def test_se_serializa_con_la_severidad(self):
        datos = CajaDetectada("crack", 0.5, 0, 0, 1, 1, severidad=ALTA).como_dict()
        self.assertEqual(datos["severidad"], ALTA)
        self.assertEqual(datos["clase"], "crack")


class ResultadoProcesoTest(SimpleTestCase):
    def test_resume_por_severidad(self):
        resultado = ResultadoProceso(cajas=[
            CajaDetectada("pothole", 0.9, 0, 0, 1, 1, severidad=BAJA),
            CajaDetectada("pothole", 0.9, 0, 0, 1, 1, severidad=BAJA),
            CajaDetectada("crack", 0.9, 0, 0, 1, 1, severidad=CRITICA),
        ])
        self.assertEqual(resultado.total, 3)
        self.assertEqual(resultado.contar_clase("pothole"), 2)
        self.assertEqual(resultado.resumen_severidad()[BAJA], 2)
        self.assertEqual(resultado.resumen_severidad()[MEDIA], 0)

    def test_un_error_lo_marca_como_fallido(self):
        self.assertFalse(ResultadoProceso(error="algo").exitoso)
        self.assertTrue(ResultadoProceso().exitoso)


class FabricaDetectoresTest(SimpleTestCase):
    def test_elige_la_estrategia_por_la_extension(self):
        self.assertEqual(
            FabricaDetectores.estrategia_por_archivo("foto.JPG"),
            FabricaDetectores.ESTRATEGIA_IMAGEN,
        )
        self.assertEqual(
            FabricaDetectores.estrategia_por_archivo("clip.webm"),
            FabricaDetectores.ESTRATEGIA_VIDEO,
        )

    def test_rechaza_una_extension_desconocida(self):
        with self.assertRaises(ValueError):
            FabricaDetectores.estrategia_por_archivo("documento.pdf")

    def test_la_version_tolerante_devuelve_none(self):
        self.assertIsNone(FabricaDetectores.estrategia_por_archivo_seguro("x.pdf"))


class VideoParaNavegadorTest(TestCase):
    """El video anotado debe quedar en un codec que el navegador reproduzca."""

    def test_hay_ffmpeg_disponible(self):
        self.assertIsNotNone(
            ruta_ffmpeg(),
            "Sin ffmpeg los videos quedan en MPEG-4 Parte 2 y el navegador no los "
            "reproduce. Instale imageio-ffmpeg.",
        )

    def test_recodifica_a_h264(self):
        if not ruta_ffmpeg():
            self.skipTest("ffmpeg no disponible")

        with tempfile.TemporaryDirectory() as carpeta:
            # Dimensiones impares a proposito: H.264 solo admite pares
            origen = Path(carpeta) / "origen.mp4"
            imagen = np.full((301, 401, 3), 120, dtype=np.uint8)
            escritor = cv2.VideoWriter(
                str(origen), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (401, 301)
            )
            for _ in range(10):
                escritor.write(imagen)
            escritor.release()

            destino = Path(carpeta) / "salida.mp4"
            self.assertTrue(recodificar_para_web(origen, destino))
            self.assertIn(codec_de(destino).lower(), ("h264", "avc1"))


@unittest.skipUnless(HAY_MODELO, "Falta el archivo .pt del modelo")
class DetectorImagenTest(TestCase):
    """Prueba de humo del motor: que cargue y responda sin reventar."""

    def test_analiza_una_imagen_sin_errores(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "via.jpg"
            cv2.imwrite(str(ruta), np.full((480, 640, 3), 105, dtype=np.uint8))

            detector = FabricaDetectores.crear(FabricaDetectores.ESTRATEGIA_IMAGEN)
            resultado = detector.procesar(ruta, Path(carpeta) / "salida.jpg")

            self.assertTrue(resultado.exitoso, resultado.error)
            self.assertEqual(resultado.frames_analizados, 1)
            self.assertTrue((Path(carpeta) / "salida.jpg").exists())

    def test_un_archivo_ilegible_devuelve_error_sin_lanzar(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "roto.jpg"
            ruta.write_bytes(b"esto no es una imagen")

            # El detector registra el fallo; aqui se silencia para no ensuciar
            # la salida de la suite con una traza que se espera.
            with self.assertLogs("apps.deteccion.services", level="ERROR"):
                resultado = FabricaDetectores.crear(
                    FabricaDetectores.ESTRATEGIA_IMAGEN
                ).procesar(ruta)

            self.assertFalse(resultado.exitoso)
            self.assertIn("imagen", resultado.error.lower())
