# Despliegue en un VPS con Ubuntu

Guía completa para poner el Detector de Baches en un servidor propio con acceso SSH
(Hostinger, DigitalOcean, Hetzner, Contabo, AWS EC2…).

**Requisitos mínimos del servidor**: Ubuntu 22.04 o 24.04, **2 GB de RAM** (4 GB
recomendado: cada worker carga el modelo YOLO) y **10 GB de disco**.

Sustituya `midominio.com` por su dominio y `denis` por su usuario en todo el documento.

## ¿Tiene dominio?

De esto depende un ajuste importante:

| Situación | Qué hacer |
|---|---|
| **Tengo dominio** apuntando al servidor | Siga la guía completa, incluido el paso 9 (HTTPS) |
| **Solo tengo la IP** | Ponga `SECURE_SSL_REDIRECT=False` en el `.env` y **sáltese el paso 9** |

Sin certificado y con `SECURE_SSL_REDIRECT=True`, el navegador entra en un bucle de
redirecciones. Y aunque lo evitara, las cookies seguras no viajan por HTTP y **sería
imposible iniciar sesión**, sin ningún mensaje que lo explique. Por eso ese ajuste
desactiva las tres cosas a la vez.

> Por IP funciona todo, pero **las contraseñas viajan sin cifrar**. Es aceptable para
> probar; en cuanto tenga dominio, active HTTPS.

---

## 1. Preparar el sistema

Conéctese por SSH y actualice:

```bash
ssh denis@IP_DEL_SERVIDOR
sudo apt update && sudo apt upgrade -y
```

Instale las dependencias. Cada bloque tiene su motivo:

```bash
sudo apt install -y \
    python3.12 python3.12-venv python3-pip \
    mariadb-server \
    nginx \
    git \
    build-essential pkg-config default-libmysqlclient-dev \
    libgl1 libglib2.0-0 \
    ffmpeg
```

| Paquete | Para qué |
|---|---|
| `build-essential pkg-config default-libmysqlclient-dev` | Compilar `mysqlclient` |
| `libgl1 libglib2.0-0` | OpenCV no arranca sin estas librerías |
| `ffmpeg` | Recodificar el vídeo anotado a H.264 |

> `ffmpeg` también llega dentro de `imageio-ffmpeg`, pero el del sistema es más rápido y
> el proyecto lo prefiere si existe.

---

## 2. Base de datos

Asegure MariaDB y cree la base:

```bash
sudo mysql_secure_installation
```

Responda: contraseña de root **sí**, quitar usuarios anónimos **sí**, prohibir acceso
remoto de root **sí**, borrar la base `test` **sí**.

```bash
sudo mysql
```

```sql
CREATE DATABASE baches_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'baches'@'localhost' IDENTIFIED BY 'PONGA_AQUI_UNA_CLAVE_FUERTE';
GRANT ALL PRIVILEGES ON baches_db.* TO 'baches'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

**No use el usuario root de MySQL para la aplicación.**

---

## 3. Traer el código

```bash
sudo mkdir -p /var/www
sudo chown $USER:$USER /var/www
cd /var/www
git clone https://github.com/DENIS-DEVELOPER-oss/Detector_baches_final.git baches
cd baches
```

---

## 4. Entorno de Python

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

**Instale PyTorch para CPU antes que nada.** La versión normal descarga las librerías de
CUDA: son unos 2.5 GB que en un servidor sin GPU no se usan para nada.

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

Diferencia real: **~700 MB** frente a **~3 GB**.

---

## 5. Configuración

Genere una clave secreta nueva:

```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

Cree el archivo `.env`:

```bash
nano .env
```

```ini
SECRET_KEY=pegue-aqui-la-clave-que-acaba-de-generar
DEBUG=False

# Con dominio:
ALLOWED_HOSTS=midominio.com,www.midominio.com
CSRF_TRUSTED_ORIGINS=https://midominio.com,https://www.midominio.com

# Solo con IP: use estas dos lineas en lugar de las anteriores y anada
# SECURE_SSL_REDIRECT=False
# ALLOWED_HOSTS=203.0.113.10
# CSRF_TRUSTED_ORIGINS=http://203.0.113.10

DB_NAME=baches_db
DB_USER=baches
DB_PASSWORD=la-clave-fuerte-del-paso-2
DB_HOST=127.0.0.1
DB_PORT=3306

YOLO_MODEL=detector_baches_v2_bache_grieta.pt
YOLO_CONF=0.35

GOOGLE_MAPS_API_KEY=
NOMINATIM_USER_AGENT=detector-baches-juliaca-puno
```

