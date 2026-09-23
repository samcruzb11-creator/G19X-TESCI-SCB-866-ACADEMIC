from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.app_name, debug=settings.debug)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["estado"])
def inicio() -> dict[str, str]:
    return {
        "mensaje": "Sistema de Trazabilidad Documental",
        "estado": "API funcionando correctamente",
    }
