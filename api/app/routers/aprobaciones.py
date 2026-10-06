from typing import Annotated
from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session
from pydantic import BeforeValidator
from app.api.dependencies import current_user
from app.db.session import get_db
from app.models.entities import Usuario
from app.schemas.aprobacion import (RondaCreate, RondaCommand, DecisionCommand, RondaRead,
    RondaFilters, ApprovalPage, ResourceFilters, ApproverFilters, DecisionRead, ApprovalResource, path_integer)
from app.schemas.auditoria import AuditReference, AuditEventRead
from app.schemas.hallazgo import MAX_ID
from app.services import aprobacion_service as service

router = APIRouter(prefix='/aprobaciones', tags=['aprobaciones'])
RoundId = Annotated[int, Path(gt=0, le=MAX_ID), BeforeValidator(path_integer)]


def counted(response, result):
    rows, total = result
    response.headers['X-Total-Count'] = str(total)
    return rows


@router.get('', response_model=list[RondaRead])
def listado(response: Response, filters: Annotated[RondaFilters, Query()],
            user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return counted(response, service.list_rounds(db, user, filters))


@router.post('', response_model=RondaRead, status_code=201)
def crear(payload: RondaCreate, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.create(db, user, payload)


@router.get('/recursos', response_model=list[ApprovalResource])
def recursos(response: Response, filters: Annotated[ResourceFilters, Query()],
             user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return counted(response, service.resources(db, user, filters))


@router.get('/aprobadores', response_model=list[AuditReference])
def aprobadores(response: Response, filters: Annotated[ApproverFilters, Query()],
                user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return counted(response, service.approvers(db, user, filters))


@router.get('/{round_id}', response_model=RondaRead)
def detalle(round_id: RoundId, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.detail(db, user, round_id)


@router.post('/{round_id}/iniciar', response_model=RondaRead)
def iniciar(round_id: RoundId, payload: RondaCommand, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.command(db, user, round_id, payload, 'iniciar')


@router.post('/{round_id}/cancelar', response_model=RondaRead)
def cancelar(round_id: RoundId, payload: RondaCommand, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.command(db, user, round_id, payload, 'cancelar')


@router.post('/{round_id}/finalizar', response_model=RondaRead)
def finalizar(round_id: RoundId, payload: RondaCommand, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.command(db, user, round_id, payload, 'finalizar')


@router.post('/{round_id}/decision', response_model=RondaRead)
def decidir(round_id: RoundId, payload: DecisionCommand, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.decide(db, user, round_id, payload)


@router.get('/{round_id}/decisiones', response_model=list[DecisionRead])
def decisiones(round_id: RoundId, response: Response, page: Annotated[ApprovalPage, Query()],
               user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return counted(response, service.decisions(db, user, round_id, page))


@router.get('/{round_id}/historial', response_model=list[AuditEventRead])
def historial(round_id: RoundId, response: Response, page: Annotated[ApprovalPage, Query()],
              user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return counted(response, service.history(db, user, round_id, page))
