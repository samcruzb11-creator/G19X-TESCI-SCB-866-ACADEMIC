from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_token, validate_jwt_config
from app.db.session import get_db
from app.models.auth import AuthSession
from app.models.entities import Usuario
from app.services.authorization_service import ROLES

bearer = HTTPBearer(auto_error=False)


def authentication_ready() -> None:
    try:
        validate_jwt_config()
    except ValueError:
        raise HTTPException(503, "Autenticacion no disponible: configuracion JWT insegura") from None


def unauthorized() -> HTTPException:
    return HTTPException(401, "Credenciales invalidas o sesion no vigente", headers={"WWW-Authenticate": "Bearer"})


@dataclass(frozen=True)
class AuthContext:
    user: Usuario
    session: AuthSession


def current_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    ready: None = Depends(authentication_ready),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    try:
        claims = decode_token(credentials.credentials)
    except (JWTError, ValueError, TypeError):
        raise unauthorized() from None
    session = db.get(AuthSession, claims["sid"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if (session is None or session.usuario_id != int(claims["sub"])
            or session.revoked_at is not None or session.expires_at <= now
            or session.created_at != datetime.fromtimestamp(claims["iat"], timezone.utc).replace(tzinfo=None)
            or session.expires_at != datetime.fromtimestamp(claims["exp"], timezone.utc).replace(tzinfo=None)):
        raise unauthorized()
    user = db.get(Usuario, session.usuario_id)
    if user is None or not user.activo or user.rol not in ROLES:
        raise unauthorized()
    return AuthContext(user, session)


def current_user(auth: AuthContext = Depends(current_auth)) -> Usuario:
    return auth.user


def current_session(auth: AuthContext = Depends(current_auth)) -> AuthSession:
    return auth.session
