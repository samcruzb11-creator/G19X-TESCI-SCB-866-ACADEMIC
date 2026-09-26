"""Endpoints REST para documentos y sus versiones."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.session import get_db
from app.models.entities import Documento
from app.schemas.documento import (
    DocumentoConVersionesRead,
    DocumentoCreate,
    DocumentoRead,
    DocumentoUpdate,
    VersionDocumentoRead,
)
from app.services.documento_service import documento_service

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


@router.get("", response_model=list[DocumentoRead])
def listar_documentos(
    tipo: str | None = None,
    estado: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    stmt = select(Documento)
    if tipo:
        stmt = stmt.where(Documento.tipo == tipo)
    if estado:
        stmt = stmt.where(Documento.estado == estado)
    stmt = stmt.order_by(Documento.id).offset(offset).limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/{documento_id}", response_model=DocumentoRead | DocumentoConVersionesRead)
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
    documento = db.scalar(stmt)
    if documento is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return documento


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


@router.get("/{documento_id}/versiones", response_model=list[VersionDocumentoRead])
def listar_versiones(documento_id: int, db: Session = Depends(get_db)):
    if db.get(Documento, documento_id) is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return documento_service.listar_versiones(db, documento_id)
