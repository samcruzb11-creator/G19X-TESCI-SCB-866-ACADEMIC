import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.dependencies import AuthContext, authentication_ready, current_auth, unauthorized
from app.core.security import ACCESS_SECONDS, DUMMY_HASH, issue_token, normalize_email, verify_password
from app.db.session import get_db
from app.models.auth import AuthSession
from app.models.entities import Usuario
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["autenticacion"])


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(authentication_ready)])
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    user = db.scalar(select(Usuario).where(Usuario.correo_normalizado == normalize_email(payload.correo)))
    valid = verify_password(payload.password.get_secret_value(), user.password_hash if user else DUMMY_HASH)
    if user is None or not valid or not user.activo:
        raise unauthorized()
    verified_hash = user.password_hash
    try:
        # Argon2 runs before taking the lock. MySQL's locking read sees current
        # committed state even under REPEATABLE READ; populate_existing refreshes
        # the identity map. Every subsequent failure releases the lock via rollback.
        user = db.scalar(select(Usuario).where(Usuario.id == user.id).with_for_update()
                         .execution_options(populate_existing=True))
        if user is None or not user.activo or user.password_hash != verified_hash:
            raise unauthorized()
        issued = int(datetime.now(timezone.utc).timestamp())
        sid = secrets.token_hex(32)
        token = issue_token(user.id, sid, issued)
        session = AuthSession(sid=sid, usuario_id=user.id,
                              created_at=datetime.fromtimestamp(issued, timezone.utc).replace(tzinfo=None),
                              expires_at=datetime.fromtimestamp(issued + ACCESS_SECONDS, timezone.utc).replace(tzinfo=None))
        db.add(session)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return TokenResponse(access_token=token)


@router.get("/me", response_model=CurrentUserResponse)
def me(response: Response, auth: AuthContext = Depends(current_auth)):
    response.headers["Cache-Control"] = "no-store"
    user = auth.user
    return CurrentUserResponse(id=user.id, nombre=user.nombre, correo=user.correo, rol=user.rol)


@router.post("/logout", status_code=204)
def logout(auth: AuthContext = Depends(current_auth), db: Session = Depends(get_db)):
    # Conditional update makes concurrent logouts harmless; no other SID is affected.
    try:
        db.execute(update(AuthSession).where(AuthSession.sid == auth.session.sid,
                                            AuthSession.revoked_at.is_(None)).values(
            revoked_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
