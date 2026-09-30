"""Password and JWT primitives. No credentials are logged."""
import re
from datetime import datetime, timezone

from jose import JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings

password_hasher = PasswordHash((Argon2Hasher(),))
DUMMY_HASH = password_hasher.hash("dummy-verification-only")
ACCESS_SECONDS = 15 * 60


def normalize_email(value: str) -> str:
    return value.strip().lower()


def validate_jwt_config() -> None:
    secret = settings.jwt_secret_key
    minimum = {"HS256": 32, "HS384": 48, "HS512": 64}.get(settings.jwt_algorithm)
    if (minimum is None or len(secret.encode("utf-8")) < minimum
            or len(set(secret)) < 16
            or any(marker in secret.lower() for marker in ("replace-with", "changeme", "change-me", "default", "example"))):
        raise ValueError("Configuracion JWT insegura: use un secreto aleatorio y HS256/HS384/HS512.")


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("La contraseña debe tener entre 12 y 1024 caracteres.")
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(password, hashed)
    except Exception:
        # Legacy/invalid hashes cannot authenticate; still perform Argon2 work.
        password_hasher.verify(password, DUMMY_HASH)
        return False


def issue_token(user_id: int, sid: str, issued: int) -> str:
    validate_jwt_config()
    return jwt.encode({"sub": str(user_id), "sid": sid, "iat": issued,
                       "exp": issued + ACCESS_SECONDS}, settings.jwt_secret_key,
                      algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    validate_jwt_config()
    claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm],
                        options={"require_sub": True, "require_iat": True, "require_exp": True})
    now = int(datetime.now(timezone.utc).timestamp())
    if (set(claims) != {"sub", "sid", "iat", "exp"}
            or not isinstance(claims["sub"], str)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", claims["sub"])
            or int(claims["sub"]) > 18446744073709551615
            or not isinstance(claims["sid"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", claims["sid"])
            or type(claims["iat"]) is not int or type(claims["exp"]) is not int
            or claims["iat"] > now or claims["exp"] <= now
            or claims["exp"] - claims["iat"] != ACCESS_SECONDS):
        raise JWTError("Invalid claims")
    return claims
