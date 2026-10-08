"""Endpoints REST para documentos y sus versiones."""

from typing import Annotated
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path as PathParam, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload, raiseload

from app.db.session import get_db
from app.api.dependencies import current_user
from app.models.entities import Usuario
from app.services import authorization_service as authz
from app.models.entities import Documento, EventoAuditoria, VersionDocumento
from app.schemas.documento import (
    MAX_ID,
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
    user: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
    creador_id: Annotated[int | None, Query(deprecated=True)] = None,
):
    authz.authorize_document_create(user, payload)
    try:
        return documento_service.crear_documento(db, payload, user.id, client_info=_client_info(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Conflicto de integridad; recargue antes de continuar') from None


@router.get("", response_model=list[DocumentoListRead])
def listar_documentos(
    tipo: str | None = None,
    estado: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    user: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    authz.require_permission(user, 'documento.read')
    stmt = select(Documento).where(authz.documento_scope(user)).options(joinedload(Documento.version_vigente.and_(authz.version_scope(user))))
    if tipo:
        stmt = stmt.where(Documento.tipo == tipo)
    if estado:
        stmt = stmt.where(Documento.estado == estado)
    stmt = stmt.order_by(Documento.id).offset(offset).limit(limit).execution_options(populate_existing=True)
    rows = list(db.scalars(stmt).all())
    return [_document_response(row, user, DocumentoListRead) for row in rows]


@router.get("/{documento_id}", response_model=DocumentoDetalleRead, response_model_exclude_unset=True)
def obtener_documento(
    documento_id: Annotated[int, PathParam(gt=0, le=MAX_ID)],
    incluir_versiones: bool = False,
    user: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    authz.require_permission(user, 'documento.read')
    stmt = select(Documento).where(Documento.id == documento_id, authz.documento_scope(user)).options(
        joinedload(Documento.version_vigente.and_(authz.version_scope(user)))
    )
    if incluir_versiones:
        stmt = stmt.options(selectinload(Documento.versiones.and_(authz.version_scope(user))))
    else:
        stmt = stmt.options(raiseload(Documento.versiones))
    documento = db.scalar(stmt.execution_options(populate_existing=True))
    if documento is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    data = _document_response(documento, user, DocumentoRead).model_dump()
    if incluir_versiones:
        data["versiones"] = [VersionDocumentoRead.model_validate(v) for v in documento.versiones]
    return DocumentoDetalleRead(**data)


@router.patch("/{documento_id}", response_model=DocumentoRead)
def actualizar_documento(
    documento_id: Annotated[int, PathParam(gt=0, le=MAX_ID)],
    payload: DocumentoUpdate,
    request: Request,
    user: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
    editor_id: Annotated[int | None, Query(deprecated=True)] = None,
):
    document = authz.resource(db, user, Documento, documento_id, 'documento.update', authz.documento_scope)
    authz.authorize_document_update(user, document, payload)
    try:
        return documento_service.actualizar_cabecera(
            db, documento_id, payload, user.id, client_info=_client_info(request)
        )
    except ValueError as exc:
        code = 404 if "no encontrado" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Conflicto de integridad; recargue antes de continuar') from None


@router.post("/{documento_id}/versiones", response_model=VersionDocumentoRead, status_code=201)
def crear_version(
    documento_id: Annotated[int, PathParam(gt=0, le=MAX_ID)],
    request: Request,
    archivo: Annotated[UploadFile, File()],
    comentario_cambio: Annotated[str | None, Form()] = None,
    user: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
    subido_por_id: Annotated[int | None, Form(deprecated=True)] = None,
):
    authz.require_permission(user, 'version.create')
    try:
        return documento_service.crear_version_desde_upload(
            db, documento_id, archivo, user.id,
            comentario_cambio=comentario_cambio,
            client_info=_client_info(request),
        )
    except ValueError as exc:
        code = 404 if "no encontrado" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/{documento_id}/versiones", response_model=list[VersionDocumentoListRead])
def listar_versiones(documento_id: Annotated[int, PathParam(gt=0, le=MAX_ID)], user: Usuario = Depends(current_user),
    db: Session = Depends(get_db)):
    authz.resource(db, user, Documento, documento_id, 'version.read', authz.documento_scope)
    return list(db.scalars(select(VersionDocumento).where(VersionDocumento.documento_id == documento_id, authz.version_scope(user)).order_by(VersionDocumento.numero_version)).all())


@router.get("/{documento_id}/versiones/{version_id}/descargar", response_class=FileResponse)
def descargar_version(documento_id: Annotated[int, PathParam(gt=0, le=MAX_ID)], version_id: Annotated[int, PathParam(gt=0, le=MAX_ID)], user: Usuario = Depends(current_user),
    db: Session = Depends(get_db)):
    authz.require_permission(user, 'version.read')
    version = db.scalar(select(VersionDocumento).where(
        authz.version_scope(user),
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
def historial_documento(documento_id: Annotated[int, PathParam(gt=0, le=MAX_ID)], user: Usuario = Depends(current_user),
    db: Session = Depends(get_db)):
    authz.require_permission(user, 'historial.read')
    if db.get(Documento, documento_id) is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return list(db.scalars(select(EventoAuditoria).where(
        EventoAuditoria.entidad_tipo == "DOCUMENTO",
        EventoAuditoria.entidad_id == str(documento_id),
    ).order_by(EventoAuditoria.ocurrido_en, EventoAuditoria.id)).all())


def _document_response(document, user, schema):
    data = schema.model_validate(document)
    return authz.sanitize_document_metadata(user, data)
