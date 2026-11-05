# TP2 - Plataforma de Tareas Distribuidas

Servidor asíncrono desarrollado con Python 3.11+, FastAPI y `asyncio`. La API
recibe tareas por HTTP, las coloca en una `asyncio.Queue` y las ejecuta con un
pool configurable de workers consumidores.

## 1. Descripción y uso

La plataforma soporta tres tipos de tarea:

| Tipo | Parámetros | Resultado |
| --- | --- | --- |
| `esperar` | `segundos` | Confirma el tiempo esperado |
| `descargar` | `urls` (lista), opcionalmente `timeout` | Código HTTP, tamaño y duración por URL |
| `hashear` | `texto`, `iteraciones` | Hash SHA-256 iterativo |

Los estados posibles son `pendiente`, `ejecutando`, `completada`, `fallida` y
`cancelada`. `POST /tareas` responde `202 Accepted` inmediatamente; la
ejecución ocurre en segundo plano.

### Ejecutar con Docker

Desde el directorio `tp2/`:

```bash
docker compose up --build
```

La API queda disponible en `http://localhost:8000`. La cantidad de workers se
configura con `WORKER_COUNT` (por defecto, `2`). El límite de apagado ordenado
se configura con `SHUTDOWN_TIMEOUT` y los volcados se guardan en `STATE_DIR`.

### Ejemplos con curl

Crear una tarea asíncrona:

```bash
curl -X POST http://localhost:8000/tareas ^
  -H "Content-Type: application/json" ^
  -d "{\"tipo\":\"esperar\",\"parametros\":{\"segundos\":3}}"
```

Consultar una tarea:

```bash
curl http://localhost:8000/tareas/<ID>
```

Listar o filtrar por estado:

```bash
curl http://localhost:8000/tareas
curl "http://localhost:8000/tareas?estado=ejecutando"
```

Descargar varias URLs concurrentemente:

```bash
curl -X POST http://localhost:8000/tareas ^
  -H "Content-Type: application/json" ^
  -d "{\"tipo\":\"descargar\",\"parametros\":{\"urls\":[\"https://example.com\",\"https://httpbin.org/bytes/32\"]}}"
```

Solicitar un hash intensivo con timeout:

```bash
curl -X POST http://localhost:8000/tareas ^
  -H "Content-Type: application/json" ^
  -d "{\"tipo\":\"hashear\",\"parametros\":{\"texto\":\"hola\",\"iteraciones\":1000000},\"timeout\":30}"
```

Cancelar una tarea pendiente o ejecutándose:

```bash
curl -X DELETE http://localhost:8000/tareas/<ID>
```

Consultar estadísticas:

```bash
curl http://localhost:8000/estadisticas
```

### Pruebas y benchmarks

Ejecutar la suite:

```bash
python -m pytest -q
```

Ejecutar las mediciones de la FASE 6 desde `tp2/`:

```bash
python -m benchmarks.benchmark
```

Parámetros opcionales:

```bash
python -m benchmarks.benchmark --delay 0.05 --iterations 2000000 --batches 1 2 4 8 16 32
```

## 2. Arquitectura y flujo

```text
Cliente HTTP
     |
     v
+------------------+       +-------------------+
| FastAPI          | ----> | asyncio.Queue     |
| POST /tareas     |       | IDs de tareas     |
| GET/DELETE       |       +---------+---------+
| /estadisticas    |                 |
+------------------+                 v
                         +-------------------+
                         | WorkerPool       |
                         | N corrutinas     |
                         +----+---------+----+
                              |         |
                         I/O  |         | CPU
                              v         v
                         httpx       ProcessPoolExecutor
                         asyncio     run_in_executor
                              \         /
                               v       v
                         estado/resultado en memoria
                                      |
                                      v
                              volcado JSON al apagar
```

El endpoint crea una `TareaResponse`, la registra en memoria y encola su ID.
Un worker toma el ID, cambia el estado a `ejecutando`, ejecuta la operación y
guarda resultado, error y timestamps. Al terminar pasa a `completada` o
`fallida`; una cancelación explícita pasa a `cancelada`.

La aplicación usa el `lifespan` de FastAPI. Al iniciar busca volcados previos y
los reporta mediante logging. Ante `SIGINT` o `SIGTERM`, Uvicorn inicia el
apagado: se dejan de aceptar tareas, se espera hasta `SHUTDOWN_TIMEOUT`, se
cancelan las tareas que no terminaron y se escribe
`estado_<timestamp>.json`.

## 3. Decisiones de diseño

### ¿Por qué `asyncio.Queue` y no `queue.Queue`?