Protéjalo para que solo lo lea su usuario:

```bash
chmod 600 .env
```

> Con `DEBUG=False` y la `SECRET_KEY` de desarrollo, el proyecto **se niega a arrancar**.
> Es a propósito.

---

## 6. Migrar y preparar

```bash
python manage.py migrate
python manage.py cargar_datos_iniciales    # 20 zonas + las 4 cuentas de prueba
python manage.py collectstatic --noinput
```

### Sobre las cuentas de prueba

El sistema se despliega como **demostración abierta**: la pantalla de acceso muestra las
cuatro cuentas con su contraseña para que cualquiera pueda probarlo.

**Esto implica que cualquier visitante puede entrar como `admin`** y borrar análisis,
usuarios y zonas. Es una decisión consciente, apropiada para presentar el proyecto.

Si más adelante quiere cerrarlo:

```bash
# 1. Ocultar el bloque de la pantalla de acceso
echo "MOSTRAR_CUENTAS_DEMO=False" >> .env

# 2. Crear su cuenta real y borrar las de prueba
python manage.py createsuperuser
python manage.py shell -c "
from apps.usuarios.models import Usuario
Usuario.objects.filter(username__in=['admin','vanessa','denis','aldo']).delete()"

sudo systemctl restart baches
```

Mientras siga abierto, tenga programada la copia de seguridad (sección
[Copia de seguridad](#copia-de-seguridad)): si alguien borra algo, se restaura en un minuto.

Compruebe que Django está conforme:

```bash
python manage.py check --deploy    # debe decir: no issues
```

---

## 7. Gunicorn como servicio

```bash
sudo nano /etc/systemd/system/baches.service
```

```ini
[Unit]
Description=Detector de Baches
After=network.target mariadb.service

[Service]
User=denis
Group=www-data
WorkingDirectory=/var/www/baches
EnvironmentFile=/var/www/baches/.env
ExecStart=/var/www/baches/.venv/bin/gunicorn -c gunicorn.conf.py config.wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now baches
sudo systemctl status baches      # debe aparecer "active (running)"
```

Si falla, el motivo estará en:

```bash
sudo journalctl -u baches -n 50 --no-pager
```

---

## 8. Nginx

```bash
sudo nano /etc/nginx/sites-available/baches
```

```nginx
server {
    listen 80;
    server_name midominio.com www.midominio.com;

    # Los videos y fotos pueden ser grandes: el limite por defecto es 1 MB
    client_max_body_size 120M;

    # El analisis tarda; sin esto nginx corta a los 60 s
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    location /media/ {
        alias /var/www/baches/media/;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # Sin esta cabecera Django cree que la peticion es HTTP y entra en un
        # bucle infinito de redirecciones con SECURE_SSL_REDIRECT.
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/baches /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t          # debe decir: syntax is ok
sudo systemctl reload nginx
```

Los estáticos los sirve WhiteNoise desde la propia aplicación; `media/` va por nginx
porque son archivos de usuario y conviene cachearlos.

---

## 9. HTTPS

> **Sáltese este paso si solo tiene la IP.** Let's Encrypt no emite certificados para
> direcciones IP; necesita un dominio apuntando al servidor.

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d midominio.com -d www.midominio.com
```

Certbot edita nginx y programa la renovación automática. Compruébela:

```bash
sudo certbot renew --dry-run
```

**Hasta este paso el sitio no funcionará**: `SECURE_SSL_REDIRECT` obliga a HTTPS y sin
certificado el navegador entra en bucle. Es lo esperado.

---

## 10. Permisos de `media/`

Gunicorn escribe ahí y nginx lee:

```bash
mkdir -p /var/www/baches/media
sudo chown -R denis:www-data /var/www/baches/media
sudo chmod -R 775 /var/www/baches/media
```

---

## 11. Comprobar que todo va

```bash
curl -I https://midominio.com/cuentas/login/     # 200
curl -I http://midominio.com/                    # 301 a https
sudo systemctl status baches nginx mariadb
```

Y desde el navegador: entre, suba una foto con un bache y confirme que aparece anotada.

---

## Actualizar el código más adelante

```bash
cd /var/www/baches
git pull
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart baches
```

---

## Copia de seguridad

Tres cosas hay que salvar: la base de datos, `media/` y el `.env`.

```bash
mysqldump -u baches -p baches_db | gzip > ~/baches_$(date +%F).sql.gz
tar czf ~/media_$(date +%F).tar.gz -C /var/www/baches media
```

Automatícelo con `crontab -e`:

```cron
0 3 * * * /usr/bin/mysqldump -u baches -pCLAVE baches_db | gzip > /home/denis/copias/baches_$(date +\%F).sql.gz
```

---

## Notas para Hostinger

- **Firewall**: el panel muestra «Reglas del firewall: 0», lo que significa que **no hay
  ninguna regla y todo el tráfico pasa**. Configure `ufw` en el propio servidor
  (paso 1b, más abajo). Si además crea reglas en el panel, abra 22, 80 y 443.
- **Acceso root**: Hostinger entrega el VPS con acceso `root`. Trabajar siempre como root
  es arriesgado; el paso 1b crea un usuario normal.
- **Snapshots**: el panel ofrece copias del disco entero. Son útiles, pero **no sustituyen
  al `mysqldump`**: restaurar un snapshot revierte todo el servidor, no solo la base.
  Haga uno *antes* de empezar, para poder volver atrás si algo sale mal.
- **KVM 2** (2 vCPU, 8 GB de RAM) va sobrado. Puede subir a `WEB_CONCURRENCY=3` en el
  `.env` si quiere atender más análisis a la vez.

### 1b. Usuario y firewall

```bash
# Como root, crear un usuario normal
adduser denis
usermod -aG sudo denis

# Firewall: solo SSH, HTTP y HTTPS
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status
```

Cierre la sesión y vuelva a entrar como el usuario nuevo:

```bash
ssh denis@LA_IP_DE_SU_VPS
```

> No habilite `ufw` sin haber permitido antes OpenSSH: se quedaría fuera del servidor.

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| Bucle de redirecciones | Falta `proxy_set_header X-Forwarded-Proto $scheme;` en nginx |
| `413 Request Entity Too Large` | Suba `client_max_body_size` en nginx |
| `502 Bad Gateway` al analizar un vídeo | Suba `proxy_read_timeout` y `GUNICORN_TIMEOUT` |
| `ImportError: libGL.so.1` | Falta `libgl1`: `sudo apt install libgl1` |
| El vídeo no se reproduce | Falta ffmpeg: `sudo apt install ffmpeg` y luego `python manage.py recodificar_videos` |
| El servicio muere al analizar | Poca RAM. Baje a `WEB_CONCURRENCY=1` o amplíe el servidor |
| Los estáticos no cargan | Falta `collectstatic`, o `DEBUG=True` en el `.env` |
| `ValueError: Missing staticfiles manifest entry` | Falta `collectstatic` |
| Entro por IP y no puedo iniciar sesión | Falta `SECURE_SSL_REDIRECT=False` en el `.env`: las cookies seguras no viajan por HTTP |
| `DisallowedHost` | Añada el dominio o la IP a `ALLOWED_HOSTS` |

---

## Después de desplegar

1. Verifique en GitHub que **no se subió ningún `.env`** ni ningún `.sql`.
2. **Programe las copias de seguridad.** Con las cuentas de prueba visibles, cualquiera
   puede borrar datos: la copia es su red de seguridad.
3. `media/` crece rápido con vídeos: vigile el disco con `df -h`.
4. Entre y compruebe el flujo completo: iniciar sesión con una cuenta de prueba, subir una
   foto con un bache y ver que aparece anotada y clasificada.
