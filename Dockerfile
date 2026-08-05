# ---------------------------------------------------------------------------
# Imagen del Detector de Baches
#
#   docker build -t detector-baches .
#   docker run --env-file .env -p 8000:8000 detector-baches
#
# Punto clave: se instala la version de PyTorch **solo para CPU**. La normal
# arrastra las librerias de CUDA y la imagen pasa de ~1 GB a mas de 5 GB, para
# nada: en un servidor sin GPU no se usan.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias del sistema:
#   build-essential, pkg-config, default-libmysqlclient-dev -> compilar mysqlclient
#   libgl1, libglib2.0-0                                    -> OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        default-libmysqlclient-dev \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# PyTorch para CPU primero, para que pip no baje despues la variante con CUDA
RUN pip install --no-cache-dir \
        torch torchvision \
        --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Los estaticos se recogen al construir. SECRET_KEY es un valor de relleno:
# collectstatic no lo usa, pero settings.py exige uno con DEBUG=False.
RUN DEBUG=False SECRET_KEY=solo-para-collectstatic \
    python manage.py collectstatic --noinput

# Los analisis se guardan aqui. Montelo como volumen o se perderan al reiniciar.
VOLUME ["/app/media"]

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "config.wsgi:application"]
