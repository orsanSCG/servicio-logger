import io
import json
import logging
import logging.config
import sys

from servicio_logger import get_gunicorn_logconfig, get_logging_config
from servicio_logger.config import JSON_FORMATTER


def test_defaults(monkeypatch):
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    monkeypatch.delenv('LOG_FORMAT', raising=False)
    config = get_logging_config(module='mi-servicio')
    assert config['disable_existing_loggers'] is False
    assert config['formatters']['json']['()'] == JSON_FORMATTER
    assert config['formatters']['json']['module'] == 'mi-servicio'
    assert config['handlers']['stdout']['formatter'] == 'json'
    assert config['root'] == {'level': 'INFO', 'handlers': ['stdout']}


def test_env_overrides(monkeypatch):
    monkeypatch.setenv('LOG_LEVEL', 'debug')
    monkeypatch.setenv('LOG_FORMAT', 'console')
    config = get_logging_config(module='mi-servicio')
    assert config['root']['level'] == 'DEBUG'
    assert config['handlers']['stdout']['formatter'] == 'console'


def test_invalid_format_falls_back_to_json():
    assert get_logging_config(fmt='xml')['handlers']['stdout']['formatter'] == 'json'


def test_explicit_environment_and_release():
    config = get_logging_config(module='m', environment='prod', release='v1')
    assert config['formatters']['json']['environment'] == 'prod'
    assert config['formatters']['json']['release'] == 'v1'


def test_dictconfig_applies_and_writes_json(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', stream)
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        logging.config.dictConfig(get_logging_config(module='mi-servicio', component='worker'))
        logging.getLogger('app.tasks').warning('hola')
        logging.getLogger('django.db.backends').info('SELECT 1')  # silenciado
        lines = [json.loads(x) for x in stream.getvalue().splitlines()]
        assert len(lines) == 1
        assert lines[0]['module'] == 'mi-servicio'
        assert lines[0]['component'] == 'worker'
    finally:
        root.handlers[:], _ = saved
        root.setLevel(saved[1])


def test_gunicorn_config_silences_access():
    config = get_gunicorn_logconfig()
    assert config['loggers']['gunicorn.access']['handlers'] == []
    assert config['loggers']['gunicorn.error']['handlers'] == ['stdout']
    from servicio_logger import gunicorn_conf
    assert gunicorn_conf.accesslog is None
    assert 'gunicorn.error' in gunicorn_conf.logconfig_dict['loggers']
