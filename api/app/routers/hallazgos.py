from typing import Annotated
from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session
from app.api.dependencies import current_user
from app.db.session import get_db
from app.models.entities import Usuario
from app.schemas.hallazgo import (HallazgoCreate, HallazgoUpdate, HallazgoTransition,
    HallazgoLink, HallazgoRead, HallazgoFilters, PageInput, MAX_ID)
from app.schemas.evidencia import EvidenciaListRead
from app.schemas.auditoria import AuditEventRead
from app.services import hallazgo_service as service

router = APIRouter(prefix='/hallazgos', tags=['hallazgos'])
FindingId = Annotated[int, Path(gt=0, le=MAX_ID)]


@router.get('', response_model=list[HallazgoRead])
def listado(response: Response, filters: Annotated[HallazgoFilters, Query()],
            user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    rows, total = service.list_findings(db, user, filters)
    response.headers['X-Total-Count'] = str(total)
    return rows


@router.post('', response_model=HallazgoRead, status_code=201)
def crear(payload: HallazgoCreate, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.create(db, user, payload)


@router.get('/{finding_id}', response_model=HallazgoRead)
def detalle(finding_id: FindingId, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.detail(db, user, finding_id)


@router.patch('/{finding_id}', response_model=HallazgoRead)
def editar(finding_id: FindingId, payload: HallazgoUpdate, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.edit(db, user, finding_id, payload)


@router.post('/{finding_id}/estado', response_model=HallazgoRead)
def estado(finding_id: FindingId, payload: HallazgoTransition, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.transition(db, user, finding_id, payload)


@router.post('/{finding_id}/evidencias', response_model=HallazgoRead, status_code=201)
def asociar(finding_id: FindingId, payload: HallazgoLink, user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return service.associate(db, user, finding_id, payload)


@router.get('/{finding_id}/evidencias', response_model=list[EvidenciaListRead])
def evidencias(finding_id: FindingId, response: Response, page: Annotated[PageInput, Query()],
               user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    rows, total = service.evidence_list(db, user, finding_id, page)
    response.headers['X-Total-Count'] = str(total)
    return rows


@router.get('/{finding_id}/historial', response_model=list[AuditEventRead])
def historial(finding_id: FindingId, response: Response, page: Annotated[PageInput, Query()],
              user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    rows, total = service.history(db, user, finding_id, page)
    response.headers['X-Total-Count'] = str(total)
    return rows
