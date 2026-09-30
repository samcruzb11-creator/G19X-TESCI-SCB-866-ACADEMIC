"""Real MySQL integration without storage or application-database access."""
import importlib.util
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Barrier, Event

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import inspect, select, text, func
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import hash_password, issue_token, verify_password
from app.db.session import get_db
from app.main import app
from app.models.auth import AuthSession
from app.models.entities import Usuario
from app.routers import auth
from app.schemas.auth import LoginRequest

PASSWORD = "isolated-mysql-auth-password"
NEW_PASSWORD = "isolated-mysql-changed-password"


@pytest.fixture
def user(mysql_factory):
    email = secrets.token_hex(8) + "@example.invalid"
    with mysql_factory() as db:
        user = Usuario(nombre="Isolated auth test", correo=email, correo_normalizado=email,
                       password_hash=hash_password(PASSWORD), rol="AUDITOR_INTERNO", activo=True)
        db.add(user)
        db.commit()
        return user.id, email


@pytest.fixture
def client(mysql_factory):
    def isolated_db():
        with mysql_factory() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def login(client, user, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"correo": " " + user[1].upper() + " ", "password": password})


def bearer(token):
    return {"Authorization": "Bearer " + token}


def claims(token):
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def session_count(factory, user_id):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.usuario_id == user_id))


