from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.routers.documentos import router as documentos_router
from app.routers.evidencias import router as evidencias_router

app = FastAPI(title=settings.app_name, debug=settings.debug)
app.include_router(documentos_router, prefix=settings.api_v1_prefix)
app.include_router(evidencias_router, prefix=settings.api_v1_prefix)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})


@app.get("/", tags=["estado"])
def inicio() -> dict[str, str]:
    return {
        "mensaje": "Sistema de Trazabilidad Documental",
        "estado": "API funcionando correctamente",
    }
