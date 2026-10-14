"""Logging estructurado (JSON) compartido para servicios Django / Celery / gunicorn.

Ver README.md para el esquema de log y los pasos de integración.
"""
from . import context as log_context
from .config import get_component, get_gunicorn_logconfig, get_logging_config
from .formatters import SCHEMA_VERSION, ConsoleFormatter, JsonFormatter

__version__ = '0.1.0'

__all__ = [
    'SCHEMA_VERSION',
    'ConsoleFormatter',
    'JsonFormatter',
    'get_component',
    'get_gunicorn_logconfig',
    'get_logging_config',
    'log_context',
    '__version__',
]
