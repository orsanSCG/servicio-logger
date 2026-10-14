"""Integración con Django.

Agregar al inicio de ``MIDDLEWARE`` (justo después de ``SecurityMiddleware``)::

    'servicio_logger.django.RequestContextMiddleware',

Qué hace en cada request:

* toma ``X-Request-ID`` del request entrante (o genera uno) y lo asocia al
  contexto de log, así cada línea de log de ese request lleva ``request_id``;
* retorna el id en el header de respuesta ``X-Request-ID``;
* emite UNA línea de acceso en el logger ``servicio_logger.access`` con
  ``extra.http = {method, path, status, duration_ms, ip, user, slow}``.

Settings opcionales:

* ``SERVICIO_LOGGER_SKIP_PATHS``: tupla de prefijos de path que no generan línea
  de acceso (health checks, archivos estáticos...).
* ``SERVICIO_LOGGER_ACCESS_MODE``: ``'all'`` (por defecto, una línea por request) o
  ``'notable'`` (solo requests con status >= 400, lentos, o que escriben:
  POST/PUT/PATCH/DELETE). En ``'notable'`` los GET rápidos y exitosos (p.ej. polling)
  no generan línea, pero siguen teniendo ``request_id``.
* ``SERVICIO_LOGGER_ACCESS_SLOW_MS`` (por defecto 10000): desde esta duración la
  línea sale en WARNING con ``slow="slow"``.
* ``SERVICIO_LOGGER_ACCESS_VERY_SLOW_MS`` (por defecto 30000): desde esta duración
  la línea sale en ERROR con ``slow="very_slow"``.
"""
import logging
import re
import time
import uuid

from . import context
from .config import ACCESS_LOGGER

access_logger = logging.getLogger(ACCESS_LOGGER)

REQUEST_ID_HEADER = 'X-Request-ID'
_REQUEST_ID_META = 'HTTP_X_REQUEST_ID'
_VALID_REQUEST_ID = re.compile(r'^[A-Za-z0-9._:\-]{1,128}$')

DEFAULT_SKIP_PATHS = ('/favicon.ico',)
DEFAULT_ACCESS_MODE = 'all'
DEFAULT_SLOW_MS = 10000
DEFAULT_VERY_SLOW_MS = 30000

ACCESS_MODES = ('all', 'notable')
# Métodos que solo leen: en modo 'notable' no generan línea si son rápidos y exitosos.
READ_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


def _setting(name, default):
    try:
        from django.conf import settings
        return getattr(settings, name, default)
    except Exception:
        return default


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _user_identifier(request):
    # DRF copia el usuario autenticado al HttpRequest subyacente, así que esto
    # funciona con sesión y con token/OIDC. Se lee solo al momento de la respuesta.
    try:
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        return str(getattr(user, 'username', None) or user.pk)
    except Exception:
        return None


class RequestContextMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response
        self.skip_paths = tuple(_setting('SERVICIO_LOGGER_SKIP_PATHS', DEFAULT_SKIP_PATHS))
        mode = str(_setting('SERVICIO_LOGGER_ACCESS_MODE', DEFAULT_ACCESS_MODE)).lower()
        self.access_mode = mode if mode in ACCESS_MODES else DEFAULT_ACCESS_MODE
        self.slow_ms = int(_setting('SERVICIO_LOGGER_ACCESS_SLOW_MS', DEFAULT_SLOW_MS))
        self.very_slow_ms = int(_setting('SERVICIO_LOGGER_ACCESS_VERY_SLOW_MS', DEFAULT_VERY_SLOW_MS))

    def __call__(self, request):
        incoming = request.META.get(_REQUEST_ID_META, '')
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id

        tokens = context.bind(request_id=request_id, user=None)
        start = time.perf_counter()
        try:
            response = self.get_response(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            response[REQUEST_ID_HEADER] = request_id

            user = _user_identifier(request)
            if user:
                context.bind(user=user)
            if not request.path.startswith(self.skip_paths):
                self._log_access(request, response, duration_ms, user)
            return response
        finally:
            context.reset(tokens)

    def _slowness(self, duration_ms):
        if duration_ms >= self.very_slow_ms:
            return 'very_slow'
        if duration_ms >= self.slow_ms:
            return 'slow'
        return None

    def _is_notable(self, request, status, slow):
        return status >= 400 or slow is not None or request.method not in READ_METHODS

    def _log_access(self, request, response, duration_ms, user):
        status = response.status_code
        slow = self._slowness(duration_ms)
        if self.access_mode == 'notable' and not self._is_notable(request, status, slow):
            return
        level = {'very_slow': logging.ERROR, 'slow': logging.WARNING}.get(slow, logging.INFO)
        access_logger.log(
            level,
            '%s %s %s %sms',
            request.method,
            request.path,
            status,
            duration_ms,
            extra={
                'http': {
                    'method': request.method,
                    'path': request.path,
                    'status': status,
                    'duration_ms': duration_ms,
                    'ip': _client_ip(request),
                    'user': user,
                    'slow': slow,
                },
            },
        )