`asyncio.Queue` está integrada con el event loop: `put()` y `get()` permiten
que la corrutina ceda el control sin bloquear el hilo. `queue.Queue` es una
primitiva para hilos y puede bloquear físicamente el único hilo que atiende la
API. El sistema es un productor-consumidor asíncrono, por eso la cola debe
pertenecer al mismo modelo de concurrencia que los workers.

### ¿Cómo evitamos congelar la API con CPU-bound?

`hashear` no calcula el hash dentro del event loop. La función
`_iterated_sha256` se envía a un `ProcessPoolExecutor` con
`loop.run_in_executor`. Los procesos evitan que el cálculo intensivo monopolice
el hilo que atiende HTTP. La protección `if __name__ == "__main__"` también
evita problemas de reimportación con `spawn` en Windows y macOS.

Las tareas I/O-bound usan corrutinas: `esperar` utiliza `asyncio.sleep()` y
`descargar` utiliza `httpx.AsyncClient` junto con `asyncio.gather()`.

### ¿Cómo funciona la cancelación?

Para una tarea pendiente se marca `cancelada` y el worker la descarta cuando
la encuentra en la cola. Para una tarea ejecutándose se cancela su
`asyncio.Task`; `httpx` y `asyncio.sleep` reciben la cancelación y liberan sus
recursos mediante sus context managers. El worker limpia el registro de tareas
en ejecución y siempre ejecuta `queue.task_done()`.

Una cancelación no mata procesos externos ni deja una tarea marcada como
completada: el estado final es `cancelada`. Los timeouts siguen el mismo
mecanismo de cancelación y marcan la tarea como `fallida` con el motivo.

### ¿Qué ocurre si un worker lanza una excepción?

Las excepciones normales producidas por el ejecutor se capturan en el worker,
se convierten en estado `fallida` y se guarda el texto en `error`. El worker
continúa consumiendo tareas posteriores y la cola recibe `task_done()`. La
cancelación (`CancelledError`) se trata separadamente para conservar el estado
`cancelada` y no ocultar la señal de apagado.

## 4. Mediciones e interpretación

Las mediciones se obtuvieron ejecutando:

```bash
python -m benchmarks.benchmark --delay 0.02 --iterations 500000 --batches 1 2 4 8 16 32
```

### Medición 1: concurrencia I/O

El benchmark hizo 20 descargas contra un servidor HTTP local controlado:

```text
Secuencial:  0.8936 s
Concurrente: 0.1130 s
Speedup:     7.91x
```

La versión concurrente tarda aproximadamente lo que la respuesta más lenta,
en vez de sumar las 20 esperas. El speedup no llega a 20x por costos de
conexión, scheduling y límites del cliente.

### Medición 2: bloqueo del event loop

Se midió el tiempo hasta responder `GET /tareas` mientras corrían 500.000
iteraciones SHA-256:

```text
Hash directo en event loop:  0.3116 s
ProcessPoolExecutor:         0.0012 s
Mejora de latencia:        266.55x
```

El resultado evidencia que `asyncio` no vuelve CPU-bound a un trabajo
automáticamente concurrente. El executor libera el event loop y permite que
la API atienda otra solicitud mientras el proceso auxiliar calcula.

### Medición 3: techo del pool

Con `WORKER_COUNT=2` y tareas `esperar` de 0.02 segundos:

| Lote | Tiempo total | Promedio por tarea |
| ---: | ---: | ---: |
| 1 | 0.0377 s | 0.0377 s |
| 2 | 0.0481 s | 0.0241 s |
| 4 | 0.0803 s | 0.0201 s |
| 8 | 0.1306 s | 0.0163 s |
| 16 | 0.2885 s | 0.0180 s |
| 32 | 0.5633 s | 0.0176 s |

La capacidad útil se alcanza aproximadamente entre 8 y 16 tareas simultáneas.
Después aumenta el tiempo total por la espera en la cola; no se crean workers
ilimitados para cada solicitud.

## 5. Conceptos teóricos aplicados

- **Productor-consumidor:** FastAPI es el productor y el `WorkerPool` consume
  IDs desde `asyncio.Queue`.
- **Event loop y multiplexación:** una corrutina bloqueada en I/O cede el hilo,
  permitiendo atender otras solicitudes.
- **Corrutinas frente a hilos:** las tareas I/O-bound se resuelven con
  corrutinas cooperativas; el cálculo CPU-bound se separa en procesos.
- **Ausencia de locks para el estado normal:** las operaciones sobre el
  diccionario y las transiciones de estado se ejecutan en secciones síncronas
  del event loop; no hay dos corrutinas ejecutando Python al mismo tiempo
  dentro de esa sección.
