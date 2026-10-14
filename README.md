# servicio-logger

Logging estructurado compartido para servicios Python (Django + gunicorn + Celery).

Todo servicio que lo usa escribe en stdout **un objeto JSON por línea, con las mismas claves**.
Un recolector de logs (por ejemplo Promtail) envía stdout a Loki, y Grafana parsea cada línea con
`| json`. Así, un mismo set de dashboards y alertas sirve para todos los servicios, y nadie puede
romperlo cambiando el formato de log dentro de un servicio.

Sin dependencias (solo librería estándar). Las integraciones con Django y Celery se importan solo
cuando se usan.

---

## Esquema de log (`schema_version: 1`)

Todas las claves están **siempre presentes**; si una clave no tiene valor, es `null`.

| clave | ejemplo | notas |
|---|---|---|
| `schema_version` | `1` | Solo sube con cambios incompatibles en esta tabla. |
| `ts` | `2026-10-14T12:00:00.123-03:00` | Hora local (TZ del contenedor) con offset. |
| `level` | `INFO` / `WARNING` / `ERROR` / `CRITICAL` / `DEBUG` | |
| `logger` | `app.tasks` | Nombre del logger, normalmente la ruta del módulo Python. |
| `msg` | `Procesando cliente 42` | El mensaje formateado. |
| `module` | `mi-servicio` | Definido en settings (`get_logging_config(module=...)`) o en `LOG_MODULE`. |
| `component` | `web`, `worker`, `cron` | Variable de entorno `LOG_COMPONENT`. |
| `environment` | `prod`, `stg` | Variable de entorno `ENVIRONMENT`. |
| `release` | `v1.2.3` | Variable de entorno `RELEASE`. |
| `request_id` | `9f1c…` | El mismo id en un request web **y en las tareas de Celery que encoló**. |
| `user` | `usuario1` | Usuario autenticado. Se asigna al momento de la respuesta, así que aparece en la línea de acceso. |
| `task_id`, `task_name` | | Se asignan mientras corre una tarea de Celery. |
| `file`, `line`, `func`, `process` | `tasks.py`, `68`, `procesar`, `12` | Dónde está la llamada al log. |
| `exc_type`, `exc_message`, `stack` | `ValueError`, `…`, `Traceback …` | Se llenan con `logger.exception(...)` o `exc_info=True`. El traceback queda dentro de la misma línea. |
| `extra` | `{"data": {...}, "cliente_id": 42}` | Todo lo que se pasa con `extra={...}`. Siempre va anidado aquí, así que nunca puede sobrescribir las claves de arriba. |

Loggers especiales que emite el paquete:

* `servicio_logger.access`: una línea por request HTTP, con
  `extra.http = {method, path, status, duration_ms, ip, user}`. Siempre en nivel INFO; los fallos
  se filtran por `extra_http_status`.
* `servicio_logger.task`: una línea `Task finished` por tarea de Celery, con
  `extra.task = {name, state, duration_ms, queue, retries}`.
* `django.request`: solo 5xx (ERROR) con el traceback de la excepción no manejada. Los 4xx se ven
  en `servicio_logger.access`.
* `celery.app.trace`: las líneas propias de Celery cuando falla una tarea (ERROR, con traceback).
  Ahora llevan el contexto de la tarea.

## Variables de entorno

| variable | por defecto | |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Nivel raíz. |
| `LOG_FORMAT` | `json` | `console` entrega líneas legibles para desarrollo local. |
| `LOG_COMPONENT` | (null) | Se define en el entrypoint según el modo de ejecución. |
| `LOG_MODULE` | (null) | Solo se necesita para las líneas propias de gunicorn (los settings de Django aún no están cargados). |
| `ENVIRONMENT`, `RELEASE` | (null) | Ambiente y versión desplegada. |

---

## Cómo agregarlo a un servicio

1. **`requirements.txt`**
   ```
   git+https://github.com/<usuario-u-organizacion>/servicio-logger.git@v0.1.0#egg=servicio_logger
   ```

2. **`settings.py`**
   ```python
   from decouple import config
   from servicio_logger import get_component, get_logging_config

   MIDDLEWARE = [
       'django.middleware.security.SecurityMiddleware',
       'servicio_logger.django.RequestContextMiddleware',
       ...
   ]

   LOGGING = get_logging_config(
       module='<mi-servicio>',
       level=config('LOG_LEVEL', 'INFO'),
       fmt=config('LOG_FORMAT', 'json'),
       environment=config('ENVIRONMENT', ''),
       release=config('RELEASE', ''),
   )

   # Sentry (opcional)
   sentry_sdk.init(..., server_name=f'<mi-servicio>-{get_component()}')
   ```
   Opcional: `SERVICIO_LOGGER_SKIP_PATHS = ('/health',)` para no generar líneas de acceso en los
   health checks.

3. **`dev_settings.py`** (local): `LOGGING = get_logging_config(module='<mi-servicio>', fmt='console')`

