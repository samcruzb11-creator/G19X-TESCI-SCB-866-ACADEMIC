import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.services.file_transaction import CommitOutcomeUnknown
from app.routers.documentos import router as documentos_router
from app.routers.evidencias import router as evidencias_router
from app.routers.catalogos import router as catalogos_router
from app.routers.auditorias import router as auditorias_router
from app.routers.auth import router as auth_router
from app.core.security import validate_jwt_config
from app.services.login_protection import AuthResponseMiddleware


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Imports, Alembic and credential tooling remain usable without a JWT secret;
    # serving HTTP requires valid cryptographic configuration before startup.
    validate_jwt_config()
    yield

# Filesystem/driver failures must use the sanitized handler even in local mode.
# Starlette's HTTP debug mode otherwise bypasses it and returns tracebacks.
app = FastAPI(title=settings.app_name, debug=False, lifespan=lifespan)
logger = logging.getLogger(__name__)


def log_error_kind(exc: Exception) -> None:
    # Local diagnostics only: never log exception text, URLs or traceback.
    if settings.debug:
        logger.warning("HTTP operation failed (%s)", type(exc).__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost", "http://127.0.0.1",
        "http://localhost:80", "http://127.0.0.1:80",
        "http://localhost:8080", "http://127.0.0.1:8080",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Disposition"],
)
app.include_router(documentos_router, prefix=settings.api_v1_prefix)
app.include_router(evidencias_router, prefix=settings.api_v1_prefix)
app.include_router(catalogos_router, prefix=settings.api_v1_prefix)
app.include_router(auditorias_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.add_middleware(AuthResponseMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if request.url.path.startswith(settings.api_v1_prefix + "/auth/"):
        # Pydantic errors can contain raw input, including passwords.
        return JSONResponse(status_code=422, content={"detail": "Solicitud de autenticacion invalida"})
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log_error_kind(exc)
    # ServerErrorMiddleware is outside user middleware, including no-store.
    headers = {"Cache-Control": "no-store"} if request.url.path.startswith(settings.api_v1_prefix + "/auth/") else None
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"}, headers=headers)


@app.exception_handler(CommitOutcomeUnknown)
async def commit_outcome_unknown_handler(request: Request, exc: CommitOutcomeUnknown) -> JSONResponse:
    log_error_kind(exc)
    return JSONResponse(status_code=503, content={
        "detail": "No fue posible confirmar el estado de la transacción. Verifique el expediente antes de reintentar.",
        "code": "COMMIT_OUTCOME_UNKNOWN",
    })


@app.get("/", tags=["estado"])
def inicio() -> dict[str, str]:
    return {
        "mensaje": "Sistema de Trazabilidad Documental",
        "estado": "API funcionando correctamente",
    }
