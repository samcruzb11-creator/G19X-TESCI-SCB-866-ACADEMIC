"""Endpoints REST para evidencias físicas y lógicas."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.evidencia import EvidenciaCreate, EvidenciaRead
from app.services.evidencia_service import evidencia_service
from app.services.storage_service import storage_service

router = APIRouter(prefix="/evidencias", tags=["evidencias"])


def _client_info(request: Request) -> dict[str, str | None]:
    return {"ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")}


@router.post("/archivo", response_model=EvidenciaRead, status_code=201)
def registrar_archivo(
    request: Request,
    archivo: Annotated[UploadFile, File()],
    auditoria_id: Annotated[int, Form(gt=0)],
    titulo: Annotated[str, Form(min_length=3, max_length=200)],
    registrada_por_id: Annotated[int, Form(gt=0)],
    descripcion: Annotated[str | None, Form()] = None,
    documento_id: Annotated[int | None, Form(gt=0)] = None,
    version_documento_id: Annotated[int | None, Form(gt=0)] = None,
    db: Session = Depends(get_db),
):
    try:
        return evidencia_service.registrar_evidencia_desde_upload(
            db, auditoria_id, titulo, registrada_por_id, archivo, descripcion,
            documento_id, version_documento_id, client_info=_client_info(request),
        )
    except ValueError as exc:
        code = 404 if "no encontrada" in str(exc).lower() or "no encontrado" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/logica", response_model=EvidenciaRead, status_code=201)
def registrar_logica(
    payload: EvidenciaCreate,
    request: Request,
    registrada_por_id: Annotated[int, Query(gt=0)],
    db: Session = Depends(get_db),
):
    try:
        return evidencia_service.registrar_evidencia_logica(
            db, payload, registrada_por_id, client_info=_client_info(request)
        )
    except ValueError as exc:
        code = 404 if "no encontrada" in str(exc).lower() or "no encontrado" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/{evidencia_id}", response_model=EvidenciaRead)
def obtener_evidencia(evidencia_id: int, db: Session = Depends(get_db)):
    evidencia = evidencia_service.obtener_evidencia(db, evidencia_id)
    if evidencia is None:
        raise HTTPException(status_code=404, detail="Evidencia no encontrada")
    return evidencia


@router.get("/{evidencia_id}/descargar")
def descargar_evidencia(evidencia_id: int, db: Session = Depends(get_db)):
    evidencia = evidencia_service.obtener_evidencia(db, evidencia_id)
    if evidencia is None:
        raise HTTPException(status_code=404, detail="Evidencia no encontrada")
    if evidencia.tipo != "FILE" or not evidencia.storage_key:
        raise HTTPException(status_code=400, detail="La evidencia no contiene un archivo descargable")
    try:
        path = storage_service.get_absolute_path(evidencia.storage_key)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Ruta de almacenamiento inválida") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="El archivo asociado no está disponible")
    return FileResponse(path, media_type=evidencia.mime_type or "application/octet-stream",
                        filename=evidencia.nombre_original or Path(path).name)
