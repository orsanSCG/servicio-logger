import pytest

pytest.importorskip('django')

from django.test import Client  # noqa: E402

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
