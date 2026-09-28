from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class EventoAuditoriaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    actor_snapshot: str | None
    accion: str
    entidad_tipo: str
    entidad_id: str
    ocurrido_en: datetime
    correlation_id: str | None
    datos_anteriores: dict[str, Any] | None
    datos_nuevos: dict[str, Any] | None
