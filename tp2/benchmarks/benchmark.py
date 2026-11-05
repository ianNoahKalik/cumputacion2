import argparse
import asyncio
import time
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from src.main import _tareas, app, lifespan
from src.schemas import TareaResponse
from src.tasks.executor import (
    _iterated_sha256,
    execute_task,
    shutdown_executor,
)


DEFAULT_DELAY = 0.02
DEFAULT_ITERATIONS = 2_000_000
DEFAULT_BATCHES = (1, 2, 4, 8, 16, 32)


async def run_io_benchmark(delay: float) -> None:
    async with _local_http_server(delay) as url:
        urls = [url] * 20
        sequential_task = _benchmark_task("descargar", {"urls": [url]})
        concurrent_task = _benchmark_task("descargar", {"urls": urls})

        started = time.perf_counter()
        for _ in urls:
            await execute_task(sequential_task)
        sequential = time.perf_counter() - started

        started = time.perf_counter()
        await execute_task(concurrent_task)
        concurrent = time.perf_counter() - started

    print("\nMEDICION 1 - CONCURRENCIA I/O")
    print(f"Descargas: 20 | demora controlada: {delay:.3f}s")
    print(f"Secuencial: {sequential:.4f}s")
    print(f"Concurrente: {concurrent:.4f}s")
    print(f"Speedup: {sequential / concurrent:.2f}x")


async def run_event_loop_benchmark(iterations: int) -> None:
    await _run_in_executor(1_000)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://benchmark",
    ) as client:
        direct = await _measure_get_during(
            client,
            _run_in_main_process(iterations),
        )
        executor = await _measure_get_during(
            client,
            _run_in_executor(iterations),
        )

    print("\nMEDICION 2 - BLOQUEO DEL EVENT LOOP")
    print(f"Iteraciones SHA-256: {iterations:,}")
    print(f"GET /tareas con hash en event loop: {direct:.4f}s")
    print(f"GET /tareas con ProcessPoolExecutor: {executor:.4f}s")
    print(f"Mejora de latencia: {direct / executor:.2f}x")


async def _measure_get_during(
    client: httpx.AsyncClient,
    cpu_work: Awaitable[object],
) -> float:
    started = time.perf_counter()
    cpu_task = asyncio.create_task(cpu_work)
    await asyncio.sleep(0)
    response_task = asyncio.create_task(client.get("/tareas"))
    await response_task
    elapsed = time.perf_counter() - started
    await cpu_task
    return elapsed


async def _run_in_main_process(iterations: int) -> str:
    return _iterated_sha256("benchmark", iterations)


async def _run_in_executor(iterations: int) -> object:
    task = _benchmark_task(
        "hashear",
        {"texto": "benchmark", "iteraciones": iterations},
    )
    return await execute_task(task)


async def run_pool_benchmark(batches: tuple[int, ...]) -> None:
    _tareas.clear()
    async with lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://benchmark",
        ) as client:
            print("\nMEDICION 3 - TECHO DEL POOL")
            print("batch, tiempo_total_s, tiempo_promedio_por_tarea_s")
            for batch_size in batches:
                _tareas.clear()
                started = time.perf_counter()
                responses = await asyncio.gather(
                    *(
                        client.post(
                            "/tareas",
                            json={
                                "tipo": "esperar",
                                "parametros": {"segundos": DEFAULT_DELAY},
                            },
                        )
                        for _ in range(batch_size)
                    ),
                )
                task_ids = [response.json()["id"] for response in responses]
                await _wait_for_tasks(client, task_ids)
                elapsed = time.perf_counter() - started
                print(f"{batch_size}, {elapsed:.4f}, {elapsed / batch_size:.4f}")
    _tareas.clear()


async def _wait_for_tasks(
    client: httpx.AsyncClient,
    task_ids: list[str],
) -> None:
    deadline = time.perf_counter() + 30
    while time.perf_counter() < deadline:
        states = await asyncio.gather(
            *(client.get(f"/tareas/{task_id}") for task_id in task_ids),
        )
        if all(response.json()["estado"] == "completada" for response in states):
            return
        await asyncio.sleep(0.005)
    raise TimeoutError("El benchmark del pool no finalizo a tiempo")


def _benchmark_task(tipo: str, parametros: dict) -> TareaResponse:
    now = datetime.now(timezone.utc)
    return TareaResponse(
        id=uuid4(),
        tipo=tipo,
        estado="pendiente",
        parametros=parametros,
        creada_en=now,
    )


@asynccontextmanager
async def _local_http_server(delay: float):
    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            await asyncio.sleep(delay)
            body = b"benchmark-response"
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body,
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    address = server.sockets[0].getsockname()
    try:
        yield f"http://127.0.0.1:{address[1]}/"
    finally:
        server.close()
        await server.wait_closed()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmarks de la FASE 6")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument(
        "--batches",
        type=int,
        nargs="+",
        default=list(DEFAULT_BATCHES),
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    if args.delay <= 0 or args.iterations < 1 or any(size < 1 for size in args.batches):
        raise ValueError("Los parametros del benchmark deben ser positivos")
    await run_io_benchmark(args.delay)
    await run_event_loop_benchmark(args.iterations)
    try:
        await run_pool_benchmark(tuple(args.batches))
    finally:
        await shutdown_executor()


if __name__ == "__main__":
    asyncio.run(_main())
