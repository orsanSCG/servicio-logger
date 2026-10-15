import pytest

pytest.importorskip('rest_framework')

from rest_framework import exceptions, serializers  # noqa: E402
from rest_framework.decorators import api_view, authentication_classes, permission_classes  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402
from rest_framework.views import APIView, exception_handler as drf_default  # noqa: E402

from servicio_logger.config import DRF_LOGGER  # noqa: E402
from servicio_logger.drf import log_exception_handler  # noqa: E402

factory = APIRequestFactory()


class ClienteSerializer(serializers.Serializer):
    nombre = serializers.CharField()
    monto = serializers.IntegerField()

    def validate_monto(self, value):
        if value < 0:
            raise serializers.ValidationError('El monto no puede ser negativo.')
        return value


class BaseView(APIView):
    authentication_classes = []
    permission_classes = []

    def get_exception_handler(self):
        return log_exception_handler


class ClienteView(BaseView):

    def post(self, request):
        serializer = ClienteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data, status=201)

    def get(self, request):
        raise exceptions.NotFound('Cliente no encontrado.')

    def put(self, request):
        raise exceptions.Throttled(wait=10)

    def delete(self, request):
        raise RuntimeError('error inesperado')


def _drf_lines(capture):
    return [line for line in capture.lines if line['logger'] == DRF_LOGGER]


def test_validation_error_logs_warning_with_response_and_origin(capture):
    response = ClienteView.as_view()(factory.post('/clientes', {'nombre': 'x', 'monto': -5}, format='json'))
    assert response.status_code == 400
    (line,) = _drf_lines(capture)
    assert line['level'] == 'WARNING'
    assert line['msg'] == 'ClienteView.POST respondió 400: monto: El monto no puede ser negativo.'
    assert line['extra']['view'] == 'ClienteView'
    assert line['extra']['status'] == 400
    assert line['extra']['exc_type'] == 'ValidationError'
    assert line['extra']['response'] == {'monto': ['El monto no puede ser negativo.']}
    # DRF junta los errores de campo y los relanza desde is_valid(): origin apunta a la vista que validó
    assert 'test_drf.py' in line['extra']['origin'] and line['extra']['origin'].endswith('en post')
    assert line['stack'] is None  # errores de validación: solo origin, sin traceback


def test_response_is_identical_to_drf_default():
    exc = exceptions.ValidationError({'campo': ['requerido']})
    context = {'view': None, 'request': None}
    assert log_exception_handler(exc, context).data == drf_default(exc, context).data


def test_not_found_is_info(capture):
    response = ClienteView.as_view()(factory.get('/clientes'))
    assert response.status_code == 404
    (line,) = _drf_lines(capture)
    assert line['level'] == 'INFO'
    assert line['msg'] == 'ClienteView.GET respondió 404: Cliente no encontrado.'


def test_other_4xx_include_traceback(capture):
    response = ClienteView.as_view()(factory.put('/clientes'))
    assert response.status_code == 429
    (line,) = _drf_lines(capture)
    assert line['level'] == 'WARNING'
    assert 'Traceback' in line['stack']


def test_unhandled_exception_is_not_logged_here(capture):
    with pytest.raises(RuntimeError):
        ClienteView.as_view()(factory.delete('/clientes'))
    assert _drf_lines(capture) == []


def test_function_view_name(capture):
    @api_view(['POST'])
    @authentication_classes([])
    @permission_classes([])
    def crear_linea(request):
        raise exceptions.ValidationError({'organizacion': ['Este campo es requerido.']})

    crear_linea.cls.get_exception_handler = lambda self: log_exception_handler
    response = crear_linea(factory.post('/lineas', {}, format='json'))
    assert response.status_code == 400
    (line,) = _drf_lines(capture)
    assert line['msg'] == 'crear_linea.POST respondió 400: organizacion: Este campo es requerido.'


def test_large_response_is_truncated(capture):
    exc = exceptions.ValidationError({'filas': [f'Fila {i}: error largo de validación' for i in range(500)]})
    log_exception_handler(exc, {'view': None, 'request': None})
    (line,) = _drf_lines(capture)
    assert isinstance(line['extra']['response'], str) and len(line['extra']['response']) <= 2001
