"""Dashboard GETs reuse authenticated identity and its request transaction."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.db.session import get_db
from app.models.entities import Usuario
from app.schemas.dashboard import (DashboardContext, DashboardPage, AlertFilters,
    Indicators, AlertPage, ActivityPage, Summary)
from app.services import dashboard_service as service

router = APIRouter(prefix='/dashboard', tags=['dashboard'])


def prepare(db, user, context, response):
    response.headers['Cache-Control'] = 'no-store'
    service.validate_context(db, user, context)


@router.get('/resumen', response_model=Summary)
def resumen(response: Response, page: Annotated[DashboardPage, Query()],
            user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    prepare(db, user, page, response)
    return service.summary(db, user, page)


@router.get('/indicadores', response_model=Indicators)
def indicadores(response: Response, context: Annotated[DashboardContext, Query()],
                user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    prepare(db, user, context, response)
    return service.indicators(db, user, context)


@router.get('/alertas', response_model=AlertPage)
def alertas(response: Response, filters: Annotated[AlertFilters, Query()],
            user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    prepare(db, user, filters, response)
    return service.alerts(db, user, filters)


@router.get('/actividad', response_model=ActivityPage)
def actividad(response: Response, page: Annotated[DashboardPage, Query()],
              user: Usuario = Depends(current_user), db: Session = Depends(get_db)):
    prepare(db, user, page, response)
    return service.activity(db, user, page)
