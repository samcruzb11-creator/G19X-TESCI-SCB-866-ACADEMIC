"""Authenticated GET-only analysis, with request snapshot and fresh scope barrier."""
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.api.dependencies import current_user
from app.db.session import get_db
from app.models.entities import Usuario
from app.schemas.dashboard import DecimalId
from app.schemas.analisis import (AnalysisFilters, AnalysisContext, AnalysisSummary,
    DetectionPage, ResourceAnalysis)
from app.services import analisis_service as service

router = APIRouter(prefix='/analisis', tags=['analisis'])


def evaluate(db, user, filters, response, operation, version_id=None):
    response.headers['Cache-Control'] = 'no-store'
    with db.no_autoflush:
        service.validate(db, user, filters, version_id)
        signature = service.visibility_digest(db, user)
        result = operation(datetime.now(timezone.utc))
        service.fresh_authorization(db, user, signature)
        return result


@router.get('/resumen', response_model=AnalysisSummary)
def resumen(response: Response, context: Annotated[AnalysisContext, Query()],
            user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return evaluate(db, user, context, response, lambda stamp: service.summary(db, user, context, stamp))


@router.get('/anomalias', response_model=DetectionPage)
def anomalias(response: Response, filters: Annotated[AnalysisFilters, Query()],
              user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return evaluate(db, user, filters, response, lambda stamp: service.page(db, user, filters, stamp))


@router.get('/documentos/{resource_id}', response_model=ResourceAnalysis)
def documento(resource_id: DecimalId, response: Response, filters: Annotated[AnalysisFilters, Query()],
              user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    if filters.documento_id is not None and filters.documento_id != resource_id:
        from fastapi import HTTPException
        raise HTTPException(404, 'Recurso no encontrado')
    filters = filters.model_copy(update={'documento_id': resource_id})
    return evaluate(db, user, filters, response, lambda stamp: service.detail(db, user, filters, stamp))


@router.get('/versiones/{resource_id}', response_model=ResourceAnalysis)
def version(resource_id: DecimalId, response: Response, filters: Annotated[AnalysisFilters, Query()],
            user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    return evaluate(db, user, filters, response,
        lambda stamp: service.detail(db, user, filters, stamp, resource_id), resource_id)
