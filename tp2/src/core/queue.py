import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from src.schemas import TareaResponse


TaskExecutor = Callable[[TareaResponse], Awaitable[object]]


class TaskQueueManager:
    """Administra la cola y coordina la cancelación de tareas."""

    def __init__(
        self,
        tasks: dict[UUID, TareaResponse],
        executor: TaskExecutor,
        worker_count: int = 2,
    ) -> None:
        if worker_count < 1:
            raise ValueError("worker_count debe ser mayor que cero")
        self._tasks = tasks
        self._executor = executor
        self._queue: asyncio.Queue[UUID] = asyncio.Queue()
        self._worker_count = worker_count
        self._workers: list[asyncio.Task[None]] = []
        self._running_tasks: dict[UUID, asyncio.Task[object]] = {}
        self._started = False
        self._accepting = True

    @property
    def worker_count(self) -> int:
        return self._worker_count

    @property
    def workers_busy(self) -> int:
        return len(self._running_tasks)

    async def start(self) -> None:
        if self._started:
            return
        self._accepting = True
        self._workers = [
            asyncio.create_task(self._worker(index))
            for index in range(self._worker_count)
        ]
        self._started = True

    async def enqueue(self, task_id: UUID) -> None:
        if not self._accepting:
            raise RuntimeError("El administrador no acepta tareas nuevas")
        await self.start()
        await self._queue.put(task_id)

    async def cancel(self, task_id: UUID) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.estado not in {"pendiente", "ejecutando"}:
            return False

        task.estado = "cancelada"
        running_task = self._running_tasks.get(task_id)
        if running_task is not None:
            running_task.cancel()
        else:
            task.finalizada_en = task.finalizada_en or _utc_now()
        return True

    async def stop(self, timeout: float = 5.0) -> None:
        if not self._started:
            return
        self._accepting = False
        pending_workers = list(self._workers)
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            for task in self._running_tasks.values():
                task.cancel()
        finally:
            for worker in pending_workers:
                worker.cancel()
            await asyncio.gather(*pending_workers, return_exceptions=True)
            self._workers.clear()
            self._started = False

    async def _worker(self, worker_index: int) -> None:
        del worker_index
        while True:
            task_id = await self._queue.get()
            try:
                task = self._tasks.get(task_id)
                if task is None or task.estado == "cancelada":
                    continue

                task.estado = "ejecutando"
                task.iniciada_en = _utc_now()
                execution = asyncio.create_task(
                    self._run_with_timeout(task),
                )
                self._running_tasks[task_id] = execution
                try:
                    task.resultado = await execution
                except asyncio.CancelledError:
                    if task.estado != "cancelada":
                        task.estado = "cancelada"
                        raise
                except asyncio.TimeoutError:
                    task.estado = "fallida"
                    task.error = (
                        f"Tiempo de ejecucion agotado ({task.timeout} segundos)"
                    )
                except Exception as error:
                    task.estado = "fallida"
                    task.error = str(error)
                else:
                    task.estado = "completada"
                finally:
                    self._running_tasks.pop(task_id, None)
                    task.finalizada_en = task.finalizada_en or _utc_now()
            finally:
                self._queue.task_done()

    async def _run_with_timeout(self, task: TareaResponse) -> object:
        if task.timeout is None:
            return await self._executor(task)
        return await asyncio.wait_for(self._executor(task), task.timeout)


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
