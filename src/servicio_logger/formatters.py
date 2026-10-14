"""Formatters que generan el esquema de log compartido.

``JsonFormatter`` es EL contrato con Grafana/Loki: cada línea es un único objeto
JSON con las mismas claves de primer nivel, en todos los servicios. No agregar,
renombrar ni eliminar claves de primer nivel sin subir ``SCHEMA_VERSION``.
"""
import json
import logging
import os
import sys
from datetime import datetime

from . import context

SCHEMA_VERSION = 1

# Atributos que tiene todo LogRecord. Cualquier otro atributo del record viene
# de ``extra=...`` y se ubica bajo la clave ``extra``.
_RESERVED_ATTRS = frozenset(vars(logging.LogRecord('', 0, '', 0, '', (), None))) | {
    'message',
    'asctime',
    'taskName',
}


def env_defaults():
    """Campos estáticos leídos desde variables de entorno."""
    return {
        'module': os.environ.get('LOG_MODULE') or None,
        'component': os.environ.get('LOG_COMPONENT') or None,
        'environment': os.environ.get('ENVIRONMENT') or None,
        'release': os.environ.get('RELEASE') or None,
    }


def _safe_message(record):
    try:
        return record.getMessage()
    except Exception:  # argumentos %-format inválidos nunca deben perder la línea
        return f'{record.msg} {record.args!r}'


def _record_extras(record):
    extras = {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RESERVED_ATTRS and not key.startswith('_')
    }
    return extras or None


def _json_default(obj):
    try:
        return str(obj)
    except Exception:
        return f'<unserializable {type(obj).__name__}>'


class _BaseFormatter(logging.Formatter):

    def __init__(self, module=None, component=None, environment=None, release=None, **kwargs):
        super().__init__(**kwargs)
        defaults = env_defaults()
        self.static = {
            'module': module or defaults['module'],
            'component': component or defaults['component'],
            'environment': environment or defaults['environment'],
            'release': release or defaults['release'],
        }

    def _exception_fields(self, record):
        exc_type = exc_message = stack = None
        if record.exc_info and record.exc_info[0] is not None:
            exc_type = record.exc_info[0].__name__
            exc_message = str(record.exc_info[1])
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            stack = record.exc_text
        if record.stack_info:
            stack_info = self.formatStack(record.stack_info)
            stack = f'{stack}\n{stack_info}' if stack else stack_info
        return exc_type, exc_message, stack


class JsonFormatter(_BaseFormatter):
    """Un objeto JSON por línea. Todas las claves de primer nivel siempre están presentes."""

    def format(self, record):
        exc_type, exc_message, stack = self._exception_fields(record)
        payload = {
            'schema_version': SCHEMA_VERSION,
            'ts': datetime.fromtimestamp(record.created).astimezone().isoformat(
                timespec='milliseconds'
            ),
            'level': record.levelname,
            'logger': record.name,
            'msg': _safe_message(record),
            **self.static,
            **context.get_context(),
            'file': record.filename,
            'line': record.lineno,
            'func': record.funcName,
            'process': record.process,
            'exc_type': exc_type,
            'exc_message': exc_message,
            'stack': stack,
            'extra': _record_extras(record),
        }
        try:
            return json.dumps(payload, default=_json_default, ensure_ascii=False)
        except Exception:
            # p.ej. referencias circulares dentro de ``extra``: se mantiene la línea y se degrada ``extra``.
            payload['extra'] = {'unserializable': repr(payload['extra'])}
            return json.dumps(payload, default=_json_default, ensure_ascii=False)


_COLORS = {
    'DEBUG': '\033[36m',
    'INFO': '\033[32m',
    'WARNING': '\033[33m',
    'ERROR': '\033[31m',
    'CRITICAL': '\033[1;31m',
}
_RESET = '\033[0m'


class ConsoleFormatter(_BaseFormatter):
    """Formato de una línea legible para desarrollo local (LOG_FORMAT=console)."""

    def __init__(self, color=None, **kwargs):
        super().__init__(**kwargs)
        self.color = sys.stdout.isatty() if color is None else color

    def format(self, record):
        ts = datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3]
        level = record.levelname
        if self.color:
            level = f'{_COLORS.get(level, "")}{level:>8}{_RESET}'
        else:
            level = f'{level:>8}'
        line = f'{ts} {level} {record.name}:{record.lineno} | {_safe_message(record)}'

        ctx = {k: v for k, v in context.get_context().items() if v is not None}
        extras = _record_extras(record)
        if ctx:
            line += '  [' + ' '.join(f'{k}={v}' for k, v in ctx.items()) + ']'
        if extras:
            line += '  ' + json.dumps(extras, default=_json_default, ensure_ascii=False)

        _, _, stack = self._exception_fields(record)
        if stack:
            line += '\n' + stack
        return line
