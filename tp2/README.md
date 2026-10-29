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
el event loop. Las implementaciones específicas de `descargar` y `hashear` se
incorporarán en la FASE 3.

Para ejecutar la API:

```bash
docker compose up --build
```