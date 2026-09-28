from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import Area, Usuario
from app.schemas.catalogo import AreaRead, UsuarioRead

router = APIRouter(tags=["catalogos"])


@router.get("/areas", response_model=list[AreaRead])
def listar_areas(db: Session = Depends(get_db)):
    return db.execute(select(Area.id, Area.nombre, Area.codigo, Area.activa).order_by(Area.nombre, Area.id)).mappings().all()


@router.get("/usuarios", response_model=list[UsuarioRead])
def listar_usuarios(db: Session = Depends(get_db)):
    return db.execute(select(Usuario.id, Usuario.nombre, Usuario.activo).order_by(Usuario.nombre, Usuario.id)).mappings().all()
