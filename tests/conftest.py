import io
import json
import logging

import pytest

from servicio_logger import log_context
from servicio_logger.formatters import JsonFormatter


def pytest_configure():
    try:
        from django.conf import settings
    except ImportError:
        return
    if not settings.configured:
        settings.configure(
            DEBUG=False,
            SECRET_KEY='test',
            ALLOWED_HOSTS=['*'],
            ROOT_URLCONF='tests.urls',
            INSTALLED_APPS=['django.contrib.contenttypes', 'django.contrib.auth'],
            MIDDLEWARE=['servicio_logger.django.RequestContextMiddleware'],
            SERVICIO_LOGGER_SKIP_PATHS=('/health',),
            DATABASES={},
        )
        import django
        django.setup()


@pytest.fixture(autouse=True)
def clean_context():
    log_context.clear()
    yield
    log_context.clear()


class Capture:

    def __init__(self, stream):
        self.stream = stream

    @property
    def lines(self):
        return [json.loads(line) for line in self.stream.getvalue().splitlines() if line.strip()]


@pytest.fixture
def capture():
    """Agrega un handler con JsonFormatter al logger raíz y retorna las líneas parseadas."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(module='testmod', component='web', environment='stg'))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield Capture(stream)
    root.removeHandler(handler)
    root.setLevel(old_level)
