"""Pydantic v2 schemas for Evidencias.

Sincronizados con ``api/app/models/entities.py`` (SQLAlchemy 2.x, MySQL 8.0).
Los campos criptográficos (``storage_key``, ``sha256``, ``tamano_bytes``)
son asignados exclusivamente por ``StorageService`` y no los envía el cliente.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator, field_validator
from urllib.parse import urlsplit


# ===========================================================================
# Enumeraciones — espejo de los CHECK constraints en entities.py
# ===========================================================================

class TipoEvidenciaEnum(str, Enum):
    """Tipos de evidencia aceptados por el sistema."""

    FILE = "FILE"            # Archivo físico (SHA-256 obligatorio)
    REFERENCE = "REFERENCE"  # URL externa (referencia_url obligatorio)
    NOTE = "NOTE"            # Nota de texto libre
    OTHER = "OTHER"          # Otro tipo de referencia documental


# ===========================================================================
# EvidenciaBase
# ===========================================================================

def _clean_text(value, info):
    if value is not None and any((ord(c) < 32 and not (info.field_name == 'descripcion' and c in '\r\n\t')) or ord(c) == 127 for c in value):
        raise ValueError('Texto con caracteres de control')
    return value

class EvidenciaBase(BaseModel):
    """Atributos comunes de una evidencia (todos los tipos)."""

    auditoria_id: int = Field(description="ID de la auditoría a la que pertenece la evidencia")
    tipo: TipoEvidenciaEnum = Field(description="Tipo de evidencia: FILE, REFERENCE, NOTE, OTHER")
    titulo: Annotated[
        str, StringConstraints(min_length=3, max_length=200, strip_whitespace=True)
    ]
    descripcion: str | None = None
    referencia_url: (
        Annotated[str, StringConstraints(max_length=2048)] | None
    ) = Field(default=None, description="URL externa (requerido si tipo=REFERENCE)")
    documento_id: int | None = Field(
        default=None, description="Documento del sistema vinculado (opcional)"
    )
    version_documento_id: int | None = Field(
        default=None, description="Versión específica vinculada (requiere documento_id)"
    )


# ===========================================================================
# EvidenciaCreate — para evidencias NO-FILE (NOTE, REFERENCE, OTHER)
# ===========================================================================

class EvidenciaCreate(EvidenciaBase):
    """Esquema para crear evidencias sin archivo físico (NOTE, REFERENCE, OTHER).

    Para evidencias de tipo FILE, usar ``EvidenciaArchivoCreate`` acompañado
    del binario en un ``multipart/form-data``.
    """

    model_config = ConfigDict(extra='forbid')
    descripcion: str | None = Field(default=None, max_length=16000)
    _validate_text = field_validator('titulo', 'descripcion', 'referencia_url')(_clean_text)
    hallazgo_id: int | None = Field(default=None, gt=0, strict=True)
    auditoria_id: int = Field(gt=0, strict=True)
    documento_id: int | None = Field(default=None, gt=0, strict=True)
    version_documento_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator('referencia_url')
    @classmethod
    def safe_reference(cls, value):
        if value is not None:
            parsed = urlsplit(value)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Referencia HTTP/HTTPS sin credenciales requerida')
        return value

    @model_validator(mode="after")
    def validate_tipo_requirements(self) -> EvidenciaCreate:
        if self.tipo == TipoEvidenciaEnum.FILE:
            raise ValueError(
                "Las evidencias de tipo FILE deben enviarse mediante el endpoint "
                "de carga de archivos (multipart/form-data), no por este esquema."
            )
        if self.tipo == TipoEvidenciaEnum.REFERENCE and not self.referencia_url:
            raise ValueError("Las evidencias de tipo REFERENCE requieren 'referencia_url'.")
        if self.version_documento_id is not None and self.documento_id is None:
            raise ValueError(
                "Si se vincula 'version_documento_id', 'documento_id' es obligatorio."
            )
        return self


# ===========================================================================
# EvidenciaArchivoCreate — metadatos que acompañan al archivo en multipart
# ===========================================================================

class EvidenciaArchivoCreate(BaseModel):
    """Metadatos del cliente para la subida de un archivo de evidencia.

    Se envía como parte de un ``multipart/form-data`` junto con el binario.
    Los campos criptográficos (``storage_key``, ``sha256``, ``tamano_bytes``,
    ``nombre_original``, ``mime_type``) los asigna el ``StorageService``
    internamente y **no** se incluyen aquí.
    """

    _validate_text = field_validator('titulo', 'descripcion')(_clean_text)
    auditoria_id: int = Field(description="ID de la auditoría destinataria")
    titulo: Annotated[
        str, StringConstraints(min_length=3, max_length=200, strip_whitespace=True)
    ]
    descripcion: str | None = Field(default=None, max_length=16000)
    documento_id: int | None = Field(
        default=None, description="Documento del sistema al que pertenece este archivo"
    )
    version_documento_id: int | None = Field(
        default=None, description="Versión específica del documento (requiere documento_id)"
    )

    @model_validator(mode="after")
    def validate_version_requiere_documento(self) -> EvidenciaArchivoCreate:
        if self.version_documento_id is not None and self.documento_id is None:
            raise ValueError(
                "Si se vincula 'version_documento_id', 'documento_id' es obligatorio."
            )
        return self


# ===========================================================================
# EvidenciaRead — respuesta completa del API
# ===========================================================================

class EvidenciaListRead(EvidenciaBase):
    """Metadatos públicos para el listado, sin claves internas de almacenamiento."""

    id: int
    # Metadatos de archivo — solo presentes cuando tipo == FILE
    nombre_original: str | None = None
    mime_type: str | None = None
    tamano_bytes: int | None = None
    sha256: str | None = Field(
        default=None,
        description="SHA-256 hexadecimal (64 chars) del archivo. Presente solo si tipo=FILE.",
    )
    registrada_por_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvidenciaRead(EvidenciaListRead):
    """Contrato existente de detalle y registro, conservado por compatibilidad."""

    storage_key: str | None = None
