"""Commands for existing version approval rounds; identity is server-owned."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.hallazgo import MAX_ID
from app.schemas.auditoria import AuditReference

RoundState = Literal['PENDING', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'CANCELLED']
DecisionState = Literal['APPROVED', 'REJECTED', 'CHANGES_REQUESTED']
StrictId = Annotated[int, Field(gt=0, le=MAX_ID, strict=True)]


def path_integer(value):
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    if type(value) is int:
        return value
    raise ValueError('Entero decimal requerido')


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('updated_at_esperado', mode='before', check_fields=False)
    @classmethod
    def timestamp_type(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError('Fecha y hora ISO requerida')
        return value

    @field_validator('comentario', 'q', check_fields=False)
    @classmethod
    def clean_text(cls, value):
        if value is not None and any((ord(c) < 32 and c not in '\r\n\t') or ord(c) == 127 for c in value):
            raise ValueError('Texto con caracteres de control')
        return value


class RondaCreate(ApprovalInput):
    documento_id: StrictId
    version_documento_id: StrictId
    auditoria_id: StrictId | None = None
    aprobadores_ids: list[StrictId] = Field(min_length=1, max_length=20)

    @field_validator('aprobadores_ids')
    @classmethod
    def unique_approvers(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Aprobadores duplicados')
        return value


class RondaCommand(ApprovalInput):
    estado_esperado: RoundState
    updated_at_esperado: datetime


class DecisionCommand(ApprovalInput):
    estado: DecisionState
    updated_at_esperado: datetime  # The caller's pending assignment, not a shared vote token.
    comentario: str | None = Field(default=None, max_length=16000)


class ApprovalPage(ApprovalInput):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)

    @field_validator('limit', 'offset', 'documento_id', 'version_documento_id', 'auditoria_id',
                     mode='before', check_fields=False)
    @classmethod
    def query_integer(cls, value):
        # Query strings are decimal integers; forbid coercion of bool/float,
        # scientific notation and decimal strings such as "1.0".
        if value is None or type(value) is int:
            return value
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        raise ValueError('Entero decimal requerido')


class RondaFilters(ApprovalPage):
    documento_id: int | None = Field(default=None, gt=0, le=MAX_ID)
    version_documento_id: int | None = Field(default=None, gt=0, le=MAX_ID)
    auditoria_id: int | None = Field(default=None, gt=0, le=MAX_ID)
    estado: RoundState | None = None
    pendientes_propias: bool = False
    q: str | None = Field(default=None, max_length=100)
    orden: Literal['id', '-id'] = '-id'


class ResourceFilters(ApprovalPage):
    documento_id: int | None = Field(default=None, gt=0, le=MAX_ID)
    auditoria_id: int | None = Field(default=None, gt=0, le=MAX_ID)


class ApproverFilters(ApprovalPage):
    q: str | None = Field(default=None, max_length=100)


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ronda_aprobacion_id: int
    aprobador_id: int
    aprobador: AuditReference
    estado: Literal['PENDING', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED']
    comentario: str | None
    asignada_en: datetime
    decidida_en: datetime | None
    updated_at: datetime


class ApprovalResource(BaseModel):
    documento_id: int
    documento_titulo: str
    version_documento_id: int
    numero_version: int


class RondaRead(ApprovalResource):
    id: int
    numero_ronda: int
    estado: RoundState
    solicitada_por: AuditReference
    solicitada_en: datetime
    resuelta_en: datetime | None
    created_at: datetime
    updated_at: datetime
    decisiones_count: int
    pendientes_count: int
    mi_decision: DecisionRead | None
    puede_decidir: bool
    puede_gestionar: bool
