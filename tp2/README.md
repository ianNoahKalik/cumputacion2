## FASE 2: cola y pool de workers

La API encola cada tarea recibida por `POST /tareas` en una `asyncio.Queue` y
responde con `202 Accepted` sin esperar su ejecución. Un pool configurable de
corrutinas consumidoras toma los identificadores de la cola y actualiza el
estado en memoria:

`pendiente -> ejecutando -> completada | fallida | cancelada`

La cantidad de workers se configura con la variable de entorno
`WORKER_COUNT` (por defecto, `2`). `DELETE /tareas/{id}` cancela tanto tareas
pendientes como tareas que ya están siendo ejecutadas. El tipo `esperar` usa
`asyncio.sleep`, por lo que permite observar el estado `ejecutando` sin bloquear
el event loop. `descargar` recibe `urls`, usa un `httpx.AsyncClient` compartido y realiza las
descargas con `asyncio.gather`. Cada resultado informa `codigo`, `tamano` y
`tiempo_segundos`; los errores HTTP de una URL se informan en esa entrada sin
perder las demás descargas.

`hashear` recibe `texto` e `iteraciones`. El cálculo iterativo SHA-256 se
ejecuta en un `ProcessPoolExecutor` mediante `run_in_executor`, evitando
bloquear el event loop con trabajo CPU-bound.

Si una tarea supera su `timeout`, queda `fallida` con el motivo y el valor del
timeout agotado.

## FASE 4: apagado ordenado y persistencia

Uvicorn captura `SIGINT` y `SIGTERM` y ejecuta el `lifespan` de FastAPI. Durante
el apagado se dejan de aceptar tareas nuevas, se espera hasta
`SHUTDOWN_TIMEOUT` segundos por la cola y las tareas en ejecución, y luego se
cancelan las que no terminaron. El estado completo se guarda como
`estado_<timestamp>.json` en `STATE_DIR`. Al iniciar, la aplicación busca esos
archivos y registra en el log cuántos volcados previos encontró.

Las variables `SHUTDOWN_TIMEOUT` y `STATE_DIR` son configurables. Docker monta
`/app/state` en un volumen persistente para conservar los volcados entre
reinicios.

Para ejecutar la API:

```bash
docker compose up --build
```