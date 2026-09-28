"""Pydantic v2 schemas for Documentos and VersionesDocumento.

Sincronizados con ``api/app/models/entities.py`` (SQLAlchemy 2.x, MySQL 8.0).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# ---------------------------------------------------------------------------
# Allowed literal sets (mirror CHECK constraints in entities.py)
# ---------------------------------------------------------------------------
ESTADOS_DOCUMENTO = {"DRAFT", "ACTIVE", "OBSOLETE", "ARCHIVED"}
ESTADOS_REVISION = {"PENDING", "REVIEWED", "ACCEPTED", "REJECTED"}


# ===========================================================================
# VersionDocumento
# ===========================================================================

class VersionDocumentoBase(BaseModel):
    """Atributos editables por el cliente al crear una versión de documento."""

    comentario_cambio: str | None = Field(
        default=None, description="Motivo o descripción del cambio"
    )


class VersionDocumentoCreate(VersionDocumentoBase):
    """Esquema para solicitar la creación de una nueva versión.

    Los campos criptográficos (``storage_key``, ``sha256``, ``tamano_bytes``,
    ``nombre_original``, ``mime_type``) los asigna el ``StorageService`` y
    **no** los envía el cliente en el body JSON.
    """

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
    sha256: str = Field(description="SHA-256 hexadecimal (64 chars) del archivo")
    subido_por_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# Documento
# ===========================================================================

class DocumentoBase(BaseModel):
    """Atributos base de un documento."""

    codigo: Annotated[
        str, StringConstraints(min_length=2, max_length=80, strip_whitespace=True)
    ]
    titulo: Annotated[
        str, StringConstraints(min_length=3, max_length=240, strip_whitespace=True)
    ]
    descripcion: str | None = None
    tipo: Annotated[
        str, StringConstraints(min_length=2, max_length=40, strip_whitespace=True)
    ]
    estado: str = Field(
        default="DRAFT",
        description=f"Estado del documento. Permitidos: {sorted(ESTADOS_DOCUMENTO)}",
    )
    area_id: int = Field(description="ID del área propietaria del documento")
    responsable_id: int = Field(description="ID del usuario responsable del documento")


class DocumentoCreate(DocumentoBase):
    """Esquema para registrar un nuevo documento (sin archivo aún)."""

    pass


class DocumentoUpdate(BaseModel):
    """Esquema PATCH para actualizar cabecera de un documento.

    Todos los campos son opcionales; solo se actualizan los que se envíen.
    """

    titulo: (
        Annotated[str, StringConstraints(min_length=3, max_length=240, strip_whitespace=True)]
        | None
    ) = None
    descripcion: str | None = None
    tipo: (
        Annotated[str, StringConstraints(min_length=2, max_length=40, strip_whitespace=True)]
        | None
    ) = None
    estado: str | None = Field(
        default=None,
        description=f"Nuevo estado. Permitidos: {sorted(ESTADOS_DOCUMENTO)}",
    )
    area_id: int | None = None
    responsable_id: int | None = None


class DocumentoRead(DocumentoBase):
    """Esquema de salida para un documento persistido (cabecera)."""

    id: int
    created_by_id: int
    updated_by_id: int | None = None
    version_vigente_id: int | None = None
    created_at: datetime
    updated_at: datetime
    # Relación eager opcional — se incluye cuando el endpoint la carga
    version_vigente: VersionDocumentoRead | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentoConVersionesRead(DocumentoRead):
    """Esquema extendido que incluye todas las versiones del documento.

    Útil para endpoints de detalle (GET /documentos/{id}) que necesitan
    exponer el historial completo de versiones.
    """

    versiones: list[VersionDocumentoRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DocumentoDetalleRead(DocumentoRead):
    """Versiones only appears when explicitly requested by the client."""

    versiones: list[VersionDocumentoRead] | None = None


# ===========================================================================
# DocumentoAuditoria (pivot)
# ===========================================================================

class DocumentoAuditoriaBase(BaseModel):
    """Atributos base de la asociación Documento ↔ Auditoría."""

    documento_id: int
    auditoria_id: int
    version_documento_id: int
    proposito: Annotated[
        str, StringConstraints(min_length=2, max_length=40, strip_whitespace=True)
    ]
    contexto: str | None = None
    estado_revision: str = Field(
        default="PENDING",
        description=f"Estado de revisión. Permitidos: {sorted(ESTADOS_REVISION)}",
    )
    observaciones: str | None = None


class DocumentoAuditoriaCreate(DocumentoAuditoriaBase):
    """Esquema para asociar un documento a una auditoría."""

    pass


class DocumentoAuditoriaRead(DocumentoAuditoriaBase):
    """Esquema de salida para una asociación Documento ↔ Auditoría."""

    id: int
    asociado_por_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
