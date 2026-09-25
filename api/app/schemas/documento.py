"""Pydantic v2 schemas for Documentos and VersionesDocumento."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class VersionDocumentoBase(BaseModel):
    """Atributos base para una versión de documento."""
    comentario_cambio: str | None = Field(default=None, description="Motivo o descripción del cambio")


class VersionDocumentoCreate(VersionDocumentoBase):
    """Esquema para crear una nueva versión de documento."""
    pass


class VersionDocumentoRead(VersionDocumentoBase):
    """Esquema de salida para una versión de documento persistida."""
    id: int
    documento_id: int
    numero_version: int
    storage_key: str
    nombre_original: str
    mime_type: str
    tamano_bytes: int
    sha256: str
    subido_por_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentoBase(BaseModel):
    """Atributos base de un documento."""
    codigo: Annotated[str, StringConstraints(min_length=2, max_length=80, strip_whitespace=True)]
    titulo: Annotated[str, StringConstraints(min_length=3, max_length=240, strip_whitespace=True)]
    descripcion: str | None = None
    tipo: Annotated[str, StringConstraints(min_length=2, max_length=40, strip_whitespace=True)]
    estado: str = Field(default="DRAFT", description="Estado del documento: DRAFT, ACTIVE, OBSOLETE, ARCHIVED")
    area_id: int = Field(description="ID del área a la que pertenece el documento")
    responsable_id: int = Field(description="ID del usuario responsable del documento")


class DocumentoCreate(DocumentoBase):
    """Esquema para registrar un nuevo documento."""
    pass


class DocumentoUpdate(BaseModel):
    """Esquema para actualizar datos de cabecera de un documento."""
    titulo: Annotated[str, StringConstraints(min_length=3, max_length=240, strip_whitespace=True)] | None = None
    descripcion: str | None = None
    tipo: Annotated[str, StringConstraints(min_length=2, max_length=40, strip_whitespace=True)] | None = None
    estado: str | None = None
    area_id: int | None = None
    responsable_id: int | None = None


class DocumentoRead(DocumentoBase):
    """Esquema de salida para un documento persistido."""
    id: int
    created_by_id: int
    updated_by_id: int | None = None
    version_vigente_id: int | None = None
    created_at: datetime
    updated_at: datetime
    version_vigente: VersionDocumentoRead | None = None

    model_config = ConfigDict(from_attributes=True)