def tool(monkeypatch, factory, user, password=NEW_PASSWORD, confirm=True):
    spec = importlib.util.spec_from_file_location("isolated_credential_tool",
              Path(__file__).resolve().parents[2] / "scripts/gestionar_usuario.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setattr("sys.argv", ["gestionar_usuario.py", "--usuario-id", str(user[0]), "--correo", user[1]])
    monkeypatch.setattr(module, "getpass", lambda prompt: password)
    monkeypatch.setattr("builtins.input", lambda prompt: f"CAMBIAR {user[0]}" if confirm else "CANCEL")
    return module


def test_schema(mysql_factory):
    with mysql_factory() as db:
        inspector = inspect(db.connection())
        columns = {c["name"]: c for c in inspector.get_columns("auth_sessions")}
        assert set(columns) == {"sid", "usuario_id", "created_at", "expires_at", "revoked_at"}
        assert columns["sid"]["type"].length == 64
        assert all(not columns[c]["nullable"] for c in columns if c != "revoked_at")
        assert columns["revoked_at"]["nullable"]
        assert all(columns[c]["type"].fsp == 6 for c in ["created_at", "expires_at", "revoked_at"])
        assert inspector.get_pk_constraint("auth_sessions")["constrained_columns"] == ["sid"]
        fk = inspector.get_foreign_keys("auth_sessions")[0]
        assert fk["name"] == "fk_auth_sessions_usuario"
        assert fk["referred_table"] == "usuarios" and fk["referred_columns"] == ["id"]
        assert {i["name"] for i in inspector.get_indexes("auth_sessions")} == {"ix_auth_sessions_usuario"}
        ddl = db.execute(text("SHOW CREATE TABLE auth_sessions")).one()[1]
        assert "ENGINE=InnoDB" in ddl and "ascii_bin" in ddl
        assert "ON DELETE RESTRICT ON UPDATE RESTRICT" in ddl


def test_fk_and_unique_sid(mysql_factory, user):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sid = secrets.token_hex(32)
    with mysql_factory() as db:
        db.add(AuthSession(sid=sid, usuario_id=user[0], created_at=now, expires_at=now + timedelta(minutes=15)))
        db.commit()
    for user_id in [user[0], 18446744073709551614]:
        with mysql_factory() as db:
            db.add(AuthSession(sid=sid if user_id == user[0] else secrets.token_hex(32), usuario_id=user_id,
                               created_at=now, expires_at=now + timedelta(minutes=15)))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
            assert not db.in_transaction()


def test_login_me(client, mysql_factory, user):
    response = login(client, user)
    assert response.status_code == 200
    token = response.json()["access_token"]
    decoded = claims(token)
    assert set(decoded) == {"sub", "sid", "iat", "exp"}
    assert decoded["exp"] - decoded["iat"] == 900
    with mysql_factory() as db:
        session = db.get(AuthSession, decoded["sid"])
        assert session.usuario_id == user[0] and session.revoked_at is None
        assert session.expires_at - session.created_at == timedelta(minutes=15)
        db.get(Usuario, user[0]).rol = "APROBADOR"
        db.commit()
    me = client.get("/api/v1/auth/me", headers=bearer(token))
    assert me.status_code == 200 and me.json()["rol"] == "APROBADOR"
    assert set(me.json()) == {"id", "nombre", "correo", "rol"}


@pytest.mark.parametrize("case", ["wrong", "missing", "inactive"])
def test_login_invalid_generic(client, mysql_factory, user, case):
    if case == "inactive":
        with mysql_factory() as db:
            db.get(Usuario, user[0]).activo = False
            db.commit()
    response = login(client, (user[0], "missing@example.invalid") if case == "missing" else user,
                     "incorrect" if case == "wrong" else PASSWORD)
    assert response.status_code == 401
    assert response.json() == {"detail": "Credenciales invalidas o sesion no vigente"}
    assert session_count(mysql_factory, user[0]) == 0


def test_logout_two_sessions(client, mysql_factory, user):
    first = login(client, user).json()["access_token"]
    second = login(client, user).json()["access_token"]
    assert first != second and session_count(mysql_factory, user[0]) == 2
    assert client.post("/api/v1/auth/logout", headers=bearer(first)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=bearer(first)).status_code == 401
    assert client.post("/api/v1/auth/logout", headers=bearer(first)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=bearer(second)).status_code == 200
    with mysql_factory() as db:
        assert db.get(AuthSession, claims(first)["sid"]).revoked_at is not None
        assert db.get(AuthSession, claims(second)["sid"]).revoked_at is None


@pytest.mark.parametrize("case", ["expired_token", "expired_session", "missing_session", "revoked", "deactivated", "signature"])
def test_invalid_after_issue(client, mysql_factory, user, case):
    token = login(client, user).json()["access_token"]
    sid = claims(token)["sid"]
    if case == "expired_token":
        token = issue_token(user[0], sid, int(datetime.now(timezone.utc).timestamp()) - 901)
    elif case == "signature":
        decoded = claims(token)
        token = jwt.encode(decoded, secrets.token_urlsafe(64), algorithm="HS256")
    else:
        with mysql_factory() as db:
            session = db.get(AuthSession, sid)
            if case == "expired_session":
                session.expires_at -= timedelta(minutes=20)
            elif case == "missing_session":
                db.delete(session)
            elif case == "revoked":
                session.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            elif case == "deactivated":
                db.get(Usuario, user[0]).activo = False
            db.commit()
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_password_tool_revokes_only_selected_user(client, mysql_factory, user, monkeypatch, capsys):
    old = login(client, user).json()["access_token"]
    with mysql_factory() as db:
        other = Usuario(nombre="Other isolated user", correo="other@example.invalid", correo_normalizado="other@example.invalid",
                        password_hash=hash_password(PASSWORD), activo=True, rol="ADMIN")
        db.add(other)
        db.commit()
        other_user = other.id, other.correo
        other_hash = other.password_hash
    other_token = login(client, other_user).json()["access_token"]
    assert tool(monkeypatch, mysql_factory, user).main() == 0
    assert client.get("/api/v1/auth/me", headers=bearer(old)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=bearer(other_token)).status_code == 200
    assert login(client, user).status_code == 401
    assert login(client, user, NEW_PASSWORD).status_code == 200
    with mysql_factory() as db:
        assert db.get(Usuario, user[0]).password_hash.startswith("$argon2id$")
        assert db.get(Usuario, other_user[0]).password_hash == other_hash
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err
    assert NEW_PASSWORD not in output.out + output.err and "$argon2" not in output.out + output.err


def test_tool_failure_rolls_back(client, mysql_factory, user, monkeypatch, capsys):
    old_token = login(client, user).json()["access_token"]
    module = tool(monkeypatch, mysql_factory, user)
    from sqlalchemy.orm import Session

    class FailingSession(Session):
        def commit(self):
            self.flush()  # Password and revocations reach MySQL but remain uncommitted.
            raise RuntimeError("private-driver-message")

    failing_factory = lambda: FailingSession(bind=mysql_factory.kw["bind"], autoflush=False)
    monkeypatch.setattr("app.db.session.SessionLocal", failing_factory)
    assert module.main() == 1
    assert client.get("/api/v1/auth/me", headers=bearer(old_token)).status_code == 200
    assert login(client, user).status_code == 200
    assert "private-driver-message" not in capsys.readouterr().out


@pytest.mark.parametrize("case", ["wrong_email", "missing_id", "cancel", "mismatch"])
def test_tool_refuses_unconfirmed_identity_or_password(client, mysql_factory, user, monkeypatch, case):
    old_token = login(client, user).json()["access_token"]
    selected = ((user[0], "not-selected@example.invalid") if case == "wrong_email" else
                (18446744073709551614, user[1]) if case == "missing_id" else user)
    module = tool(monkeypatch, mysql_factory, selected, confirm=case != "cancel")
    if case == "mismatch":
        answers = iter([NEW_PASSWORD, "different-confirmation"])
        monkeypatch.setattr(module, "getpass", lambda prompt: next(answers))
    assert module.main() == 1
    assert client.get("/api/v1/auth/me", headers=bearer(old_token)).status_code == 200
    with mysql_factory() as db:
        assert verify_password(PASSWORD, db.get(Usuario, user[0]).password_hash)


def test_two_concurrent_logins(mysql_factory, user, monkeypatch):
    barrier = Barrier(2)
    original = auth.verify_password

    def verified_together(*args):
        valid = original(*args)
        barrier.wait(timeout=10)
        return valid

    monkeypatch.setattr(auth, "verify_password", verified_together)

    def attempt():
        with mysql_factory() as db:
            result = auth.login(LoginRequest(correo=user[1], password=PASSWORD), Response(), db)
            assert not db.in_transaction()
            return result.access_token

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(lambda _: attempt(), range(2)))
    assert one != two and session_count(mysql_factory, user[0]) == 2


