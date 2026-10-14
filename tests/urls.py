import logging
import time

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


def slow(request):
    time.sleep(0.3)
    return HttpResponse('lento')


def very_slow(request):
    time.sleep(0.7)
    return HttpResponse('muy lento')


urlpatterns = [
    path('ok', ok),
    path('missing', not_found),
    path('boom', boom),
    path('health', ok),
    path('slow', slow),
    path('very-slow', very_slow),
]
