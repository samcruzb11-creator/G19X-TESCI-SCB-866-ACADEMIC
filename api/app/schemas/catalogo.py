from pydantic import BaseModel, ConfigDict


class AreaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    codigo: str
    activa: bool


class UsuarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    activo: bool
