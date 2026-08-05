# Detector de Baches — Detección automática con IA

Sistema web en Django que detecta **baches (`pothole`)** y **grietas (`crack`)** en vías de
Juliaca y Puno usando un modelo YOLO entrenado, y **clasifica automáticamente cada daño**
por nivel de severidad.

No es un sistema de reportes ciudadanos: no hay estados de seguimiento, ni asignación de
inspectores, ni flujos de trabajo. Todo gira alrededor del análisis por inteligencia artificial.

---

## 1. Requisitos

| Componente | Versión | Nota |
|---|---|---|
| Python | 3.12 | |
| Django | 5.0.x | Última serie compatible con **MariaDB 10.4** (la que trae XAMPP). Django 5.1+ exige 10.5+; 6.0 exige 10.6+. |
| MariaDB | 10.4.32 (XAMPP en `D:\xampp`) | |
| Ultralytics + PyTorch | 8.4 / 2.6 | |

```bash
pip install -r requirements.txt
```

## 2. Puesta en marcha

1. Arrancar **MySQL** desde el panel de XAMPP.
2. Crear la base de datos si no existe:
   ```sql
   CREATE DATABASE baches_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
3. Migrar y sembrar:
   ```bash
   python manage.py migrate
   python manage.py cargar_datos_iniciales
   ```
4. Levantar el servidor:
   ```bash
   python manage.py runserver
   ```
5. Abrir <http://127.0.0.1:8000/>

### Usuarios de demostración

| Usuario | Contraseña | Rol | Ciudad |
|---|---|---|---|
| `admin` | `admin123` | Administrador | Juliaca |
| `vanessa` | `vanessa123` | Ciudadano | Juliaca |
| `denis` | `denis123` | Ciudadano | Puno |
| `aldo` | `aldo123` | Ciudadano | Juliaca |

> Son contraseñas de demostración: **cámbielas antes de cualquier uso real**. Se
> asignan con `set_password()`, que no pasa por `AUTH_PASSWORD_VALIDATORS`; el
> formulario de registro sí rechazaría claves tan simples.

Para actualizar los datos o la contraseña de usuarios que ya existen:

```bash
python manage.py cargar_datos_iniciales --reiniciar-usuarios
```

Sin ese modificador, los usuarios existentes se respetan. El comando nunca borra
cuentas: si encuentra otras, solo las lista.

## 3. Roles

El sistema maneja **exactamente dos roles**:

| Rol | Puede |
|---|---|
| **Administrador** | Todo: ve las detecciones de todos los usuarios, accede a estadísticas globales, gestiona usuarios (rol, activación, datos) y entra al panel de Django. |
| **Ciudadano** | Iniciar sesión, usar el módulo de detección en sus cinco modos y consultar **su propio** historial y resultados. |

### Sin registro público

El sistema **no admite altas públicas**: no existe `/cuentas/registro/`. Las cuentas las
crea el administrador en `/cuentas/gestion/` → **Crear usuario**, eligiendo el rol, y desde
ahí edita datos, rol y activación.

Es una decisión deliberada: al ser un sistema de detección automática para una entidad
concreta, no tiene sentido que cualquiera se dé de alta.

### Sin panel de Django

El panel de administración de Django **está desmontado**: `/admin/` devuelve 404 y ninguna
página enlaza a él. Tiene otro aspecto visual y no hace falta, porque la gestión de
usuarios vive dentro de la aplicación.

Para una tarea de mantenimiento puntual se puede activar desde el `.env`:

```ini
ADMIN_DJANGO=True
ADMIN_DJANGO_URL=panel-interno/     # no lo deje en "admin/"
```

Conviene volver a `False` al terminar.

### Pantalla de acceso

- Pantalla partida: panel de marca a la izquierda, formulario a la derecha; en móvil el
  panel se oculta y queda solo el formulario.
- Mostrar/ocultar contraseña, aviso de bloqueo de mayúsculas (causa habitual del
  «usuario o contraseña incorrectos») y `autocomplete` correcto para los gestores de claves.
- **Mantener la sesión iniciada**: sin marcar, la sesión caduca al cerrar el navegador;
  marcada, dura 14 días (`AccesoView.DIAS_RECORDAR`).
- Con sesión abierta, `/cuentas/login/` redirige al panel en vez de volver a pedir acceso.

## 4. Módulo de detección — cinco modos

En `/deteccion/`, una sola página con selector de modo:

| # | Modo | Cómo funciona |
|---|---|---|
| 1 | **Subir imagen** | Arrastrar o elegir JPG/PNG/WEBP. Vista previa antes de analizar. |
| 2 | **Subir video** | MP4/WEBM/AVI/MOV. Se recorre muestreando ~4 cuadros por segundo. |
| 3 | **Tomar foto** | `getUserMedia` → se congela el cuadro y se envía como JPEG. |
| 4 | **Grabar video** | `MediaRecorder` (VP8/WebM) con cronómetro; el blob se adjunta al formulario y se analiza cuadro por cuadro. |
| 5 | **Detección en vivo** | El navegador manda cuadros a `/deteccion/vivo/analizar/` (1–6 por segundo, ajustable) y dibuja las cajas sobre un canvas, coloreadas por severidad. Se puede congelar el cuadro actual y guardarlo. |

Los cinco terminan en lo mismo: un `Analisis` guardado, con sus `Bache` ya clasificados.
Todos comparten un mapa Leaflet para fijar la ubicación (por zona, por clic o por GPS).

## 5. Clasificación automática de severidad

Cada daño detectado recibe un nivel: **Baja · Media · Alta · Crítica**, y se guarda en la
columna `bache.severidad`. La regla vive en `ClasificadorSeveridad`
([apps/deteccion/services.py](apps/deteccion/services.py)):

1. **El área que ocupa el daño en el cuadro es el factor principal.** Umbrales sobre la
   fracción del cuadro: `< 1%` → Baja, `< 3.5%` → Media, `< 9%` → Alta, resto → Crítica.
2. **Una grieta baja un nivel** respecto de un bache del mismo tamaño: no representa el
   mismo riesgo para el vehículo.
3. **Una detección con confianza < 0.45 baja un nivel**, para no exagerar la gravedad
   cuando el modelo duda.

Nunca baja de `Baja`. Los umbrales son parámetros del constructor, así que se pueden
ajustar sin tocar el resto del código.

A nivel de `Analisis` se guardan además los contadores por nivel (`sev_baja`, `sev_media`,
`sev_alta`, `sev_critica`), la **severidad máxima** (la que colorea el mapa) y la
**severidad predominante** (la más frecuente; ante empate gana la más grave).

## 5b. Mapas y georreferenciación

### Librerías

| Librería | Para qué |
|---|---|
| **django-leaflet** | Mapas: sirve Leaflet, gestiona los plugins y centraliza el encuadre y los tiles en `LEAFLET_CONFIG` (settings.py). |
| **geopy** | Georreferenciación real: dirección ↔ coordenadas contra Nominatim (OpenStreetMap). Sin clave de API. |
| Google Maps JS API | Opcional. Se activa solo si define `GOOGLE_MAPS_API_KEY`. |

### Capa única de mapas

Todos los mapas pasan por [static/js/mapas.js](static/js/mapas.js):

```
MapaBase (abstracta)
  ├── MapaGoogle    → Google Maps JavaScript API   (si hay clave)
  └── MapaLeaflet   → django-leaflet + OpenStreetMap (por defecto)

