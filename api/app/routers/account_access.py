from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import current_user
from app.db.session import get_db
from app.models.entities import Usuario
from app.models.account_access import AccessRequest
from app.schemas.account_access import (EmailRequest, AccessRequestCreate, ApproveRequest, RejectRequest,
    PasswordConfirm, AccessRequestRead, ResendRequest)
from app.services import account_actions as actions
from app.services.auth_mail import validate_mail_config

class PrivateActionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, 'Solicitud de acceso o recuperación invalida') from None
            except HTTPException:
                raise
            except Exception:
                # Prevent server traceback logging of SQL/driver/credential inputs.
                raise HTTPException(503, 'No se pudo completar la operación. Intenta más tarde.') from None
        return sanitized


router = APIRouter(tags=['acceso y recuperación'], route_class=PrivateActionRoute)


def administrator(user: Usuario = Depends(current_user)):
    if user.rol != 'ADMIN':
        raise HTTPException(403, 'Operacion no permitida')
    return user


@router.post('/auth/access-requests', status_code=202)
def request_access(payload: AccessRequestCreate, db: Session = Depends(get_db)):
    actions.submit_access(db, payload)
    return {'message': actions.ACCESS_MESSAGE}


@router.post('/auth/password-reset/request', status_code=202)
def request_reset(payload: EmailRequest, db: Session = Depends(get_db)):
    actions.request_reset(db, payload.correo)
    return {'message': actions.RESET_MESSAGE}


@router.post('/auth/password-reset/confirm')
def confirm_reset(payload: PasswordConfirm, db: Session = Depends(get_db)):
    actions.confirm_password(db, 'PASSWORD_RESET', payload.token.get_secret_value(), payload.password.get_secret_value())
    return {'message': 'Contraseña actualizada. Por seguridad cerramos tus sesiones anteriores. Inicia sesión con tu nueva contraseña.'}


@router.post('/auth/initial-password/confirm')
def confirm_initial(payload: PasswordConfirm, db: Session = Depends(get_db)):
    actions.confirm_password(db, 'INITIAL_PASSWORD', payload.token.get_secret_value(), payload.password.get_secret_value())
    return {'message': 'Contraseña establecida. Ya puedes iniciar sesión.'}


@router.get('/access-requests', response_model=list[AccessRequestRead])
def list_requests(status: Literal['PENDING','APPROVED','REJECTED','FULFILLED'] = 'PENDING',
                  limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                  admin: Usuario = Depends(administrator), db: Session = Depends(get_db)):
    return db.scalars(select(AccessRequest).where(AccessRequest.status == status)
        .order_by(AccessRequest.created_at, AccessRequest.id).offset(offset).limit(limit)).all()


@router.get('/access-requests/{request_id}', response_model=AccessRequestRead)
def get_request(request_id: int, admin: Usuario = Depends(administrator), db: Session = Depends(get_db)):
    row = db.get(AccessRequest, request_id)
    if row is None:
        raise HTTPException(404, 'Recurso no encontrado')
    return row


@router.post('/access-requests/{request_id}/approve', response_model=AccessRequestRead)
def approve(request_id: int, payload: ApproveRequest, admin: Usuario = Depends(administrator), db: Session = Depends(get_db)):
    validate_mail_config()
    return actions.resolve_access(db, admin.id, request_id, role=payload.rol)


@router.post('/access-requests/{request_id}/reject', response_model=AccessRequestRead)
def reject(request_id: int, payload: RejectRequest, admin: Usuario = Depends(administrator), db: Session = Depends(get_db)):
    return actions.resolve_access(db, admin.id, request_id, reason=payload.motivo)


@router.post('/access-requests/{request_id}/resend', response_model=AccessRequestRead)
def resend(request_id: int, payload: ResendRequest, admin: Usuario = Depends(administrator), db: Session = Depends(get_db)):
    validate_mail_config()
    return actions.resend_initial(db, admin.id, request_id)
