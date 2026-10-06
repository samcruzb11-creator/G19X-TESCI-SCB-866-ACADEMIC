from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, Path
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import current_user
from app.models.entities import Usuario
from app.schemas.auditoria import (AuditoriaCreate, AuditoriaRead, AuditoriaUpdate,
                                  AuditoriaTransition, AuditoriaFilters, AuditEventRead)
from app.services import auditoria_service as service

router = APIRouter(prefix='/auditorias', tags=['auditorias'])
AuditId = Annotated[int, Path(gt=0)]


@router.get('', response_model=list[AuditoriaRead])
def listar_auditorias(response: Response, filters: Annotated[AuditoriaFilters, Query()],
                     user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    rows, total = service.list_audits(db, user, filters)
    response.headers['X-Total-Count'] = str(total)
    return rows


@router.post('', response_model=AuditoriaRead, status_code=201)
def crear_auditoria(payload: AuditoriaCreate, user: Usuario = Depends(current_user),
                    db: Session = Depends(get_db)):
    return service.create(db, user, payload)


@router.get('/{audit_id}', response_model=AuditoriaRead)
def detalle(audit_id: AuditId, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.read_rows(db, [service.resource(db, user, audit_id)])[0]


@router.patch('/{audit_id}', response_model=AuditoriaRead)
def editar(audit_id: AuditId, payload: AuditoriaUpdate, user: Usuario = Depends(current_user),
           db: Session = Depends(get_db)):
    return service.edit(db, user, audit_id, payload)


@router.post('/{audit_id}/estado', response_model=AuditoriaRead)
def cambiar_estado(audit_id: AuditId, payload: AuditoriaTransition,
                   user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.transition(db, user, audit_id, payload)


@router.get('/{audit_id}/historial', response_model=list[AuditEventRead])
def historial(audit_id: AuditId, limit: Annotated[int, Query(ge=1, le=100)] = 20,
              offset: Annotated[int, Query(ge=0, le=10000)] = 0,
              user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.history(db, user, audit_id, limit, offset)
