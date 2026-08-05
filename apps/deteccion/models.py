"""
Esta app no define modelos a proposito.

`deteccion` es la capa de inteligencia artificial y captura: el motor YOLO, el
clasificador de severidad y las cinco formas de alimentarlo. Todo lo que se
guarda en la base de datos vive en `apps.analisis`.

Mantener el archivo (vacio) evita sorpresas: Django lo espera al recorrer las
apps instaladas.
"""
