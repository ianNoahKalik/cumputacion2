import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from src.core.queue import TaskQueueManager
from src.schemas import TareaResponse
from src.tasks.executor import execute_task, shutdown_executor


def _task(tipo: str, parametros: dict, timeout: float | None = None):
    return TareaResponse(
        id=uuid4(),
        tipo=tipo,
        estado="pendiente",
        parametros=parametros,
        timeout=timeout,
        creada_en=datetime.now(timezone.utc),
    )


def test_hash_uses_executor_and_returns_digest():
    asyncio.run(_test_hash_uses_executor_and_returns_digest())


async def _test_hash_uses_executor_and_returns_digest():
    task = _task("hashear", {"texto": "hola", "iteraciones": 1000})

    result = await execute_task(task)

    assert result["iteraciones"] == 1000
    assert len(result["hash"]) == 64
    await shutdown_executor()


def test_timeout_marks_task_as_failed():
    asyncio.run(_test_timeout_marks_task_as_failed())


async def _test_timeout_marks_task_as_failed():
    task = _task("esperar", {"segundos": 0.1}, timeout=0.01)
    tasks = {task.id: task}
    manager = TaskQueueManager(tasks, execute_task, worker_count=1)

    await manager.enqueue(task.id)
    await asyncio.wait_for(_wait_for_terminal(task), timeout=1)
    await manager.stop()

    assert task.estado == "fallida"
    assert "0.01" in task.error


async def _wait_for_terminal(task: TareaResponse) -> None:
    while task.estado not in {"completada", "fallida", "cancelada"}:
        await asyncio.sleep(0)