crearMapa(...)      → Factory: promesa con la implementación ya inicializada
Geocodificador      → cliente de los endpoints de geopy
```

Las páginas solo llaman a `crearMapa({contenedor, centro, zoom})` y después a
`cargarGeoJSON()`, `agrupar()`, `ajustarVista()` o `habilitarSeleccion()`. No saben qué
proveedor hay debajo: cambiarlo es tocar un solo archivo.

### django-leaflet sin GeoDjango

`django-leaflet` **no está en `INSTALLED_APPS`** a propósito: su `admin.py` importa
`django.contrib.gis`, que exige GDAL y rompería el arranque. En su lugar se usa solo la
parte que no depende de GeoDjango:

```python
TEMPLATES[0]["OPTIONS"]["libraries"] = {"leaflet_tags": "leaflet.templatetags.leaflet_tags"}
TEMPLATES[0]["DIRS"]  += [LEAFLET_DIR / "templates"]   # leaflet/css.html, leaflet/js.html
STATICFILES_DIRS      += [LEAFLET_DIR / "static"]      # leaflet.js, leaflet.css, iconos
```

`LEAFLET_DIR` se localiza con `importlib.util.find_spec` **sin importar el paquete**: al
importarlo, `leaflet.app_settings` congelaría su configuración antes de que `settings.py`
llegue a definir `LEAFLET_CONFIG`.

Los plugins se piden por nombre (`{% leaflet_js plugins="markercluster" %}`), no con
`plugins="ALL"`, que arrastraría `leaflet.draw` — el editor de geometrías de GeoDjango.

### Ubicar cada foto en el mapa

Todo análisis se puede georreferenciar **en cualquier momento**, no solo al subirlo. Un
análisis sin coordenadas no aparece en el mapa de baches, y antes no había forma de
arreglarlo.

| Momento | Cómo |
|---|---|
| Al subir | Buscador de direcciones, clic en el mapa, GPS del navegador o zona |
| Automático | Si la foto trae **GPS en su EXIF**, se usa solo (típico en fotos de celular) |
| Después | `/historial/<id>/ubicacion/` — mapa a pantalla completa, buscador y GPS |

Dónde aparece la opción:

- **Historial**: los análisis sin ubicar muestran un aviso ámbar *«Sin ubicar — situar en
  el mapa»* que lleva directo al editor.
- **Detalle**: si no tiene ubicación, una llamada a la acción *«Ubicar en el mapa»*; si ya
  la tiene, el mapa con su dirección y un botón *Cambiar*.

Precedencia de coordenadas: **lo que marca el usuario manda**. Si solo eligió una zona, el
GPS de la foto la sustituye por ser más preciso que el centro del sector. La lectura del
EXIF ([apps/analisis/exif.py](apps/analisis/exif.py)) nunca interrumpe un análisis: si la
foto no trae GPS o viene dañada, simplemente no aporta nada.

Solo el dueño del análisis y el administrador pueden cambiar su ubicación.

### Georreferenciación con geopy

[apps/analisis/geocodificacion.py](apps/analisis/geocodificacion.py):

```
GeocodificadorBase (abstracta)   → contrato + caché
  └── GeocodificadorNominatim    → OpenStreetMap (singleton)
