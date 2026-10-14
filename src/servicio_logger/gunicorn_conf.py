"""Módulo de configuración para gunicorn.

Uso::

    gunicorn proyecto.wsgi:application -c python:servicio_logger.gunicorn_conf --bind ... --workers ...

Los flags de línea de comandos siguen teniendo prioridad sobre este archivo, así
que aquí solo se configura el logging. Definir ``LOG_MODULE`` en el entrypoint
para que las líneas propias de gunicorn también lleven el nombre del módulo
(en este punto todavía no se cargan los settings de Django).
"""
from servicio_logger.config import get_gunicorn_logconfig

logconfig_dict = get_gunicorn_logconfig()

# Las líneas de acceso vienen de servicio_logger.django.RequestContextMiddleware.
accesslog = None
