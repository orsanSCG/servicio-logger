"""Diccionarios listos para ``logging.config.dictConfig``.

Django::

    from servicio_logger import get_logging_config
    LOGGING = get_logging_config(module='mi-servicio')

Variables de entorno (todas opcionales):

* ``LOG_LEVEL``     nivel raíz, por defecto ``INFO``.
* ``LOG_FORMAT``    ``json`` (por defecto, lo que espera Loki) o ``console`` (desarrollo local).
* ``LOG_COMPONENT`` web / worker / cron ...
* ``ENVIRONMENT``, ``RELEASE`` se copian en cada línea.
"""
import os

JSON_FORMATTER = 'servicio_logger.formatters.JsonFormatter'
CONSOLE_FORMATTER = 'servicio_logger.formatters.ConsoleFormatter'

ACCESS_LOGGER = 'servicio_logger.access'
TASK_LOGGER = 'servicio_logger.task'

# Loggers de terceros demasiado verbosos en INFO.
QUIET_LOGGERS = (
    'django.db.backends',
    'django.utils.autoreload',
    'urllib3',
    'botocore',
    'boto3',
    's3transfer',
    'requests_oauthlib',
    'oauthlib',
    'PIL',
    'asyncio',
)

VALID_FORMATS = ('json', 'console')


def _resolve(level, fmt):
    level = (level or os.environ.get('LOG_LEVEL') or 'INFO').upper()
    fmt = (fmt or os.environ.get('LOG_FORMAT') or 'json').lower()
    if fmt not in VALID_FORMATS:
        fmt = 'json'
    return level, fmt


def _formatters(module, component, environment=None, release=None):
    common = {}
    for key, value in (
        ('module', module),
        ('component', component),
        ('environment', environment),
        ('release', release),
    ):
        if value:
            common[key] = value
    return {
        'json': {'()': JSON_FORMATTER, **common},
        'console': {'()': CONSOLE_FORMATTER, **common},
    }


def get_logging_config(
    module=None,
    level=None,
    fmt=None,
    component=None,
    environment=None,
    release=None,
    loggers=None,
):
    """Retorna un dict de dictConfig que envía todo a stdout con el esquema compartido.

    Todos los argumentos son opcionales y, si vienen vacíos, se usa su variable
    de entorno. Pasar valores leídos con ``decouple.config`` cuando viven en el
    archivo ``.env`` y no en el entorno real.

    :param module: nombre del módulo escrito en cada línea. Por defecto ``LOG_MODULE``.
    :param level: nivel raíz, sobrescribe ``LOG_LEVEL``.
    :param fmt: ``json`` o ``console``, sobrescribe ``LOG_FORMAT``.
    :param component: sobrescribe ``LOG_COMPONENT``.
    :param environment: sobrescribe ``ENVIRONMENT``.
    :param release: sobrescribe ``RELEASE``.
    :param loggers: entradas de loggers adicionales/sobrescritas que se agregan a la config.
    """
    level, fmt = _resolve(level, fmt)

    config_loggers = {
        # El DEFAULT_LOGGING de Django agrega sus propios handlers de texto a estos;
        # se eliminan y todo fluye al handler JSON raíz.
        'django': {'handlers': [], 'level': level, 'propagate': True},
        'django.server': {'handlers': [], 'level': level, 'propagate': True},
        # Los 4xx ya se ven en la línea de acceso (servicio_logger.access). Aquí solo
        # quedan los 5xx: traen el traceback de la excepción no manejada.
        'django.request': {'handlers': [], 'level': 'ERROR', 'propagate': True},
        ACCESS_LOGGER: {'handlers': [], 'level': 'INFO', 'propagate': True},
    }
    for name in QUIET_LOGGERS:
        config_loggers[name] = {'handlers': [], 'level': 'WARNING', 'propagate': True}
    if loggers:
        config_loggers.update(loggers)

    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': _formatters(module, component, environment, release),
        'handlers': {
            'stdout': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stdout',
                'formatter': fmt,
            },
        },
        'loggers': config_loggers,
        'root': {'level': level, 'handlers': ['stdout']},
    }


def get_gunicorn_logconfig(module=None, level=None, fmt=None, component=None):
    """dictConfig para los loggers propios de gunicorn (arranque, worker timeouts...).

    Las líneas de acceso las emite ``servicio_logger.django.RequestContextMiddleware``,
    por eso ``gunicorn.access`` queda silenciado.
    """
    level, fmt = _resolve(level, fmt)
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': _formatters(module, component),
        'handlers': {
            'stdout': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stdout',
                'formatter': fmt,
            },
        },
        'loggers': {
            'gunicorn.error': {'handlers': ['stdout'], 'level': level, 'propagate': False},
            'gunicorn.access': {'handlers': [], 'level': 'CRITICAL', 'propagate': False},
        },
        'root': {'level': level, 'handlers': ['stdout']},
    }


def get_component(default='web'):
    """Valor de ``LOG_COMPONENT`` (útil para el ``server_name`` de Sentry)."""
    return os.environ.get('LOG_COMPONENT') or default
