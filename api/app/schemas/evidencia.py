"""Pydantic v2 schemas for Evidencias."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class TipoEvidenciaEnum(str, Enum):
    FILE = "FILE"
    REFERENCE = "REFERENCE"
    NOTE = "NOTE"
    OTHER = "OTHER"


class EvidenciaBase(BaseModel):
    """Atributos comunes de una evidencia."""
    auditoria_id: int = Field(description="ID de la auditoría a la que pertenece la evidencia")
    tipo: TipoEvidenciaEnum = Field(description="Tipo de evidencia: FILE, REFERENCE, NOTE, OTHER")
    titulo: Annotated[str, StringConstraints(min_length=3, max_length=200, strip_whitespace=True)]
    descripcion: str | None = None
    referencia_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    documento_id: int | None = Field(default=None, description="Documento del sistema vinculado (opcional)")
    version_documento_id: int | None = Field(default=None, description="Versión específica vinculada (opcional)")


class EvidenciaCreate(EvidenciaBase):
    """Esquema para crear evidencias sin archivo directo (NOTE, REFERENCE, OTHER)."""

    @model_validator(mode="after")
    def validate_tipo_requirements(self) -> EvidenciaCreate:
        if self.tipo == TipoEvidenciaEnum.REFERENCE and not self.referencia_url:
            raise ValueError("Las evidencias de tipo REFERENCE requieren 'referencia_url'")
        if self.version_documento_id is not None and self.documento_id is None:
            raise ValueError("Si se vincula 'version_documento_id', 'documento_id' es obligatorio")
        return self


class EvidenciaArchivoCreate(BaseModel):
    """Metadatos para acompañar la subida de un archivo de evidencia."""
    auditoria_id: int
    titulo: Annotated[str, StringConstraints(min_length=3, max_length=200, strip_whitespace=True)]
    descripcion: str | None = None
    documento_id: int | None = None
    version_documento_id: int | None = None


class EvidenciaRead(EvidenciaBase):
    """Esquema de salida para una evidencia persistida con sus metadatos forenses."""
    id: int
    storage_key: str | None = None
    nombre_original: str | None = None
    mime_type: str | None = None
    tamano_bytes: int | None = None
    sha256: str | None = None
    registrada_por_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
