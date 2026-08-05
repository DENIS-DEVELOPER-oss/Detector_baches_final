"""
Configuracion de gunicorn.

    gunicorn -c gunicorn.conf.py config.wsgi:application

Esta aplicacion no es una web normal: el analisis de una imagen tarda unos
segundos y el de un video puede tardar minutos, todo dentro de la peticion.
Por eso los valores por defecto de gunicorn (30 s de timeout) no sirven.
"""

import os

# El puerto lo suele imponer la plataforma
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Cada worker carga su propia copia del modelo YOLO (unos 200 MB de RAM).
# Con 2 se atienden dos analisis a la vez sin dispararse la memoria; suba el
# numero solo si el servidor tiene RAM de sobra.
workers = int(os.getenv("WEB_CONCURRENCY", "2"))

# Hilos para que un analisis largo no deje al worker sordo ante peticiones
# ligeras (paginas, estaticos, consultas al mapa).
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_class = "gthread"

# 5 minutos: un video de varios minutos supera de largo los 30 s por defecto.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))
graceful_timeout = 60
keepalive = 5

# Reciclar workers de vez en cuando libera la memoria que retiene PyTorch
max_requests = 200
max_requests_jitter = 40

# Cargar la aplicacion antes de bifurcar comparte memoria entre workers
preload_app = True

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
