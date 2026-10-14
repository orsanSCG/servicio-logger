import logging

from django.http import HttpResponse
from django.urls import path

logger = logging.getLogger('tests.views')


def ok(request):
    logger.info('en la vista')
    return HttpResponse('ok')


def not_found(request):
    return HttpResponse('nope', status=404)


def boom(request):
    raise ValueError('explota')


urlpatterns = [
    path('ok', ok),
    path('missing', not_found),
    path('boom', boom),
    path('health', ok),
]