```

| Endpoint | Qué hace |
|---|---|
| `/api/geocodificar/?q=...` | Dirección escrita → lista de coordenadas candidatas |
| `/api/geocodificar/inverso/?lat=&lng=` | Coordenadas → dirección legible |

En el módulo de detección eso se traduce en un **buscador de direcciones** (escriba
«Av. Circunvalación, Juliaca» y el mapa salta ahí) y en el **relleno automático** de la
referencia al marcar un punto en el mapa.

Nominatim exige identificarse y no pasar de 1 petición por segundo: se cumple con
`NOMINATIM_USER_AGENT`, `RateLimiter` de geopy y una caché de 24 h. Los resultados se
sesgan a Perú con `GEOCODIFICACION_PAIS`.

### Google Maps

Hay dos formas de usar Google Maps, según tenga o no clave de API.

**Sin clave — puente «pegar desde Google Maps»** (funciona ya, sin configurar nada):

En el módulo de detección y en el editor de ubicación hay un bloque *Elegir el punto en
Google Maps* con:

- Botón **Abrir Google Maps**, que abre el punto actual (o el encuadre general) en una
  pestaña nueva. Ahí puede moverse, usar Street View y elegir el sitio exacto.
- Campo para **pegar** lo que copió. Al pegar, el marcador salta solo. Acepta:

  | Formato | Ejemplo |
  |---|---|
  | Coordenadas (clic derecho en Google Maps) | `-15.4997, -70.1330` |
  | Enlace de la barra de direcciones | `.../maps/@-15.4997,-70.133,17z` |
  | Enlace de un lugar | `.../maps/place/Juliaca/@-15.4997,-70.133,15z/...` |
  | Enlace con parámetro | `...?q=`, `?ll=`, `?query=`, `?center=` |

  Los enlaces cortos (`goo.gl/maps/...`) **no** sirven: no contienen las coordenadas.
  Ábralos primero en el navegador y copie la URL ya expandida.

En el detalle de un análisis ubicado hay además un botón **Ver en Google Maps**.

**Con clave — Google Maps dentro de la aplicación:**

1. Obtenga una clave en <https://console.cloud.google.com/google/maps-apis/credentials>
   con **Maps JavaScript API** habilitada y facturación activa.
2. Póngala en `.env`: `GOOGLE_MAPS_API_KEY=AIzaSy...`
3. Reinicie el servidor.

Todos los mapas pasan a ser de Google —incluida la selección del punto haciendo clic o
arrastrando el marcador— sin tocar una línea de código: lo resuelve la fábrica de
[mapas.js](static/js/mapas.js). El puente de pegado sigue disponible.

Sin clave no se rompe nada: se usa django-leaflet. La georreferenciación con geopy
funciona igual en ambos casos.

### Sobre `django-map-widgets`

No se usa. Importa `django.contrib.gis` (`mapwidgets/widgets/base.py`), que exige las
librerías nativas **GDAL** y **GEOS**. GEOS se puede obtener vía `shapely`, pero **GDAL no
tiene wheel para Windows + Python 3.12** y `pip install gdal` falla al compilar. Además
solo aporta un *widget de formulario* para elegir un punto: no cubre el mapa del dashboard,
el mapa global con agrupación ni el del detalle.

### Códec de los videos anotados

`cv2.VideoWriter` solo sabe escribir **MPEG-4 Parte 2** (fourcc `FMP4`). Es un formato
válido y cualquier reproductor de escritorio lo abre, pero **Chrome, Edge y Firefox no lo
decodifican**: el reproductor se queda congelado en 0:00. Los códecs que sí aceptan dentro
de un MP4 son H.264 (`avc1`), HEVC y AV1, y opencv-python no trae el codificador de H.264
por licencia.

Por eso el video se escribe primero con OpenCV y después se recodifica a H.264 con
**ffmpeg**, que llega dentro de `imageio-ffmpeg` (ya viene con ultralytics). Además de
hacerlo reproducible, el archivo encoge bastante: en una prueba real, de 7.5 MB a 2.5 MB.

Detalles de la conversión ([apps/deteccion/video.py](apps/deteccion/video.py)):
`-pix_fmt yuv420p` (el único espacio de color que aceptan todos los navegadores),
un filtro de escala que fuerza dimensiones pares (H.264 no admite impares) y
`-movflags +faststart` para que empiece a reproducirse sin descargar el archivo entero.

Si ffmpeg no estuviera disponible, el análisis **no se pierde**: se conserva el archivo tal
cual y la página de detalle ofrece descargarlo.

Para los videos generados antes de esta corrección:

```bash
python manage.py recodificar_videos --revisar   # solo informa
python manage.py recodificar_videos             # convierte los incompatibles
python manage.py recodificar_videos --todos     # rehace todos
```

### Portada de los videos

Un video no puede mostrarse como imagen en una tarjeta, y un icono genérico no dice nada
de lo que se detectó. Por eso, al analizar un video se guarda una **miniatura**: el cuadro
con más daños y más graves, **ya con las cajas dibujadas**.

El cuadro se elige puntuando cada uno con el peso de sus detecciones
(Baja 1, Media 2, Alta 3, Crítica 4) y quedándose con el mayor. Solo compiten los cuadros
realmente analizados; en el resto las cajas son las del análisis anterior y podrían no
corresponder.

Esa miniatura se usa en las tarjetas del historial (con un distintivo de video y el número
de cuadros analizados) y como `poster` del reproductor en el detalle.

Para los videos analizados antes de que existiera esta función:

```bash
python manage.py generar_miniaturas
python manage.py generar_miniaturas --rehacer   # tambien los que ya la tienen
```

No vuelve a ejecutar YOLO: el video anotado ya trae las cajas y la base de datos sabe en
qué cuadro apareció cada daño, así que solo hay que extraer el mejor.

### Diagnóstico del modelo

Si el detector «no encuentra nada», este comando dice si el problema es la foto, el umbral
o el modelo elegido — sin pasar por la web:

```bash
python manage.py probar_deteccion C:\ruta\a\su\foto.jpg
python manage.py probar_deteccion foto.jpg --conf 0.15        # baja el umbral
python manage.py probar_deteccion foto.jpg --todos-los-modelos # compara los 3 .pt
python manage.py probar_deteccion video.mp4 --guardar salida.mp4
```

Cuando no detecta nada, hace además un barrido de umbrales y le dice a partir de cuál
empieza a encontrar algo.

Medición sobre una foto real de bache en carretera (400×300), con la configuración de
producción (`imgsz=640`, `conf=0.35`):

| Modelo | Mejor confianza |
|---|---|
| `detector_baches_v2_bache_grieta.pt` *(activo)* | 91.2 % |
| `detector_baches.pt` | 91.2 % |
| `detector_baches_v1_pothole.pt` | 94.1 % (pero no detecta grietas) |

## 6. Dashboard

- Tarjetas con **total de baches**, grietas, análisis realizados y confianza media.
- Una tarjeta por **nivel de severidad**, con cantidad y **porcentaje**.
- Dona de distribución + barras de porcentaje por categoría.
- Evolución mensual de análisis y daños.
- Origen de los análisis (cuál de los cinco modos se usa más).
- Ranking de zonas más dañadas.
- **Mapa** con los baches geolocalizados, coloreados por severidad.
- **Historial de detecciones** reciente.

Un ciudadano ve su propia información; el administrador ve la de todo el sistema.

## 7. Estructura

```
APLICACION_POO2/
├── ai_models/                 modelos YOLO (.pt)
├── apps/
│   ├── usuarios/              usuario personalizado, 2 roles, gestión
│   ├── analisis/              dominio: Zona, Analisis, Bache + dashboard, historial, mapa
│   └── deteccion/             motor YOLO + módulo de captura (5 modos)
├── config/
├── media/                     archivos analizados y resultados anotados
├── static/
│   ├── css/estilos.css
│   └── js/modulo_deteccion.js
└── templates/
```

### Rutas principales

| Ruta | Descripción |
|---|---|
| `/` | Dashboard |
| `/historial/` | Historial de detecciones (propio o global) |
| `/historial/<id>/` | Detalle con la clasificación de cada daño |
| `/mapa/` | Mapa de baches |
| `/estadisticas/` | Estadísticas globales *(admin)* |
| `/deteccion/` | Módulo de detección — los 5 modos |
| `/deteccion/vivo/analizar/` | Inferencia sobre un cuadro (POST, JSON) |
| `/deteccion/api/modelo/` | Diagnóstico: confirma que el `.pt` carga |
| `/cuentas/gestion/` | Gestión de usuarios *(admin)* |
| `/admin/` | Panel de administración de Django |

## 8. Diseño orientado a objetos

| Concepto | Dónde |
|---|---|
| **Herencia + clase abstracta** | `PersonaBase` → `Usuario`; `RegistroBase` → `Zona`, `Analisis` |
| **Polimorfismo (Strategy)** | `DetectorBase` → `DetectorImagen`, `DetectorVideo`, `DetectorCuadro` |
| **Método plantilla** | `DetectorBase.procesar()` mide tiempo y captura errores; cada subclase implementa `_ejecutar()` |
| **Factory** | `FabricaDetectores.crear()` / `estrategia_por_archivo()` |
| **Singleton** | `MotorYOLO` carga el `.pt` una sola vez por proceso (thread-safe) |
| **Regla de negocio encapsulada** | `ClasificadorSeveridad`, inyectable en cualquier detector |
| **Objetos de valor** | `CajaDetectada`, `ResultadoProceso` (dataclasses) |
| **Composición 1:N** | `Analisis` agrega `Bache` |
| **Manager/QuerySet propios** | `AnalisisQuerySet.visibles_para()`, `BacheQuerySet.de_nivel()`, `UsuarioManager` |
| **Mixins** | `MixinBootstrap`, `GuardarAnalisisMixin`, `AdminRequeridoMixin`, `ResumenSeveridadMixin` |
| **Clases en el cliente** | `Camara`, `GestorModos`, `GestorUbicacion`, `CapturaFoto`, `GrabadorVideo`, `DeteccionVivo` |

`UsuarioManager` hereda de `UserManager` a propósito: si se reemplaza por un
`QuerySet.as_manager()` se pierden `create_user`, `create_superuser` y `normalize_email`,
y se rompen el registro y `manage.py createsuperuser`.

## 9. Pruebas

```bash
python manage.py test
```

60 pruebas repartidas en las tres apps:

| Archivo | Qué cubre |
|---|---|
| `apps/deteccion/tests.py` | Reglas del clasificador de severidad, objetos de valor, la fábrica de detectores y que el vídeo salga en H.264 |
| `apps/analisis/tests.py` | Recálculo de contadores, visibilidad por rol, editor de ubicación, geocodificación (con geopy simulado) y borrado de archivos |
| `apps/usuarios/tests.py` | Los dos roles, el manager propio, acceso y gestión de usuarios |

Dos pruebas merecen mención porque protegen de errores que ya ocurrieron una vez:

- **Coordenadas sin localizar**: con `LANGUAGE_CODE = es-pe`, `-15.65` se escribiría
  `-15,65` y rompería el mapa. Una prueba recorre el JavaScript de la página buscando comas
  decimales.
- **Lienzos con altura**: Chart.js con `maintainAspectRatio:false` no dibuja nada si su
  contenedor no tiene altura. Una prueba verifica que todo `<canvas>` esté dentro de un
  `.lienzo-grafico`.

Las que necesitan el modelo `.pt` se saltan solas si el archivo no está, para que la suite
siga siendo útil en una copia recién clonada.

## 10. Despliegue

> **Guía paso a paso para un VPS con Ubuntu: [DESPLIEGUE.md](DESPLIEGUE.md)**
> (sistema, MariaDB, gunicorn como servicio, nginx, HTTPS y copias de seguridad).
>
> Para contenedores está el [Dockerfile](Dockerfile), con PyTorch solo para CPU.

### Antes de subir a GitHub

El `.gitignore` ya excluye lo que no debe publicarse: **`.env`** (secretos), **`media/`**
(archivos de usuarios) y **`ai_models/*.pt`**. Compruébelo antes del primer envío:

```bash
git status --short        # el .env no debe aparecer
```

### Preparar el servidor

1. **Variables de entorno** — copie `.env.example` a `.env` y ajuste:

   ```ini
   DEBUG=False
   SECRET_KEY=<genere una nueva, ver .env.example>
   ALLOWED_HOSTS=midominio.com,www.midominio.com
   CSRF_TRUSTED_ORIGINS=https://midominio.com
   ```

   Con `DEBUG=False` y la `SECRET_KEY` por defecto, el proyecto **se niega a arrancar**:
   es intencionado, para que no salga a producción con la clave de desarrollo.

2. **Seguridad automática** — al poner `DEBUG=False` se activan solos HTTPS obligatorio,
   HSTS, cookies seguras, `X-Frame-Options: DENY` y la cabecera de proxy inverso. No hay
   que tocar nada.

3. **Estáticos** — WhiteNoise los sirve sin necesidad de nginx:

   ```bash
   python manage.py collectstatic --noinput
   ```

4. **Base de datos** — cree la base, migre y siembre:

   ```bash
   python manage.py migrate
   python manage.py cargar_datos_iniciales
   python manage.py createsuperuser     # y borre los usuarios de demostracion
   ```

5. **Servidor**:

   ```bash
   gunicorn config.wsgi:application --bind 0.0.0.0:8000 --timeout 300
   ```

   El `--timeout` alto es necesario: el análisis corre dentro de la petición y un vídeo
   largo tarda.

### Lo que hay que resolver antes de un despliegue serio

- **Tamaño**: `torch` + `torchvision` + `ultralytics` ocupan unos **2.5 GB**, más 40 MB por
  modelo. La mayoría de capas gratuitas (Render, Railway, PythonAnywhere) no lo admiten.
  Alternativas: un VPS pequeño, o exportar el modelo a **ONNX** y usar `onnxruntime`
  (~200 MB en vez de 2.5 GB).
- **Análisis síncrono**: bloquea un *worker* de gunicorn mientras dura. Con más de un
  usuario simultáneo hace falta **Celery** con Redis.
- **`media/` no es persistente** en plataformas con sistema de archivos efímero: los
  análisis desaparecen al reiniciar. Hay que montar un volumen o usar S3
  (`django-storages`).
- **Contraseñas de demostración**: `admin123` y compañía no deben sobrevivir al despliegue.

## 11. Notas y limitaciones

- **Zonas horarias en MariaDB**: XAMPP no carga las tablas `mysql.time_zone*`, así que
  `TruncMonth` falla. La agregación mensual se hace en Python (`PanelView._serie_mensual`).
- **Procesamiento síncrono**: el análisis corre dentro del request. Para videos largos
  conviene mover `ProcesadorAnalisis` a una tarea en segundo plano (Celery / django-q).
- **Cámara**: `getUserMedia` y `MediaRecorder` solo funcionan en `localhost` o bajo HTTPS.
  Desde un celular en la misma red hace falta HTTPS o un túnel.
- **Formato de la grabación**: el navegador produce WebM/VP8. OpenCV lo lee mediante
  FFmpeg. Si en algún equipo falla, el análisis lo reporta como error del archivo y basta
  con subir el video en MP4.
- **Decimales y JavaScript** (importante): el locale es `es-PE`, así que Django escribe
  `-15.65` como `-15,65`. **Nunca interpole un número directamente en JavaScript**:
  `centro: [{{ MAPA_CENTRO.lat }}, {{ MAPA_CENTRO.lng }}]` se renderiza como
  `[-15,65, -70,1]`, que en JS es un arreglo de **cuatro** números. Ese fue el motivo de
  que el mapa apareciera en gris: Leaflet acababa centrado en `lat -15, lng 65`, en mitad
  del océano Índico, donde los tiles son de un gris uniforme.

  La regla del proyecto: todo número que vaya al JavaScript viaja por `json_script`
  (`{{ MAPA_CENTRO|json_script:"mapa-centro-json" }}`) o por `CONFIG_MAPAS`. El texto
  visible sí conserva el formato peruano (`37,5%`, `-15,4997000`).

  Relacionado: `{% leaflet_json_config %}` se autoescapa; dentro de `<script>` hay que
  envolverlo en `{% autoescape off %}` o las `&quot;` rompen la sintaxis.
- **Coordenadas de las zonas**: aproximadas al centro del sector; se ajustan desde
  `/admin/analisis/zona/`.
