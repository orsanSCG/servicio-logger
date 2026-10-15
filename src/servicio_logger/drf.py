"""Integración con Django REST Framework.

En ``REST_FRAMEWORK`` de los settings::

    'EXCEPTION_HANDLER': 'servicio_logger.drf.log_exception_handler',

DRF convierte las excepciones de la API (``ValidationError``, ``NotFound``,
``PermissionDenied``...) en respuestas 4xx sin dejar nada en el log, así que la
línea de acceso solo dice "400". Este handler devuelve exactamente la misma
respuesta que el handler por defecto de DRF y además registra UNA línea en el
logger ``servicio_logger.drf`` con:

* qué vista y acción respondió (``extra.view``, ``extra.action``);
* qué se le devolvió al cliente (``extra.response``, recortado);
* dónde se lanzó el error en el código del proyecto (``extra.origin``).

El body del request NO se registra (puede contener datos personales o claves).
Los errores no manejados (500) no pasan por aquí como 4xx: Django ya los registra
en ``django.request`` con el traceback completo.
"""
import json
import logging
import traceback

from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler

from .config import DRF_LOGGER

logger = logging.getLogger(DRF_LOGGER)

# Respuestas esperables del día a día (sesión vencida, sin permiso, recurso inexistente):
# se registran en INFO para no inflar las alertas de WARNING.
INFO_STATUSES = frozenset({401, 403, 404, 405})

# Excepciones "de negocio" que no necesitan traceback completo: con ``origin`` alcanza.
SIN_TRACEBACK = (
    exceptions.ValidationError,
    exceptions.ParseError,
    exceptions.NotFound,
    exceptions.NotAuthenticated,
    exceptions.AuthenticationFailed,
    exceptions.PermissionDenied,
    exceptions.MethodNotAllowed,
)

MAX_RESUMEN = 300
MAX_RESPONSE = 2000
_LIBRERIAS = ('site-packages', 'dist-packages')


def _resumen(data):
    """Primer mensaje de error en formato ``campo: mensaje``."""
    camino = []
    while True:
        if isinstance(data, dict) and data:
            clave, data = next(iter(data.items()))
            if clave not in ('detail', 'non_field_errors'):
                camino.append(str(clave))
        elif isinstance(data, (list, tuple)) and data:
            data = data[0]
        else:
            break
    texto = f"{'.'.join(camino)}: {data}" if camino else str(data)
    return texto[:MAX_RESUMEN]


def _response_segura(data):
    """``response.data`` serializable y acotado para que la línea de log no crezca sin límite."""
    try:
        texto = json.dumps(data, default=str, ensure_ascii=False)
    except Exception:
        return repr(data)[:MAX_RESPONSE]
    if len(texto) <= MAX_RESPONSE:
        return json.loads(texto)
    return texto[:MAX_RESPONSE] + '…'


def _origen(exc):
    """Último frame del traceback que pertenece al código del proyecto (no a librerías)."""
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    propios = [f for f in frames if not any(lib in f.filename for lib in _LIBRERIAS)]
    frame = (propios or frames or [None])[-1]
    if frame is None:
        return None
    archivo = frame.filename.replace('\\', '/').rsplit('/', 3)[-3:]
    return f"{'/'.join(archivo)}:{frame.lineno} en {frame.name}"


def _vista(context):
    view = context.get('view')
    request = context.get('request')
    nombre = type(view).__name__ if view is not None else None
    # Las function views (@api_view) quedan envueltas en WrappedAPIView: usar el nombre real.
    if view is not None and nombre == 'WrappedAPIView':
        handler = getattr(view, request.method.lower(), None) if request is not None else None
        nombre = getattr(handler, '__name__', nombre)
    accion = getattr(view, 'action', None) or (request.method if request is not None else None)
    return nombre, accion


def log_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None or not 400 <= response.status_code < 500:
        return response

    try:
        status = response.status_code
        vista, accion = _vista(context)
        logger.log(
            logging.INFO if status in INFO_STATUSES else logging.WARNING,
            '%s.%s respondió %s: %s',
            vista,
            accion,
            status,
            _resumen(response.data),
            exc_info=None if isinstance(exc, SIN_TRACEBACK) else exc,
            extra={
                'view': vista,
                'action': accion,
                'status': status,
                'exc_type': type(exc).__name__,
                'response': _response_segura(response.data),
                'origin': _origen(exc),
            },
        )
    except Exception:  # un error al registrar nunca debe cambiar la respuesta de la API
        pass
    return response
