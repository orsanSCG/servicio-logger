"""Integración con Celery.

En el módulo donde se crea la app de Celery, después de ``app.config_from_object(...)``::

    from servicio_logger.celery import setup_celery_logging
    setup_celery_logging(app)

Qué hace:

* evita que Celery reemplace el logger raíz con su propio formato de texto y
  aplica ``settings.LOGGING`` de Django (o la config por defecto);
* asocia ``task_id`` / ``task_name`` al contexto de log mientras corre una tarea;
* propaga el ``request_id`` del request web que encoló la tarea, así
  ``| json | request_id="..."`` en Grafana muestra el request Y sus tareas;
* emite una línea ``Task finished`` por tarea en ``servicio_logger.task`` con
  ``extra.task = {name, state, duration_ms, queue, retries}``.

Los errores ya los registra Celery (``celery.app.trace``, nivel ERROR, con
traceback); con esta configuración esas líneas salen en JSON y con el contexto de la tarea.
"""
import logging
import logging.config
import time

from . import context
from .config import TASK_LOGGER, get_logging_config

task_logger = logging.getLogger(TASK_LOGGER)

REQUEST_ID_HEADER = 'servicio_logger_request_id'

_running = {}
_connected = False


def _default_logging_config():
    try:
        from django.conf import settings
        if settings.configured and getattr(settings, 'LOGGING', None):
            return settings.LOGGING
    except Exception:
        pass
    return get_logging_config()


def on_setup_logging(**kwargs):
    logging.config.dictConfig(_logging_config())


def on_before_task_publish(headers=None, **kwargs):
    request_id = context.get('request_id')
    if request_id and headers is not None:
        headers.setdefault(REQUEST_ID_HEADER, request_id)


def _incoming_request_id(task):
    request = getattr(task, 'request', None)
    if request is None:
        return None
    value = getattr(request, REQUEST_ID_HEADER, None)
    if value:
        return value
    headers = getattr(request, 'headers', None) or {}
    return headers.get(REQUEST_ID_HEADER)


def on_task_prerun(task_id=None, task=None, **kwargs):
    tokens = context.bind(
        task_id=task_id,
        task_name=getattr(task, 'name', None),
        # Las tareas eager (CELERY_TASK_ALWAYS_EAGER) corren dentro del request web: se mantiene su id.
        request_id=_incoming_request_id(task) or context.get('request_id'),
    )
    _running[task_id] = (tokens, time.perf_counter())


def on_task_postrun(task_id=None, task=None, state=None, **kwargs):
    tokens, start = _running.pop(task_id, (None, None))
    try:
        if start is not None:
            request = getattr(task, 'request', None)
            delivery_info = getattr(request, 'delivery_info', None) or {}
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            task_logger.info(
                'Task finished %s %s %sms',
                getattr(task, 'name', None),
                state,
                duration_ms,
                extra={
                    'task': {
                        'name': getattr(task, 'name', None),
                        'state': state,
                        'duration_ms': duration_ms,
                        'queue': delivery_info.get('routing_key'),
                        'retries': getattr(request, 'retries', None),
                    },
                },
            )
    finally:
        if tokens:
            context.reset(tokens)


_logging_config = _default_logging_config


def setup_celery_logging(app=None, logging_config=None):
    """Conecta las señales de Celery. Se puede llamar más de una vez sin problema.

    :param app: la app de Celery (no se usa, se mantiene por legibilidad / opciones futuras).
    :param logging_config: dict de dictConfig o un callable que lo retorne. Por
        defecto ``settings.LOGGING`` de Django cuando Django está configurado.
    """
    global _connected, _logging_config
    if logging_config is not None:
        _logging_config = logging_config if callable(logging_config) else (lambda: logging_config)
    if _connected:
        return
    from celery import signals

    signals.setup_logging.connect(on_setup_logging, weak=False)
    signals.before_task_publish.connect(on_before_task_publish, weak=False)
    signals.task_prerun.connect(on_task_prerun, weak=False)
    signals.task_postrun.connect(on_task_postrun, weak=False)
    _connected = True
