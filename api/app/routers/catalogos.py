from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import current_user
from app.models.entities import Usuario
from app.services import authorization_service as authz
from app.models.entities import Area, Usuario
from app.schemas.catalogo import AreaRead, UsuarioRead

router = APIRouter(tags=["catalogos"])


@router.get("/areas", response_model=list[AreaRead])
def listar_areas(user: Usuario = Depends(current_user),
    db: Session = Depends(get_db)):
    authz.require_permission(user, 'areas.read')
    return db.execute(select(Area.id, Area.nombre, Area.codigo, Area.activa).order_by(Area.nombre, Area.id)).mappings().all()


@router.get("/usuarios", response_model=list[UsuarioRead])
def listar_usuarios(elegibles_auditoria: bool = False, user: Usuario = Depends(current_user),
    db: Session = Depends(get_db)):
    authz.require_permission(user, 'usuarios.read')
    stmt = select(Usuario.id, Usuario.nombre, Usuario.activo)
    stmt = stmt.where(authz.usuarios_scope(user))
    if elegibles_auditoria:
        stmt = stmt.where(authz.eligible_users_scope())
    return db.execute(stmt.order_by(Usuario.nombre, Usuario.id)).mappings().all()