4. **Módulo de la app de Celery** (solo si el servicio tiene workers)
   ```python
   from servicio_logger.celery import setup_celery_logging

   app.config_from_object('django.conf:settings', namespace='CELERY')
   setup_celery_logging(app)
   ```

5. **`entrypoint.sh`**
   ```sh
   export LOG_MODULE=<mi-servicio>
   # web
   export LOG_COMPONENT=${LOG_COMPONENT:-web}
   gunicorn proyecto.wsgi:application -c python:servicio_logger.gunicorn_conf --bind 0.0.0.0:8000 ...
   # celery
   export LOG_COMPONENT=${LOG_COMPONENT:-worker}
   ```

6. **`crontab`** (si aplica): enviar el output al log del contenedor (stdout del PID 1) en vez
   de un archivo:
   ```
   0 23 * * * LOG_COMPONENT=cron python /src/manage.py <comando> >> /proc/1/fd/1 2>&1
   ```

7. **Cómo loguear en el código**
   ```python
   logger = logging.getLogger(__name__)

   logger.info('Procesando cliente %s', cliente_id, extra={'cliente_id': cliente_id})
   try:
       ...
   except Exception:
       logger.exception('Error procesando cliente %s', cliente_id)   # nivel ERROR + traceback
   ```
   * Dentro de un `except`, usar `logger.exception(...)` y no `logger.error(f'... {e}')`. Lo
     segundo pierde el traceback.
   * Poner en `extra` los identificadores por los que se quiera filtrar. En Grafana quedan como
     `extra_<clave>`.
   * `print()` sigue funcionando para depurar en local. En producción un print es una línea de
     texto plano: se ve en Loki, pero `| json` no la parsea y las alertas no la cuentan. Dentro de
     los workers de Celery, los prints se redirigen al logger `celery.redirected` (WARNING).

8. **Test de resguardo** para que un `LOGGING` editado a mano haga fallar el CI:
   ```python
   from proyecto import settings as prod_settings

   def test_logging_usa_servicio_logger():
       assert prod_settings.LOGGING['formatters']['json']['()'] == 'servicio_logger.formatters.JsonFormatter'
       assert 'servicio_logger.django.RequestContextMiddleware' in prod_settings.MIDDLEWARE
   ```

Contexto adicional en scripts o management commands:
```python
from servicio_logger import log_context

with log_context.bound(task_name='mi_comando'):
    ...
```

---

## Guía rápida Grafana / LogQL

Los ejemplos suponen que el recolector agrega las labels `service` y `environment`. Las claves JSON
anidadas quedan aplanadas con `_` al usar `| json` (`extra.http.status` pasa a `extra_http_status`).

```logql
# Todo un servicio, legible
{service="mi-servicio"} | json | line_format "{{.level}} {{.component}} {{.logger}} | {{.msg}}"

# Solo errores (con el traceback en el campo `stack`)
{environment="prod", service=~"mi-servicio.*"} | json | level=~"ERROR|CRITICAL"

# Seguir un request a través de web y workers
{environment="prod"} | json | request_id="9f1c..."

# Respuestas 5xx
{environment="prod"} | json | logger="servicio_logger.access" | extra_http_status >= 500

# Endpoints lentos, latencia p95 por path
quantile_over_time(0.95,
  {environment="prod"} | json | logger="servicio_logger.access" | unwrap extra_http_duration_ms [5m]
) by (extra_http_path)

# Fallos de Celery
{environment="prod"} | json | logger="celery.app.trace" | level="ERROR"

# Tareas de Celery más lentas
{environment="prod"} | json | logger="servicio_logger.task" | extra_task_duration_ms > 60000
```

### Reglas de alerta sugeridas

| alerta | query | condición |
|---|---|---|
| Tasa de errores por servicio | `sum by (service) (count_over_time({environment="prod"} \| json \| level=~"ERROR\|CRITICAL" [5m]))` | `> 10` |
| Ráfaga de 5xx | `sum by (service) (count_over_time({environment="prod"} \| json \| logger="servicio_logger.access" \| extra_http_status >= 500 [5m]))` | `> 5` |
| Fallos de tareas Celery | `sum by (service) (count_over_time({environment="prod"} \| json \| logger="celery.app.trace" \| level="ERROR" [10m]))` | `> 0` |
| Timeouts de workers de gunicorn | `count_over_time({environment="prod"} \|= "WORKER TIMEOUT" [5m])` | `> 0` |

Tip: agrupar las alertas por `service` y poner `{{ $labels.service }}` en el título de la notificación.

---

## Desarrollo

```sh
pip install -e .[test]
pytest
```

Release: subir `version` en `pyproject.toml` y `__version__`, crear el tag `vX.Y.Z` y luego
actualizar el tag en el `requirements.txt` de cada servicio. Si la **tabla del esquema** cambia de
forma incompatible, subir también `SCHEMA_VERSION` en `formatters.py`.
