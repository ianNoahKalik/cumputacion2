from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


TipoTarea = Literal["descargar", "hashear", "esperar"]
EstadoTarea = Literal[
    "pendiente",
    "ejecutando",
    "completada",
    "fallida",
    "cancelada",
]


class TareaCreate(BaseModel):
    tipo: TipoTarea
    parametros: dict[str, Any] = Field(default_factory=dict)
    timeout: float | None = Field(default=None, gt=0)


class TareaResponse(BaseModel):
    id: UUID
    tipo: TipoTarea
    estado: EstadoTarea
    parametros: dict[str, Any]
    resultado: Any | None = None
    error: str | None = None
    timeout: float | None = None
    creada_en: datetime
    iniciada_en: datetime | None = None
    finalizada_en: datetime | None = None


class EstadisticasResponse(BaseModel):
    totales_por_estado: dict[EstadoTarea, int]
    tiempo_promedio_segundos: float
    workers_ocupados: int