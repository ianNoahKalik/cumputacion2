import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, status

from src.schemas import (
    EstadoTarea,
    EstadisticasResponse,
    TareaCreate,
    TareaResponse,
    TipoTarea,
)
from src.tasks.executor import execute_task, shutdown_executor
from src.workers.pool import WorkerPool


_tareas: dict[UUID, TareaResponse] = {}
_worker_count = int(os.getenv("WORKER_COUNT", "2"))
_queue_manager = WorkerPool(_tareas, execute_task, _worker_count)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await _queue_manager.start()
    try:
        yield
    finally:
        await _queue_manager.stop()
        await shutdown_executor()


app = FastAPI(
    title="Plataforma de Tareas Distribuidas",
    version="0.1.0",
    description="API base del TP2 de Computacion II.",
    lifespan=lifespan,
)


@app.post(
    "/tareas",
    response_model=TareaResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def crear_tarea(tarea: TareaCreate) -> TareaResponse:
    tarea_creada = TareaResponse(
        id=uuid4(),
        tipo=tarea.tipo,
        estado="pendiente",
        parametros=tarea.parametros,
        timeout=tarea.timeout,
        creada_en=_ahora(),
    )
    _tareas[tarea_creada.id] = tarea_creada
    await _queue_manager.enqueue(tarea_creada.id)
    return tarea_creada


@app.get("/tareas", response_model=list[TareaResponse])
async def listar_tareas(
    estado: EstadoTarea | None = Query(default=None),
) -> list[TareaResponse]:
    tareas = _tareas.values()
    if estado is not None:
        tareas = (tarea for tarea in tareas if tarea.estado == estado)
    return list(tareas)


@app.get("/tareas/{tarea_id}", response_model=TareaResponse)
async def obtener_tarea(tarea_id: UUID) -> TareaResponse:
    tarea = _tareas.get(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return tarea


@app.delete("/tareas/{tarea_id}", response_model=TareaResponse)
async def cancelar_tarea(tarea_id: UUID) -> TareaResponse:
    tarea = _tareas.get(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    if tarea.estado not in {"pendiente", "ejecutando"}:
        raise HTTPException(
            status_code=409,
            detail="La tarea ya finalizo y no puede cancelarse",
        )
    await _queue_manager.cancel(tarea_id)
    return tarea


@app.get("/estadisticas", response_model=EstadisticasResponse)
async def obtener_estadisticas() -> EstadisticasResponse:
    estados: tuple[EstadoTarea, ...] = (
        "pendiente",
        "ejecutando",
        "completada",
        "fallida",
        "cancelada",
    )
    totales = {
        estado: sum(tarea.estado == estado for tarea in _tareas.values())
        for estado in estados
    }
    duraciones = [
        (tarea.finalizada_en - tarea.creada_en).total_seconds()
        for tarea in _tareas.values()
        if tarea.finalizada_en is not None
    ]
    promedio = sum(duraciones) / len(duraciones) if duraciones else 0.0
    workers_ocupados = totales["ejecutando"]
    return EstadisticasResponse(
        totales_por_estado=totales,
        tiempo_promedio_segundos=promedio,
        workers_ocupados=workers_ocupados,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)