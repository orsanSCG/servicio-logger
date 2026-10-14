"""Integración con Django.

Agregar al inicio de ``MIDDLEWARE`` (justo después de ``SecurityMiddleware``)::

    'servicio_logger.django.RequestContextMiddleware',

Qué hace en cada request:

* toma ``X-Request-ID`` del request entrante (o genera uno) y lo asocia al
  contexto de log, así cada línea de log de ese request lleva ``request_id``;
* retorna el id en el header de respuesta ``X-Request-ID``;
* emite UNA línea de acceso en el logger ``servicio_logger.access`` con
  ``extra.http = {method, path, status, duration_ms, ip, user}``.

Setting opcional ``SERVICIO_LOGGER_SKIP_PATHS``: tupla de prefijos de path que no
generan línea de acceso (health checks, archivos estáticos...).
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


def _skip_paths():
    try:
        from django.conf import settings
        return tuple(getattr(settings, 'SERVICIO_LOGGER_SKIP_PATHS', DEFAULT_SKIP_PATHS))
    except Exception:
        return DEFAULT_SKIP_PATHS


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
        self.skip_paths = _skip_paths()

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

    def _log_access(self, request, response, duration_ms, user):
        status = response.status_code
        access_logger.info(
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
                },
            },
        )
