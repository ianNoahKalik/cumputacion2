import asyncio
import hashlib
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import httpx

from src.schemas import TareaResponse


_process_pool: ProcessPoolExecutor | None = None


async def execute_task(task: TareaResponse) -> object:
    if task.tipo == "esperar":
        segundos = _positive_number(task.parametros, "segundos", default=0)
        await asyncio.sleep(segundos)
        return {"segundos": segundos}
    if task.tipo == "descargar":
        return await _download_urls(task.parametros)
    if task.tipo == "hashear":
        return await _hash_text(task.parametros)
    raise ValueError(f"Tipo de tarea no soportado: {task.tipo}")


async def shutdown_executor() -> None:
    """Libera los procesos auxiliares al apagar la aplicación."""
    global _process_pool
    if _process_pool is not None:
        _process_pool.shutdown(wait=True, cancel_futures=True)
        _process_pool = None


async def _download_urls(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    urls = parameters.get("urls")
    if not isinstance(urls, list) or not urls or not all(
        isinstance(url, str) and url for url in urls
    ):
        raise ValueError("descargar requiere una lista no vacia de URLs")

    timeout = parameters.get("timeout", 10.0)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("El timeout de descarga debe ser mayor que cero")

    async with httpx.AsyncClient(timeout=float(timeout)) as client:
        return await asyncio.gather(
            *(_download_one(client, url) for url in urls),
        )


async def _download_one(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = await client.get(url)
        return {
            "url": url,
            "codigo": response.status_code,
            "tamano": len(response.content),
            "tiempo_segundos": time.perf_counter() - started,
        }
    except httpx.HTTPError as error:
        return {
            "url": url,
            "error": str(error),
            "tiempo_segundos": time.perf_counter() - started,
        }


async def _hash_text(parameters: dict[str, Any]) -> dict[str, Any]:
    text = parameters.get("texto")
    iterations = parameters.get("iteraciones")
    if not isinstance(text, str):
        raise ValueError("hashear requiere el parametro texto")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations < 1:
        raise ValueError("hashear requiere iteraciones enteras mayores que cero")

    loop = asyncio.get_running_loop()
    digest = await loop.run_in_executor(
        _get_process_pool(),
        _iterated_sha256,
        text,
        iterations,
    )
    return {"hash": digest, "iteraciones": iterations}


def _get_process_pool() -> ProcessPoolExecutor:
    global _process_pool
    if _process_pool is None:
        _process_pool = ProcessPoolExecutor()
    return _process_pool


def _iterated_sha256(text: str, iterations: int) -> str:
    digest = text.encode("utf-8")
    for _ in range(iterations):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()


def _positive_number(
    parameters: dict[str, Any],
    name: str,
    *,
    default: float | int | None = None,
) -> float:
    value = parameters.get(name, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} debe ser un numero mayor o igual que cero")
    return float(value)
