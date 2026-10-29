import asyncio

from src.schemas import TareaResponse


async def execute_task(task: TareaResponse) -> object:
    """Ejecutor base; las operaciones concretas se completan en la FASE 3."""
    if task.tipo == "esperar":
        segundos = task.parametros.get("segundos", 0)
        await asyncio.sleep(float(segundos))
        return {"segundos": segundos}
    await asyncio.sleep(0)
    return {"tipo": task.tipo, "estado": "procesada"}
