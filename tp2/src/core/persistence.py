import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi.encoders import jsonable_encoder

from src.schemas import TareaResponse


logger = logging.getLogger(__name__)


class TaskPersistence:
    """Escribe volcados JSON y detecta volcados previos al iniciar."""

    def __init__(self, directory: str | Path = ".") -> None:
        self._directory = Path(directory)

    def report_previous_dumps(self) -> list[Path]:
        self._directory.mkdir(parents=True, exist_ok=True)
        dumps = sorted(self._directory.glob("estado_*.json"))
        if dumps:
            logger.info(
                "Se detectaron %d volcado(s) previo(s); ultimo: %s",
                len(dumps),
                dumps[-1],
            )
        else:
            logger.info("No se detectaron volcados previos")
        return dumps

    def dump(self, tasks: dict[UUID, TareaResponse]) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self._directory / f"estado_{timestamp}.json"
        payload = {
            "generado_en": datetime.now(timezone.utc),
            "tareas": list(tasks.values()),
        }
        destination.write_text(
            json.dumps(jsonable_encoder(payload), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Estado de %d tarea(s) volcado en %s", len(tasks), destination)
        return destination

    @staticmethod
    def load_tasks(path: str | Path) -> list[TareaResponse]:
        """Lee un volcado para herramientas de recuperación o inspección."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_tasks = payload.get("tareas", [])
        validator = getattr(TareaResponse, "model_validate", None)
        if validator is not None:
            return [validator(item) for item in raw_tasks]
        return [TareaResponse.parse_obj(item) for item in raw_tasks]
