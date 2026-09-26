"""Esquemas de entrada y salida de la API (Pydantic v2)."""

from app.schemas.documento import (
    DocumentoAuditoriaCreate,
    DocumentoAuditoriaRead,
    DocumentoBase,
    DocumentoConVersionesRead,
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
    # Documento
    "DocumentoBase",
    "DocumentoCreate",
    "DocumentoRead",
    "DocumentoUpdate",
    "DocumentoConVersionesRead",
    # VersionDocumento
    "VersionDocumentoBase",
    "VersionDocumentoCreate",
    "VersionDocumentoRead",
    # DocumentoAuditoria (pivot)
    "DocumentoAuditoriaCreate",
    "DocumentoAuditoriaRead",
    # Evidencia
    "EvidenciaArchivoCreate",
    "EvidenciaBase",
    "EvidenciaCreate",
    "EvidenciaRead",
    "TipoEvidenciaEnum",
]
