# Modelos de detección

Modelos YOLO entrenados para detectar daños en el pavimento.

| Archivo | Clases | Tamaño | ¿En el repositorio? |
|---|---|---|---|
| `detector_baches_v2_bache_grieta.pt` | `pothole`, `crack` | 38.6 MB | **Sí** (es el activo) |
| `detector_baches.pt` | `pothole`, `crack` | 38.6 MB | No |
| `detector_baches_v1_pothole.pt` | `pothole` | 49.6 MB | No |

Solo se versiona el modelo activo: los otros dos son variantes de entrenamiento y subir
los tres dejaría un repositorio de 127 MB, lento de clonar.

## Cambiar de modelo

Ponga el archivo en esta carpeta y ajuste el `.env`:

```ini
YOLO_MODEL=el_que_quiera.pt
```

Reinicie el servidor. `MotorYOLO` carga el `.pt` una sola vez por proceso, así que un
cambio en caliente no surte efecto.

## Comprobar que funciona

```bash
python manage.py probar_deteccion ruta/a/una/foto.jpg
python manage.py probar_deteccion foto.jpg --todos-los-modelos
```

Medición sobre una foto real de bache en carretera, con la configuración de producción
(`imgsz=640`, `conf=0.35`):

| Modelo | Mejor confianza |
|---|---|
| `detector_baches_v2_bache_grieta.pt` | 91.2 % |
| `detector_baches.pt` | 91.2 % |
| `detector_baches_v1_pothole.pt` | 94.1 % (pero no detecta grietas) |
