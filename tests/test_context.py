import pytest

from servicio_logger import log_context


def test_bind_and_reset():
    tokens = log_context.bind(request_id='a')
    assert log_context.get('request_id') == 'a'
    log_context.reset(tokens)
    assert log_context.get('request_id') is None


def test_nested_bound_restores_outer():
    with log_context.bound(request_id='outer'):
        with log_context.bound(request_id='inner', task_id='t'):
            assert log_context.get_context()['request_id'] == 'inner'
        assert log_context.get('request_id') == 'outer'
        assert log_context.get('task_id') is None


def test_unknown_field():
    with pytest.raises(KeyError):
        log_context.bind(foo='x')
