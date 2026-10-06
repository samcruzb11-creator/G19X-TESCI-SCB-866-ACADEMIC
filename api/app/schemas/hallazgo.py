"""7B DTOs use the existing domain fields and CHECK values."""
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.auditoria import AuditReference

MAX_ID = 18446744073709551615  # Existing MySQL BIGINT UNSIGNED domain.

FindingState = Literal['OPEN', 'IN_PROGRESS', 'PENDING_VERIFICATION', 'CLOSED', 'ACCEPTED_RISK']
Severity = Literal['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']


class FindingInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('updated_at_esperado', mode='before', check_fields=False)
    @classmethod
    def timestamp_type(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError('Fecha y hora ISO requerida')
        return value

    @field_validator('titulo', 'descripcion', 'categoria', 'resolucion', 'contexto', 'q', check_fields=False)
    @classmethod
    def clean_text(cls, value, info):
        if value is not None and any((ord(c) < 32 and not (info.field_name in {'descripcion', 'resolucion', 'contexto'} and c in '\r\n\t')) or ord(c) == 127 for c in value):
            raise ValueError('Texto con caracteres de control')
        return value

    @field_validator('fecha_limite', check_fields=False)
    @classmethod
    def mysql_date(cls, value):
        if value and value.year < 1000:
            raise ValueError('Fecha fuera del rango MySQL')
        return value


class HallazgoCreate(FindingInput):
    auditoria_id: int = Field(gt=0, le=MAX_ID, strict=True)
    titulo: str = Field(min_length=1, max_length=200)
    descripcion: str = Field(min_length=1, max_length=16000)
    categoria: str = Field(min_length=1, max_length=40)
    severidad: Severity
    responsable_id: int | None = Field(default=None, gt=0, le=MAX_ID, strict=True)
    fecha_limite: date | None = None


class HallazgoUpdate(FindingInput):
    updated_at_esperado: datetime
    titulo: str | None = Field(default=None, min_length=1, max_length=200)
    descripcion: str | None = Field(default=None, min_length=1, max_length=16000)
    categoria: str | None = Field(default=None, min_length=1, max_length=40)
    severidad: Severity | None = None
    responsable_id: int | None = Field(default=None, gt=0, le=MAX_ID, strict=True)
    fecha_limite: date | None = None
    resolucion: str | None = Field(default=None, min_length=1, max_length=16000)

    @model_validator(mode='after')
    def patch(self):
        if not self.model_fields_set - {'updated_at_esperado'}:
            raise ValueError('Debe indicar al menos un campo editable')
        for name in ('titulo', 'descripcion', 'categoria', 'severidad'):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError('Campo obligatorio no admite null')
        return self


class HallazgoTransition(FindingInput):
    estado: FindingState
    estado_esperado: FindingState
    updated_at_esperado: datetime
    resolucion: str | None = Field(default=None, min_length=1, max_length=16000)


class HallazgoLink(FindingInput):
    evidencia_id: int = Field(gt=0, le=MAX_ID, strict=True)
    contexto: str | None = Field(default=None, min_length=1, max_length=16000)


class HallazgoFilters(FindingInput):
    auditoria_id: int | None = Field(default=None, gt=0, le=MAX_ID)
    evidencia_id: int | None = Field(default=None, gt=0, le=MAX_ID)
    estado: FindingState | None = None
    severidad: Severity | None = None
    responsable_id: int | None = Field(default=None, gt=0, le=MAX_ID)
    q: str | None = Field(default=None, max_length=100)
    orden: Literal['id', '-id', 'numero', '-numero'] = 'id'
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=10000)


class HallazgoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    auditoria_id: int
    numero: int
    titulo: str
    descripcion: str
    categoria: str
    severidad: Severity
    estado: FindingState
    responsable_id: int | None
    responsable: AuditReference | None = None
    detectado_en: datetime
    fecha_limite: date | None
    resolucion: str | None
    cerrado_por_id: int | None
    cerrado_en: datetime | None
    created_by_id: int
    updated_by_id: int | None
    created_at: datetime
    updated_at: datetime
    evidencias_count: int = 0


class PageInput(FindingInput):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
