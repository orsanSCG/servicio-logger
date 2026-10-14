"""Contexto por request / por tarea que se agrega a cada línea de log.

Los valores viven en ``contextvars``, así quedan aislados por thread (workers
sync de gunicorn, prefork de celery) y por tarea de asyncio.
"""
import contextvars
from contextlib import contextmanager

CONTEXT_FIELDS = ('request_id', 'user', 'task_id', 'task_name')

_vars = {
    name: contextvars.ContextVar(f'servicio_logger_{name}', default=None)
    for name in CONTEXT_FIELDS
}


def bind(**values):
    """Asigna valores al contexto. Retorna tokens para restaurar el estado anterior con ``reset``."""
    tokens = {}
    for name, value in values.items():
        if name not in _vars:
            raise KeyError(f'Campo de contexto desconocido: {name!r}. Válidos: {CONTEXT_FIELDS}')
        tokens[name] = _vars[name].set(value)
    return tokens


def reset(tokens):
    """Restaura los valores que existían antes del ``bind`` correspondiente."""
    for name, token in tokens.items():
        try:
            _vars[name].reset(token)
        except ValueError:
            # Token creado en otro contexto (no debería pasar); se limpia el campo.
            _vars[name].set(None)


def clear(*names):
    """Limpia los campos indicados (todos si se llama sin argumentos)."""
    for name in names or CONTEXT_FIELDS:
        _vars[name].set(None)


def get(name):
    return _vars[name].get()


def get_context():
    return {name: var.get() for name, var in _vars.items()}


@contextmanager
def bound(**values):
    """Versión context manager de ``bind``/``reset``.

    Útil en management commands o scripts::

        with log_context.bound(task_name='mi_comando'):
            ...
    """
    tokens = bind(**values)
    try:
        yield
    finally:
        reset(tokens)
