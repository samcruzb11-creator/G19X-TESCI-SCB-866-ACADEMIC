from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import Auditoria, Usuario
from app.schemas.auditoria import AuditoriaCreate, AuditoriaRead
from app.services.documento_service import _log_evento

router = APIRouter(prefix="/auditorias", tags=["auditorias"])


@router.get("", response_model=list[AuditoriaRead])
def listar_auditorias(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Auditoria).order_by(Auditoria.id).limit(limit).offset(offset)).all())


@router.post("", response_model=AuditoriaRead, status_code=201)
def crear_auditoria(payload: AuditoriaCreate, db: Session = Depends(get_db)):
    usuarios = {}
    for user_id in {payload.responsable_id, payload.created_by_id}:
        usuarios[user_id] = db.get(Usuario, user_id)
        if usuarios[user_id] is None:
            raise HTTPException(status_code=404, detail="Responsable o creador no encontrado")
    auditoria = Auditoria(**payload.model_dump(), estado="PLANNED")
    try:
        db.add(auditoria)
        db.flush()
        _log_evento(
            db,
            actor=usuarios[payload.created_by_id],
            accion="CREACION_AUDITORIA",
            entidad_tipo="AUDITORIA",
            entidad_id=auditoria.id,
            correlation_id=str(uuid4()),
            datos_nuevos={
                **payload.model_dump(mode="json"),
                "auditoria_id": auditoria.id,
                "estado": auditoria.estado,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        code = exc.orig.args[0] if exc.orig.args else None
        if code == 1062:
            raise HTTPException(status_code=409, detail="El codigo de auditoria ya existe") from None
        raise HTTPException(status_code=422, detail="La auditoria incumple una restriccion de datos") from None
    except Exception:
        db.rollback()
        raise
    db.refresh(auditoria)
    return auditoria
