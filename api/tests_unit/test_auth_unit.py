"""Authentication HTTP tests with in-memory doubles; all engine connections forbidden."""
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
import importlib.util
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.engine import Engine

from app.main import app
from app.core.config import settings
from app.core.security import hash_password, issue_token, verify_password, validate_jwt_config
from app.db.session import get_db
from app.models.auth import AuthSession
from app.models.entities import Usuario

PASSWORD = "isolated-test-password"


class MemoryDB:
    def __init__(self, user):
        self.user = user
        self.sessions = {}

    def scalar(self, statement):
        params = statement.compile().params
        if "id_1" in params:
            return self.user if self.user and self.user.id == params["id_1"] else None
        email = params["correo_normalizado_1"]
        return self.user if self.user and self.user.correo_normalizado == email else None

    def get(self, model, key):
        if model is AuthSession:
            return self.sessions.get(key)
        return self.user if self.user and self.user.id == key else None

    def add(self, session):
        self.sessions[session.sid] = session

    def execute(self, statement):
        params = statement.compile().params
        session = self.sessions[params["sid_1"]]
        if session.revoked_at is None:
            session.revoked_at = params["revoked_at"]

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def client(monkeypatch):
    from app.services import login_protection
    def reserve(db, identifier):
        login_protection.global_budget.acquire_argon2()
        return None
    # Legacy credential tests use a DB double; real admission is covered separately.
    monkeypatch.setattr(login_protection, "reserve", reserve)
    monkeypatch.setattr(login_protection, "release_reservation", lambda *args: None)
    monkeypatch.setattr(Engine, "connect", Mock(side_effect=AssertionError("Real database forbidden")))
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    user = Usuario(id=1, nombre="Test", correo="test@example.invalid", correo_normalizado="test@example.invalid",
                   password_hash=hash_password(PASSWORD), activo=True, rol="AUDITOR_INTERNO")
    db = MemoryDB(user)
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app, raise_server_exceptions=False) as http:
            yield http, db
    finally:
        app.dependency_overrides.clear()


def login(http, **values):
    return http.post("/api/v1/auth/login", json={"correo": " TEST@example.invalid ", "password": PASSWORD, **values})


def headers(token):
    return {"Authorization": "Bearer " + token}


def test_passwords():
    hashed = hash_password(PASSWORD)
    assert hashed.startswith("$argon2id$")
    assert verify_password(PASSWORD, hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password(PASSWORD, "legacy-invalid")


@pytest.mark.parametrize("case", ["wrong", "missing", "inactive"])
def test_invalid_credentials_generic(client, case):
    http, db = client
    if case == "inactive":
        db.user.activo = False
    response = login(http, **({"password": "wrong"} if case == "wrong" else
                              {"correo": "missing@example.invalid"} if case == "missing" else {}))
    assert response.status_code == 401
    assert response.json() == {"detail": "Credenciales invalidas o sesion no vigente"}
    assert not db.sessions


def test_valid_token_and_db_role(client):
    http, db = client
    response = login(http)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    token = response.json()["access_token"]
    claims = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    assert set(claims) == {"sub", "sid", "iat", "exp"}
    assert claims["exp"] - claims["iat"] == 900
    db.user.rol = "APROBADOR"
    me = http.get("/api/v1/auth/me", headers=headers(token))
    assert me.status_code == 200 and me.json()["rol"] == "APROBADOR"
    assert set(me.json()) == {"id", "nombre", "correo", "rol"}


@pytest.mark.parametrize("case", ["absent", "tampered", "expired", "missing_session", "revoked",
                                  "expired_session", "missing_user", "inactive_user", "wrong_owner"])
def test_invalid_authentication(client, case):
    http, db = client
    token = login(http).json()["access_token"]
    session = next(iter(db.sessions.values()))
    if case == "tampered":
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        token = ".".join(parts)
    elif case == "expired":
        token = issue_token(1, session.sid, int(datetime.now(timezone.utc).timestamp()) - 901)
    elif case == "missing_session":
        db.sessions.clear()
    elif case == "revoked":
        session.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    elif case == "expired_session":
        session.expires_at -= timedelta(minutes=20)
    elif case == "missing_user":
        db.user = None
    elif case == "inactive_user":
        db.user.activo = False
    elif case == "wrong_owner":
        session.usuario_id = 2
    response = http.get("/api/v1/auth/me", headers={} if case == "absent" else headers(token))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_logout_only_current_session(client):
    http, db = client
    first = login(http).json()["access_token"]
    second = login(http).json()["access_token"]
    assert len(db.sessions) == 2
    assert http.post("/api/v1/auth/logout", headers=headers(first)).status_code == 204
    assert http.get("/api/v1/auth/me", headers=headers(first)).status_code == 401
    assert http.post("/api/v1/auth/logout", headers=headers(first)).status_code == 401
    assert http.get("/api/v1/auth/me", headers=headers(second)).status_code == 200
    assert sum(s.revoked_at is not None for s in db.sessions.values()) == 1


@pytest.mark.parametrize("secret", ["replace-with-a-long-random-secret", "x" * 64, "short"])
def test_insecure_config_rejected(client, monkeypatch, secret):
    http, db = client
    monkeypatch.setattr(settings, "jwt_secret_key", secret)
    assert login(http).status_code == 503
    assert not db.sessions


def test_validation_never_echoes_password(client):
    http, _ = client
    secret = "do-not-echo-this-password"
    response = login(http, password=secret, unexpected=secret)
    assert response.status_code == 422
    assert secret not in response.text


@pytest.mark.parametrize("change", ["missing_sid", "role", "future", "wrong_lifetime", "bad_sub", "bad_sid", "algorithm"])
def test_invalid_signed_claims(client, change):
    http, _ = client
    original = login(http).json()["access_token"]
    claims = jwt.decode(original, settings.jwt_secret_key, algorithms=["HS256"])
    algorithm = "HS256"
    if change == "missing_sid":
        del claims["sid"]
    elif change == "role":
        claims["rol"] = "ADMIN"
    elif change == "future":
        claims["iat"] += 100
        claims["exp"] += 100
    elif change == "wrong_lifetime":
        claims["exp"] += 1
    elif change == "bad_sub":
        claims["sub"] = "not-a-user"
    elif change == "bad_sid":
        claims["sid"] = "invalid"
    else:
        algorithm = "HS384"
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=algorithm)
    assert http.get("/api/v1/auth/me", headers=headers(token)).status_code == 401


