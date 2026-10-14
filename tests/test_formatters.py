import json
import logging

from servicio_logger import SCHEMA_VERSION, log_context
from servicio_logger.formatters import ConsoleFormatter, JsonFormatter

SCHEMA_KEYS = [
    'schema_version', 'ts', 'level', 'logger', 'msg', 'module', 'component', 'environment',
    'release', 'request_id', 'user', 'task_id', 'task_name', 'file', 'line', 'func', 'process',
    'exc_type', 'exc_message', 'stack', 'extra',
]

logger = logging.getLogger('tests.formatters')


def test_schema_keys_always_present_and_ordered(capture):
    logger.info('hola %s', 'mundo')
    (line,) = capture.lines
    assert list(line) == SCHEMA_KEYS
    assert line['schema_version'] == SCHEMA_VERSION
    assert line['msg'] == 'hola mundo'
    assert line['level'] == 'INFO'
    assert line['module'] == 'testmod'
    assert line['component'] == 'web'
    assert line['environment'] == 'stg'
    assert line['exc_type'] is None
    assert line['extra'] is None


def test_exception_is_single_line_with_stack(capture):
    try:
        1 / 0
    except ZeroDivisionError:
        logger.exception('fallo calculo')
    raw = capture.stream.getvalue()
    assert raw.count('\n') == 1  # el traceback queda dentro de una sola línea JSON
    (line,) = capture.lines
    assert line['level'] == 'ERROR'
    assert line['exc_type'] == 'ZeroDivisionError'
    assert line['exc_message'] == 'division by zero'
    assert 'Traceback' in line['stack']


def test_extra_is_nested_and_cannot_override_top_level(capture):
    logger.info('x', extra={'data': {'uuid': 'abc'}, 'cliente_id': 7, 'module_name': 'zzz'})
    (line,) = capture.lines
    assert line['module'] == 'testmod'
    assert line['extra'] == {'data': {'uuid': 'abc'}, 'cliente_id': 7, 'module_name': 'zzz'}


def test_unserializable_extra_does_not_break(capture):
    class Weird:
        def __str__(self):
            raise RuntimeError('nope')

    circular = {}
    circular['self'] = circular
    logger.info('a', extra={'obj': object(), 'weird': Weird()})
    logger.info('b', extra={'circ': circular})
    a, b = capture.lines
    assert a['extra']['obj'].startswith('<object object')
    assert a['extra']['weird'] == '<unserializable Weird>'
    assert 'unserializable' in b['extra']


def test_bad_format_args_keep_the_line(capture):
    logger.info('dos %s %s', 'uno')
    (line,) = capture.lines
    assert line['msg'].startswith('dos %s %s')


def test_context_is_attached(capture):
    with log_context.bound(request_id='req-1', user='usuario1'):
        logger.info('dentro')
    logger.info('fuera')
    inside, outside = capture.lines
    assert inside['request_id'] == 'req-1'
    assert inside['user'] == 'usuario1'
    assert outside['request_id'] is None


def test_static_fields_from_env(monkeypatch):
    monkeypatch.setenv('LOG_MODULE', 'envmod')
    monkeypatch.setenv('LOG_COMPONENT', 'cron')
    monkeypatch.setenv('ENVIRONMENT', 'prod')
    monkeypatch.setenv('RELEASE', 'v9')
    record = logging.LogRecord('x', logging.INFO, __file__, 1, 'm', (), None)
    line = json.loads(JsonFormatter().format(record))
    assert (line['module'], line['component'], line['environment'], line['release']) == (
        'envmod', 'cron', 'prod', 'v9'
    )


def test_console_formatter_is_readable():
    record = logging.LogRecord('app', logging.WARNING, __file__, 7, 'cuidado', (), None)
    record.cliente_id = 7
    with log_context.bound(request_id='r1'):
        out = ConsoleFormatter(color=False).format(record)
    assert 'WARNING app:7 | cuidado' in out
    assert 'request_id=r1' in out
    assert '"cliente_id": 7' in out