- **Backpressure:** la cola desacopla la llegada HTTP de la capacidad finita
  del pool. La espera se concentra en la cola en vez de bloquear el endpoint.
- **Finalización ordenada:** el `lifespan`, `queue.join()` y el volcado JSON
  permiten cerrar recursos y conservar observaciones del sistema.

## 6. Cuestionario de defensa

### ¿Dónde podría bloquearse el event loop?

En cualquier operación síncrona prolongada dentro de una corrutina: hash
directo, `time.sleep()`, lectura/escritura de archivos grandes o una biblioteca
HTTP síncrona. Por eso el hash usa `run_in_executor`, las esperas usan
`asyncio.sleep` y las descargas usan `httpx` asíncrono. El volcado JSON ocurre
durante el apagado, fuera del camino normal de atención de solicitudes.

### ¿Qué pasa si se cancela una tarea a mitad de una descarga?

La cancelación se propaga a la corrutina de `httpx`. El context manager de
`AsyncClient` cierra las conexiones, el worker elimina la tarea del registro
de ejecución y el estado queda `cancelada`. Las demás URLs de esa misma tarea
también dejan de esperarse porque `asyncio.gather` se cancela como conjunto.

### ¿Por qué el pool no necesita un `Lock`?

Los workers son corrutinas del mismo event loop. Las transiciones de estado no
contienen `await`, por lo que son atómicas respecto de otras corrutinas:
ninguna puede interrumpirlas a mitad. La cola ya proporciona la coordinación
entre productores y consumidores. Un `Lock` sería necesario si varios hilos
modificaran directamente el mismo estado.

### Si entran 10.000 tareas de golpe, ¿qué se rompe primero?

La cola y el diccionario pueden crecer en memoria porque no tienen límite
configurado; antes que los workers, se degradarían la memoria disponible y el
tiempo de espera de las tareas. En producción habría que agregar una cola
acotada, límites por cliente, rechazo `429`, persistencia externa o varios
procesos. La implementación actual es deliberadamente educativa y mantiene el
estado en memoria.

### ¿Diferencia entre `asyncio.gather` y un `for` con `await`?

`for` con `await` espera una operación antes de iniciar la siguiente, por lo
que es secuencial. `asyncio.gather` programa varias awaitables y espera el
conjunto, permitiendo que las descargas avancen concurrentemente durante sus
esperas de red.

### ¿Por qué `time.sleep()` es un bug y `asyncio.sleep()` no?

`time.sleep()` bloquea el hilo completo y detiene el event loop durante todo el
intervalo: no se atienden HTTP ni otras corrutinas. `asyncio.sleep()` suspende
solo la corrutina actual y devuelve el control al event loop, que puede
ejecutar otros trabajos.

## 7. Auditoría de restricciones

- Cola básica implementada exclusivamente con `asyncio.Queue`.
- No se usan Celery, RQ, Redis ni otro framework externo de colas.
- No se usa base de datos; el estado vive en memoria y se vuelca a JSON.
- `descargar` usa `httpx.AsyncClient`, no `requests`.
- La aplicación productiva no usa `time.sleep()` dentro de corrutinas.
- `hashear` usa `ProcessPoolExecutor` y `run_in_executor`.
- El entrypoint tiene protección `if __name__ == "__main__"`.
- La API se empaqueta con `Dockerfile` y `docker-compose.yml`.

## 8. Limitaciones y aprendizajes

### Limitaciones conocidas

- El estado no sobrevive completamente a una caída abrupta antes del shutdown
  ordenado.
- Los volcados JSON son archivos de inspección y no una base de datos
  transaccional; no se reencolan automáticamente las tareas pendientes.
- La cola no tiene límite ni backpressure HTTP, por lo que una carga masiva
  puede consumir memoria.
- `descargar` informa errores por URL, pero no implementa reintentos ni
  autenticación.
- El pool de procesos tiene costo de arranque y consume recursos del host.
- Las métricas son de un único proceso; no representan un despliegue
  distribuido con varios servidores.

### Aprendizajes

El proyecto permitió comprobar con mediciones que la concurrencia I/O reduce
el tiempo total, mientras que `asyncio` por sí solo no resuelve el trabajo
CPU-bound. También mostró la importancia de separar la recepción HTTP, la
planificación y la ejecución, y de definir explícitamente cancelación,
timeouts, estados y apagado. Finalmente, el benchmark del pool evidencia que
agregar concurrencia sin límite no equivale a aumentar capacidad: después del
techo, el costo se transforma en espera y presión sobre los recursos.
