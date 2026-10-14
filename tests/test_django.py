import pytest

pytest.importorskip('django')

from django.test import Client, override_settings  # noqa: E402

from servicio_logger import log_context  # noqa: E402
from servicio_logger.config import ACCESS_LOGGER  # noqa: E402


def _by_logger(lines, name):
    return [line for line in lines if line['logger'] == name]


def test_generates_request_id_and_access_line(capture):
    response = Client().get('/ok')
    request_id = response['X-Request-ID']
    assert len(request_id) == 32

    view_line = _by_logger(capture.lines, 'tests.views')[0]
    (access,) = _by_logger(capture.lines, ACCESS_LOGGER)
    assert view_line['request_id'] == request_id
    assert access['request_id'] == request_id
    assert access['level'] == 'INFO'
    http = access['extra']['http']
    assert http['method'] == 'GET'
    assert http['path'] == '/ok'
    assert http['status'] == 200
    assert http['duration_ms'] >= 0
    assert log_context.get('request_id') is None  # contexto limpio después del request


def test_reuses_incoming_request_id(capture):
    response = Client().get('/ok', HTTP_X_REQUEST_ID='abc-123')
    assert response['X-Request-ID'] == 'abc-123'
    (access,) = _by_logger(capture.lines, ACCESS_LOGGER)
    assert access['request_id'] == 'abc-123'


def test_rejects_malicious_request_id():
    response = Client().get('/ok', HTTP_X_REQUEST_ID='bad id\n{"level":"x"}')
    assert response['X-Request-ID'] != 'bad id\n{"level":"x"}'


def test_status_codes(capture):
    Client().get('/missing')
    Client(raise_request_exception=False).get('/boom')
    statuses = [line['extra']['http']['status'] for line in _by_logger(capture.lines, ACCESS_LOGGER)]
    assert statuses == [404, 500]


def test_skip_paths(capture):
    Client().get('/health')
    assert _by_logger(capture.lines, ACCESS_LOGGER) == []


# Umbrales chicos para que los tests corran rápido (las vistas duermen 0.3 s y 0.7 s).
FAST_THRESHOLDS = {
    'SERVICIO_LOGGER_ACCESS_SLOW_MS': 200,
    'SERVICIO_LOGGER_ACCESS_VERY_SLOW_MS': 600,
}


def _access(capture):
    return [
        (line['extra']['http']['path'], line['extra']['http']['method'], line['level'], line['extra']['http']['slow'])
        for line in _by_logger(capture.lines, ACCESS_LOGGER)
    ]


def test_notable_mode_skips_fast_successful_reads(capture):
    with override_settings(SERVICIO_LOGGER_ACCESS_MODE='notable', **FAST_THRESHOLDS):
        client = Client(raise_request_exception=False)
        response = client.get('/ok')
        client.get('/missing')
        client.get('/boom')
        client.post('/ok')
        client.get('/slow')
        client.get('/very-slow')
    assert response['X-Request-ID']  # el request omitido igual tiene id
    assert _by_logger(capture.lines, 'tests.views')[0]['request_id'] == response['X-Request-ID']
    assert _access(capture) == [
        ('/missing', 'GET', 'INFO', None),
        ('/boom', 'GET', 'INFO', None),
        ('/ok', 'POST', 'INFO', None),
        ('/slow', 'GET', 'WARNING', 'slow'),
        ('/very-slow', 'GET', 'ERROR', 'very_slow'),
    ]


def test_all_mode_also_flags_slowness(capture):
    with override_settings(SERVICIO_LOGGER_ACCESS_MODE='all', **FAST_THRESHOLDS):
        client = Client()
        client.get('/ok')
        client.get('/slow')
    assert _access(capture) == [
        ('/ok', 'GET', 'INFO', None),
        ('/slow', 'GET', 'WARNING', 'slow'),
    ]


def test_invalid_mode_falls_back_to_all(capture):
    with override_settings(SERVICIO_LOGGER_ACCESS_MODE='xyz'):
        Client().get('/ok')
    assert len(_by_logger(capture.lines, ACCESS_LOGGER)) == 1
