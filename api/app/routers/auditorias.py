from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import current_user
from app.services import authorization_service as authz
from app.models.entities import Auditoria, Usuario
from app.schemas.auditoria import AuditoriaCreate, AuditoriaRead
from app.services.documento_service import _log_evento

router = APIRouter(prefix="/auditorias", tags=["auditorias"])


@router.get("", response_model=list[AuditoriaRead])
def listar_auditorias(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    user: Usuario = Depends(current_user),
    db: Session = Depends(get_db),
):
    authz.require_permission(user, 'auditoria.read')
    return list(db.scalars(select(Auditoria).where(authz.auditoria_scope(user)).order_by(Auditoria.id).limit(limit).offset(offset)).all())


@router.post("", response_model=AuditoriaRead, status_code=201)
def crear_auditoria(payload: AuditoriaCreate, user: Usuario = Depends(current_user),
    db: Session = Depends(get_db)):
    authz.authorize_audit_create(db, user, payload)
    data = payload.model_dump(exclude={'created_by_id'})
    data['created_by_id'] = user.id
    auditoria = Auditoria(**data, estado='PLANNED')
    try:
        db.add(auditoria)
        db.flush()
        _log_evento(
            db,
            actor=user,
            accion="CREACION_AUDITORIA",
            entidad_tipo="AUDITORIA",
            entidad_id=auditoria.id,
            correlation_id=str(uuid4()),
            datos_nuevos={
                **payload.model_dump(mode="json", exclude={"created_by_id"}),
                "created_by_id": user.id,
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
