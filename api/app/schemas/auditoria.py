from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuditoriaCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    codigo: str = Field(min_length=1, max_length=60)
    nombre: str = Field(min_length=1, max_length=200)
    alcance: str = Field(min_length=1)
    fecha_inicio_prevista: date | None = None
    fecha_fin_prevista: date | None = None
    responsable_id: int = Field(gt=0)
    created_by_id: int = Field(gt=0)

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_inicio_prevista and self.fecha_fin_prevista and self.fecha_fin_prevista < self.fecha_inicio_prevista:
            raise ValueError("La fecha final prevista no puede preceder a la inicial")
        return self


class AuditoriaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    alcance: str
    estado: Literal["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    fecha_inicio_prevista: date | None
    fecha_fin_prevista: date | None
    responsable_id: int
    created_by_id: int
    created_at: datetime
    updated_at: datetime
