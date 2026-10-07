"""Strict read-only contracts. Hashes and storage keys are never output fields."""
from datetime import datetime
from typing import Literal
from pydantic import Field
from app.schemas.dashboard import Contract, DecimalId, PageSize, PageOffset

AnalysisType = Literal['DUPLICATE_HASH', 'HASH_REPETIDO', 'VERSION_SIN_CAMBIO',
    'SECUENCIA_TEMPORAL', 'NUMERO_VERSION_DUPLICADO', 'METADATA_INCOMPLETA',
    'DOCUMENTO_SIN_VERSION', 'VERSION_VIGENTE_INCONGRUENTE', 'RELACION_INCONGRUENTE',
    'ESTADO_DESCONOCIDO', 'POSIBLE_DUPLICADO', 'ARCHIVO_NO_DISPONIBLE', 'RUTA_NO_SEGURA']


class AnalysisFilters(Contract):
    auditoria_id: DecimalId | None = None
    documento_id: DecimalId | None = None
    tipo: AnalysisType | None = None
    severidad: Literal['INFO', 'WARNING'] | None = None
    limit: PageSize = 20
    offset: PageOffset = 0


class AnalysisContext(Contract):
    auditoria_id: DecimalId | None = None
    documento_id: DecimalId | None = None


class Resource(Contract):
    pagina: Literal['documento', 'evidencia', 'hallazgo']
    id: DecimalId
    version_id: DecimalId | None = None


class Detection(Contract):
    tipo: AnalysisType
    clasificacion: Literal['señal', 'anomalía', 'posible duplicado', 'inconsistencia objetiva']
    severidad: Literal['INFO', 'WARNING']
    recurso: Literal['documento', 'version', 'evidencia', 'hallazgo']
    recurso_id: DecimalId
    nombre: str
    titulo: str
    explicacion: str
    evidencia_tecnica: list[str]
    regla: str
    evaluado_en: datetime
    destino: Resource
    relacionado: Resource | None = None
    similitud_nombre: float | None = Field(default=None, ge=0, le=1)


class DetectionPage(Contract):
    total: int = Field(ge=0)
    limit: PageSize
    offset: PageOffset
    items: list[Detection]


class AnalysisSummary(Contract):
    evaluado_en: datetime
    total: int = Field(ge=0)
    por_tipo: dict[AnalysisType, int]
    por_severidad: dict[Literal['INFO', 'WARNING'], int]
    alcance: str = 'Reglas SQL sobre recursos autorizados; similitud y storage se consultan en el detalle.'


class ResourceAnalysis(Contract):
    evaluado_en: datetime
    anomalias: DetectionPage
    comprobaciones_locales: list[Detection]
    versiones_comprobadas: int = Field(ge=0)
    versiones_comprobadas_limite: int = Field(ge=1)
    comprobacion_completa: bool
    candidatos_comparados: int = Field(ge=0)
    candidatos_limite: int = Field(ge=1)
    candidatos_truncados: bool
