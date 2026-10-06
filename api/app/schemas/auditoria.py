from datetime import date, datetime
from typing import Literal

from datetime import timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AuditState = Literal["PLANNED", "IN_PROGRESS", "IN_REVIEW", "COMPLETED", "CANCELLED"]


class AuditInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator('codigo', 'nombre', 'alcance', check_fields=False)
    @classmethod
    def clean_text(cls, value, info):
        if value is not None and any((ord(c) < 32 and not (info.field_name == 'alcance' and c in '\n\r\t')) or ord(c) == 127 for c in value):
            raise ValueError('Texto con caracteres de control')
        return value

    @field_validator('fecha_inicio_prevista', 'fecha_fin_prevista', 'inicio_desde', 'inicio_hasta', check_fields=False)
    @classmethod
    def mysql_date(cls, value):
        if value is not None and value.year < 1000:
            raise ValueError('Fecha fuera del rango MySQL')
        return value


class AuditoriaCreate(AuditInput):

    codigo: str = Field(min_length=1, max_length=60)
    nombre: str = Field(min_length=1, max_length=200)
    alcance: str = Field(min_length=1, max_length=16000)
    fecha_inicio_prevista: date | None = None
    fecha_fin_prevista: date | None = None
    responsable_id: int = Field(gt=0, strict=True)
    created_by_id: int | None = Field(default=None, deprecated=True)

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
    estado: AuditState
    fecha_inicio_prevista: date | None
    fecha_fin_prevista: date | None
    responsable_id: int
    created_by_id: int
    created_at: datetime
    updated_at: datetime
    updated_by_id: int | None = None
    iniciada_en: datetime | None = None
    completada_en: datetime | None = None
    responsable: "AuditReference | None" = None
    areas: list["AuditReference"] = Field(default_factory=list)


class AuditReference(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str


class AuditoriaUpdate(AuditInput):
    updated_at_esperado: datetime
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    alcance: str | None = Field(default=None, min_length=1, max_length=16000)
    fecha_inicio_prevista: date | None = None
    fecha_fin_prevista: date | None = None
    responsable_id: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode='after')
    def validate_patch(self):
        if not self.model_fields_set - {'updated_at_esperado'}:
            raise ValueError('Debe indicar al menos un campo editable')
        for name in ('nombre', 'alcance', 'responsable_id'):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError('Campo obligatorio no admite null')
        return self


class AuditoriaTransition(AuditInput):
    estado: Literal['IN_PROGRESS', 'IN_REVIEW', 'COMPLETED']
    estado_esperado: AuditState
    updated_at_esperado: datetime


class AuditoriaFilters(AuditInput):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=10000)
    q: str | None = Field(default=None, max_length=100)
    estado: AuditState | None = None
    responsable_id: int | None = Field(default=None, gt=0)
    area_id: int | None = Field(default=None, gt=0)
    inicio_desde: date | None = None
    inicio_hasta: date | None = None
    orden: Literal['id', '-id', 'fecha_inicio', '-fecha_inicio'] = 'id'

    @model_validator(mode='after')
    def date_range(self):
        if self.inicio_desde and self.inicio_hasta and self.inicio_hasta < self.inicio_desde:
            raise ValueError('Rango de fechas invalido')
        return self


class AuditEventRead(BaseModel):
    id: int
    actor_id: int | None
    accion: str
    ocurrido_en: datetime
    datos_anteriores: dict | None
    datos_nuevos: dict | None


def naive_utc(value: datetime):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
