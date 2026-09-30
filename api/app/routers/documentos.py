"""Endpoints REST para documentos y sus versiones."""

from typing import Annotated
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload, raiseload

from app.db.session import get_db
from app.models.entities import Documento, EventoAuditoria, VersionDocumento
from app.schemas.documento import (
    DocumentoDetalleRead,
    DocumentoListRead,
    DocumentoCreate,
    DocumentoRead,
    DocumentoUpdate,
    VersionDocumentoRead,
    VersionDocumentoListRead,
)
from app.services.documento_service import documento_service
from app.services.storage_service import storage_service
from app.schemas.evento import EventoAuditoriaRead

router = APIRouter(prefix="/documentos", tags=["documentos"])


def _client_info(request: Request) -> dict[str, str | None]:
    return {"ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")}


@router.post("", response_model=DocumentoRead, status_code=status.HTTP_201_CREATED)
def crear_documento(
    payload: DocumentoCreate,
    request: Request,
    creador_id: Annotated[int, Query(gt=0)],
    db: Session = Depends(get_db),
):
    try:
        return documento_service.crear_documento(db, payload, creador_id, client_info=_client_info(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[DocumentoListRead])
def listar_documentos(
    tipo: str | None = None,
    estado: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    stmt = select(Documento).options(joinedload(Documento.version_vigente))
    if tipo:
        stmt = stmt.where(Documento.tipo == tipo)
    if estado:
        stmt = stmt.where(Documento.estado == estado)
    stmt = stmt.order_by(Documento.id).offset(offset).limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/{documento_id}", response_model=DocumentoDetalleRead, response_model_exclude_unset=True)
def obtener_documento(
    documento_id: int,
    incluir_versiones: bool = False,
    db: Session = Depends(get_db),
):
    stmt = select(Documento).where(Documento.id == documento_id).options(
        joinedload(Documento.version_vigente)
    )
    if incluir_versiones:
        stmt = stmt.options(selectinload(Documento.versiones))
    else:
        stmt = stmt.options(raiseload(Documento.versiones))
    documento = db.scalar(stmt)
    if documento is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    data = DocumentoRead.model_validate(documento).model_dump()
    if incluir_versiones:
        data["versiones"] = [VersionDocumentoRead.model_validate(v) for v in documento.versiones]
    return DocumentoDetalleRead(**data)


@router.patch("/{documento_id}", response_model=DocumentoRead)
def actualizar_documento(
    documento_id: int,
    payload: DocumentoUpdate,
    request: Request,
    editor_id: Annotated[int, Query(gt=0)],
    db: Session = Depends(get_db),
):
    try:
        return documento_service.actualizar_cabecera(
            db, documento_id, payload, editor_id, client_info=_client_info(request)
        )
    except ValueError as exc:
        code = 404 if "no encontrado" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/{documento_id}/versiones", response_model=VersionDocumentoRead, status_code=201)
def crear_version(
    documento_id: int,
    request: Request,
    archivo: Annotated[UploadFile, File()],
    subido_por_id: Annotated[int, Form(gt=0)],
    comentario_cambio: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    try:
        return documento_service.crear_version_desde_upload(
            db, documento_id, archivo, subido_por_id,
            comentario_cambio=comentario_cambio,
            client_info=_client_info(request),
        )
    except ValueError as exc:
        code = 404 if "no encontrado" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/{documento_id}/versiones", response_model=list[VersionDocumentoListRead])
def listar_versiones(documento_id: int, db: Session = Depends(get_db)):
    if db.get(Documento, documento_id) is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return documento_service.listar_versiones(db, documento_id)


@router.get("/{documento_id}/versiones/{version_id}/descargar", response_class=FileResponse)
def descargar_version(documento_id: int, version_id: int, db: Session = Depends(get_db)):
    version = db.scalar(select(VersionDocumento).where(
        VersionDocumento.id == version_id,
        VersionDocumento.documento_id == documento_id,
    ))
    if version is None:
        raise HTTPException(status_code=404, detail="Version no encontrada")
    try:
        path = storage_service.get_absolute_path(version.storage_key)
        if not path.is_file():
            raise FileNotFoundError
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail="Archivo no encontrado") from None
    filename = Path(version.nombre_original.replace("\\", "/")).name or path.name
    return FileResponse(path, filename=filename, media_type=version.mime_type or "application/octet-stream")


@router.get("/{documento_id}/historial", response_model=list[EventoAuditoriaRead])
def historial_documento(documento_id: int, db: Session = Depends(get_db)):
    if db.get(Documento, documento_id) is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return list(db.scalars(select(EventoAuditoria).where(
        EventoAuditoria.entidad_tipo == "DOCUMENTO",
        EventoAuditoria.entidad_id == str(documento_id),
    ).order_by(EventoAuditoria.ocurrido_en, EventoAuditoria.id)).all())
