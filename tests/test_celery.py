import pytest

celery = pytest.importorskip('celery')

from servicio_logger import celery as logger_celery  # noqa: E402
from servicio_logger import log_context  # noqa: E402
from servicio_logger.config import TASK_LOGGER  # noqa: E402


@pytest.fixture(scope='module')
def app():
    app = celery.Celery('tests')
    app.conf.task_always_eager = True
    logger_celery.setup_celery_logging(app)

    @app.task(name='tests.tasks.sumar')
    def sumar(a, b):
        import logging
        logging.getLogger('tests.tasks').info('sumando')
        return a + b

    app.sumar = sumar
    return app


def test_task_context_and_finished_line(app, capture):
    assert app.sumar.delay(1, 2).get() == 3
    task_line = [x for x in capture.lines if x['logger'] == 'tests.tasks'][0]
    finished = [x for x in capture.lines if x['logger'] == TASK_LOGGER][0]
    assert task_line['task_name'] == 'tests.tasks.sumar'
    assert task_line['task_id'] == finished['task_id']
    assert finished['extra']['task']['state'] == 'SUCCESS'
    assert finished['extra']['task']['duration_ms'] >= 0
    assert log_context.get('task_id') is None


def test_eager_task_keeps_request_id(app, capture):
    with log_context.bound(request_id='req-9'):
        app.sumar.delay(2, 2).get()
        assert log_context.get('request_id') == 'req-9'
    task_line = [x for x in capture.lines if x['logger'] == 'tests.tasks'][0]
    assert task_line['request_id'] == 'req-9'


def test_publish_adds_request_id_header():
    headers = {}
    with log_context.bound(request_id='req-1'):
        logger_celery.on_before_task_publish(headers=headers)
    assert headers == {logger_celery.REQUEST_ID_HEADER: 'req-1'}


def test_worker_restores_request_id_from_header():
    class Req:
        pass

    setattr(Req, logger_celery.REQUEST_ID_HEADER, 'req-from-web')

    class Task:
        name = 't'
        request = Req()

    logger_celery.on_task_prerun(task_id='id1', task=Task())
    assert log_context.get('request_id') == 'req-from-web'
    logger_celery.on_task_postrun(task_id='id1', task=Task(), state='SUCCESS')
    assert log_context.get('request_id') is None
