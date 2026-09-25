"""Esquemas de entrada y salida de la API (Pydantic v2)."""

from app.schemas.documento import (
    DocumentoBase,
    DocumentoCreate,
    DocumentoRead,
    DocumentoUpdate,
    VersionDocumentoBase,
    VersionDocumentoCreate,
    VersionDocumentoRead,
)
from app.schemas.evidencia import (
    EvidenciaArchivoCreate,
    EvidenciaBase,
    EvidenciaCreate,
    EvidenciaRead,
    TipoEvidenciaEnum,
)

__all__ = [
    "DocumentoBase",
    "DocumentoCreate",
    "DocumentoRead",
    "DocumentoUpdate",
    "VersionDocumentoBase",
    "VersionDocumentoCreate",
    "VersionDocumentoRead",
    "EvidenciaArchivoCreate",
    "EvidenciaBase",
    "EvidenciaCreate",
    "EvidenciaRead",
    "TipoEvidenciaEnum",
]