@pytest.mark.parametrize("case", ["success", "wrong_identity", "mismatch", "cancel"])
def test_provisioning_is_explicit_and_scoped(client, monkeypatch, capsys, case):
    _, memory = client
    path = Path(__file__).resolve().parents[2] / "scripts" / "gestionar_usuario.py"
    spec = importlib.util.spec_from_file_location("credential_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("sys.argv", [str(path), "--usuario-id", "1", "--correo", "test@example.invalid"])
    answers = iter([PASSWORD, "different" if case == "mismatch" else PASSWORD])
    monkeypatch.setattr(module, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr("builtins.input", lambda prompt: "cancel" if case == "cancel" else "CAMBIAR 1")
    db = Mock()
    db.scalar.return_value = None if case == "wrong_identity" else memory.user
    db.__enter__ = Mock(return_value=db)
    db.__exit__ = Mock(return_value=False)
    factory = Mock(return_value=db)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    old_hash = memory.user.password_hash
    result = module.main()
    if case == "success":
        assert result == 0
        assert verify_password(PASSWORD, memory.user.password_hash)
        assert memory.user.password_hash != old_hash
        db.commit.assert_called_once()
        stmt = db.execute.call_args.args[0]
        assert stmt.compile().params["usuario_id_1"] == 1
    else:
        assert result == 1
        db.commit.assert_not_called()
        assert memory.user.password_hash == old_hash
    output = capsys.readouterr().out
    assert PASSWORD not in output and "$argon2" not in output


def test_session_ddl_compiles_for_mysql():
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateTable
    ddl = str(CreateTable(AuthSession.__table__).compile(dialect=mysql.dialect()))
    assert "BIGINT UNSIGNED" in ddl and "DATETIME(6)" in ddl
    assert "ascii_bin" in ddl and "FOREIGN KEY" in ddl


def test_startup_rejects_insecure_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "replace-with-a-long-random-secret")
    with pytest.raises(ValueError, match="Configuracion JWT insegura"):
        with TestClient(app):
            pytest.fail("Startup must reject insecure JWT configuration")


@pytest.mark.parametrize("algorithm,size", [("HS256", 32), ("HS384", 48), ("HS512", 64)])
@pytest.mark.parametrize("encoding", ["hex", "urlsafe"])
def test_csprng_secret_accepted(monkeypatch, algorithm, size, encoding):
    monkeypatch.setattr(settings, "jwt_algorithm", algorithm)
    generate = secrets.token_hex if encoding == "hex" else secrets.token_urlsafe
    monkeypatch.setattr(settings, "jwt_secret_key", generate(size))
    with TestClient(app):
        validate_jwt_config()


def test_many_random_hex_secrets_accepted(monkeypatch):
    # No diversity requirement: every 32-byte CSPRNG sample must be accepted.
    for _ in range(256):
        monkeypatch.setattr(settings, "jwt_secret_key", secrets.token_hex(32))
        validate_jwt_config()
    # Fixed regression sample missing hexadecimal symbols; not a real credential.
    monkeypatch.setattr(settings, "jwt_secret_key", "0123456789abcde0" * 4)
    validate_jwt_config()


@pytest.mark.parametrize("algorithm,secret", [
    ("HS256", "short"), ("HS256", "0123456789abcdef" + "0123456789abcde"),
    ("HS384", "0123456789abcdef" * 2), ("HS512", "0123456789abcdef" * 3),
    ("HS256", "x" * 64), ("HS256", " " * 64),
    *[("HS256", marker + "0123456789abcdef" * 4)
      for marker in ["replace-with", "changeme", "change-me", "default", "example"]],
])
def test_startup_rejects_unsafe_secrets(monkeypatch, algorithm, secret):
    monkeypatch.setattr(settings, "jwt_algorithm", algorithm)
    monkeypatch.setattr(settings, "jwt_secret_key", secret)
    with pytest.raises(ValueError, match="Configuracion JWT insegura"):
        with TestClient(app):
            pytest.fail("Startup must fail before serving requests")


@pytest.mark.parametrize("password", ["short", "p" * 1025])
def test_provisioning_password_length_validation(monkeypatch, capsys, password):
    path = Path(__file__).resolve().parents[2] / "scripts" / "gestionar_usuario.py"
    spec = importlib.util.spec_from_file_location("password_validation_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("sys.argv", [str(path), "--usuario-id", "1", "--correo", "test@example.invalid"])
    monkeypatch.setattr(module, "getpass", lambda prompt: password)
    confirmation = Mock(side_effect=AssertionError("Must not confirm invalid password"))
    monkeypatch.setattr("builtins.input", confirmation)
    factory = Mock(side_effect=AssertionError("Must not open DB for invalid password"))
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    assert module.main() == 1
    factory.assert_not_called()
    confirmation.assert_not_called()
    output = capsys.readouterr()
    assert "entre 12 y 1024 caracteres. Sin cambios." in output.out
    assert "Verifique el estado" not in output.out
    assert password not in output.out + output.err
    assert "$argon2" not in output.out + output.err


@pytest.mark.parametrize("claim,value", [
    ("sub", None), ("sub", 1), ("sub", "0"), ("sub", "18446744073709551616"),
    ("sid", None), ("sid", 123), ("sid", "A" * 64),
    ("iat", None), ("iat", True), ("iat", 1.5), ("iat", []),
    ("exp", None), ("exp", True), ("exp", 1.5), ("exp", []),
])
def test_claim_types_and_ranges(client, claim, value):
    http, _ = client
    token = login(http).json()["access_token"]
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    payload[claim] = value
    malformed = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    assert http.get("/api/v1/auth/me", headers=headers(malformed)).status_code == 401


@pytest.mark.parametrize("claim", ["sub", "sid", "iat", "exp"])
def test_required_claims(client, claim):
    http, _ = client
    token = login(http).json()["access_token"]
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    del payload[claim]
    malformed = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    assert http.get("/api/v1/auth/me", headers=headers(malformed)).status_code == 401


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
def test_allowed_algorithm_roundtrip(client, monkeypatch, algorithm):
    http, _ = client
    monkeypatch.setattr(settings, "jwt_algorithm", algorithm)
    response = login(http)
    assert response.status_code == 200
    assert http.get("/api/v1/auth/me", headers=headers(response.json()["access_token"])).status_code == 200


@pytest.mark.parametrize("algorithm", ["none", "RS256", "ES256", "HS128"])
def test_startup_rejects_unconfigured_algorithm(monkeypatch, algorithm):
    monkeypatch.setattr(settings, "jwt_algorithm", algorithm)
    with pytest.raises(ValueError, match="Configuracion JWT insegura"):
        with TestClient(app):
            pytest.fail("Unexpected startup")


def test_unsigned_token_rejected(client):
    import base64
    import json
    http, _ = client
    original = login(http).json()["access_token"]
    unsigned_header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    unsigned = unsigned_header + "." + original.split(".")[1] + "."
    assert http.get("/api/v1/auth/me", headers=headers(unsigned)).status_code == 401


def test_provisioning_refuses_visible_password_fallback(client, monkeypatch, capsys):
    import warnings
    from getpass import GetPassWarning
    path = Path(__file__).resolve().parents[2] / "scripts/gestionar_usuario.py"
    spec = importlib.util.spec_from_file_location("unsafe_terminal_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("sys.argv", [str(path), "--usuario-id", "1", "--correo", "test@example.invalid"])

    def unsupported_terminal(prompt):
        warnings.warn("Password input may be echoed", GetPassWarning)
        pytest.fail("Must not fall back to visible password input")

    monkeypatch.setattr(module, "getpass", unsupported_terminal)
    factory = Mock(side_effect=AssertionError("DB must not open on unsafe input"))
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    assert module.main() == 1
    factory.assert_not_called()
    assert "Password input may be echoed" not in capsys.readouterr().err
