"""Read-only, server-owned dashboard contracts on schema 005."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator
from app.schemas.aprobacion import path_integer
from app.schemas.hallazgo import MAX_ID

DecimalId = Annotated[int, BeforeValidator(path_integer), Field(strict=True, gt=0, le=MAX_ID)]
PageSize = Annotated[int, BeforeValidator(path_integer), Field(strict=True, ge=1, le=100)]
PageOffset = Annotated[int, BeforeValidator(path_integer), Field(strict=True, ge=0, le=10000)]
AlertType = Literal['AUDITORIA_ACTIVA', 'AUDITORIA_REVISION', 'HALLAZGO_PENDIENTE',
                    'RONDA_PENDIENTE', 'DECISION_PROPIA_PENDIENTE', 'DOCUMENTO_SIN_VERSION']
AlertSeverity = Literal['INFO', 'WARNING']
ResourceType = Literal['auditoria', 'hallazgo', 'aprobacion', 'documento']
StateKey = Literal['PLANNED', 'IN_PROGRESS', 'IN_REVIEW', 'COMPLETED', 'CANCELLED',
    'OPEN', 'PENDING_VERIFICATION', 'CLOSED', 'ACCEPTED_RISK', 'PENDING', 'APPROVED',
    'REJECTED', 'CHANGES_REQUESTED', 'FILE', 'REFERENCE', 'NOTE', 'OTHER', 'DESCONOCIDO']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class DashboardContext(Contract):
    auditoria_id: DecimalId | None = None


class DashboardPage(DashboardContext):
    limit: PageSize = 10
    offset: PageOffset = 0


class AlertFilters(DashboardPage):
    tipo: AlertType | None = None
    severidad: AlertSeverity | None = None


class Distribution(Contract):
    total: int = Field(ge=0)
    por_estado: dict[StateKey, int]


class Ratio(Contract):
    numerador: int = Field(ge=0)
    denominador: int = Field(ge=0)
    porcentaje: float | None = Field(ge=0, le=100)
    estado: Literal['OK', 'NO_DATA', 'NOT_APPLICABLE']


class Documents(Contract):
    total: int = Field(ge=0)
    versiones: int = Field(ge=0)
    sin_version: int | None = Field(ge=0)


class Decisions(Distribution):
    resueltas: int = Field(ge=0)
    pendientes_propias: int | None = Field(ge=0)


class Indicators(Contract):
    auditorias: Distribution | None
    hallazgos: Distribution | None
    aprobaciones: Distribution | None
    decisiones: Decisions | None
    documentos: Documents | None
    evidencias: Distribution | None
    auditorias_completadas: Ratio
    hallazgos_cerrados: Ratio
    rondas_resueltas: Ratio
    documentos_con_version: Ratio


class Destination(Contract):
    pagina: ResourceType
    id: DecimalId


class Alert(Contract):
    clave: str  # Presentation key; never a persistent database PK.
    tipo: AlertType
    severidad: AlertSeverity
    titulo: str
    descripcion: str
    recurso: ResourceType
    recurso_id: DecimalId
    nombre: str
    fecha: datetime
    destino: Destination


class AlertPage(Contract):
    total: int = Field(ge=0)
    limit: PageSize
    offset: PageOffset
    items: list[Alert]


class Activity(Contract):
    id: DecimalId
    accion: str
    titulo: str
    ocurrido_en: datetime
    destino: Destination


class ActivityPage(Contract):
    total: int = Field(ge=0)
    limit: PageSize
    offset: PageOffset
    items: list[Activity]


class Summary(Contract):
    generado_en: datetime
    indicadores: Indicators
    alertas: AlertPage
    actividad: ActivityPage