def test_concurrent_password_change_rejects_old_login(mysql_factory, user, monkeypatch):
    verified = Event()
    changed = Event()
    original = auth.verify_password
    module = tool(monkeypatch, mysql_factory, user)

    def pause_after_verification(*args):
        result = original(*args)
        verified.set()
        assert changed.wait(timeout=10)
        return result

    monkeypatch.setattr(auth, "verify_password", pause_after_verification)

    def attempt():
        with mysql_factory() as db:
            with pytest.raises(HTTPException) as exc:
                auth.login(LoginRequest(correo=user[1], password=PASSWORD), Response(), db)
            assert exc.value.status_code == 401
            assert not db.in_transaction()  # Explicit rollback after locked recheck.

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(attempt)
        try:
            assert verified.wait(timeout=10)
            assert module.main() == 0
        finally:
            changed.set()
        future.result(timeout=10)
    assert session_count(mysql_factory, user[0]) == 0


def test_failed_session_commit_rolls_back(mysql_factory, user):
    from sqlalchemy.orm import Session

    class FailingSession(Session):
        def commit(self):
            self.flush()
            raise RuntimeError("simulated precommit failure")

    with FailingSession(bind=mysql_factory.kw["bind"], autoflush=False) as db:
        with pytest.raises(RuntimeError):
            auth.login(LoginRequest(correo=user[1], password=PASSWORD), Response(), db)
        assert not db.in_transaction()
    assert session_count(mysql_factory, user[0]) == 0
    with mysql_factory() as db:
        assert auth.login(LoginRequest(correo=user[1], password=PASSWORD), Response(), db).access_token
