"""Bootstrap integration runs ONLY on the fixture-owned random MySQL schema."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import hash_password, verify_password
from app.models.entities import Usuario

pytestmark = pytest.mark.usefixtures("clean_temporary_schema")
PASSWORD = "isolated-bootstrap-private-password"


@pytest.fixture
def tool():
    spec = importlib.util.spec_from_file_location("bootstrap_mysql",
        Path(__file__).resolve().parents[2] / "scripts/bootstrap_admin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def users(factory):
    with factory() as db:
        return [tuple(row) for row in db.execute(text("SELECT * FROM usuarios ORDER BY id"))]


def seed(factory, *, email="auditor@example.invalid", role="AUDITOR_INTERNO", active=True):
    with factory() as db:
        user = Usuario(nombre="Existing user", correo=email, correo_normalizado=email,
                       password_hash=hash_password(PASSWORD), rol=role, activo=active)
        db.add(user); db.commit()
        return user.id


def test_first_admin_fixed_role_active_hash_no_autologin_existing_user_intact(tool, mysql_factory, capsys):
    seed(mysql_factory)
    before = users(mysql_factory)
    new_id = tool.create_first_admin(" Local Admin ", " ADMIN@EXAMPLE.INVALID ", PASSWORD, factory=mysql_factory)
    after = users(mysql_factory)
    assert after[:-1] == before
    with mysql_factory() as db:
        user = db.get(Usuario, new_id)
        assert user.nombre == "Local Admin" and user.correo == user.correo_normalizado == "admin@example.invalid"
        assert user.rol == "ADMIN" and user.activo and user.password_hash != PASSWORD
        assert user.password_hash.startswith("$argon2id$") and verify_password(PASSWORD, user.password_hash)
        for table in ("auth_sessions", "access_requests", "auth_action_tokens", "auth_mail_jobs"):
            assert db.execute(text("SELECT COUNT(*) FROM " + table)).scalar_one() == 0
        assert db.scalar(select(func.count()).select_from(Usuario).where(Usuario.rol == "ADMIN", Usuario.activo.is_(True))) == 1
    assert PASSWORD not in capsys.readouterr().out


def test_refuses_second_active_admin_without_mutation(tool, mysql_factory):
    seed(mysql_factory, role="ADMIN")
    before = users(mysql_factory)
    with pytest.raises(tool.BootstrapError, match="deshabilitado"):
        tool.create_first_admin("Another Admin", "new@example.invalid", PASSWORD, factory=mysql_factory)
    assert users(mysql_factory) == before


def test_inactive_admin_does_not_block_first_active_admin(tool, mysql_factory):
    seed(mysql_factory, role="ADMIN", active=False)
    before = users(mysql_factory)
    tool.create_first_admin("Local Admin", "new@example.invalid", PASSWORD, factory=mysql_factory)
    assert users(mysql_factory)[:-1] == before


@pytest.mark.parametrize("existing,attempt", [("same@example.invalid", "same@example.invalid"),
    ("mixed@example.invalid", " MIXED@EXAMPLE.INVALID "),
    ("cafe@example.invalid", "café@example.invalid")])
def test_duplicate_and_mysql_collation_refused(tool, mysql_factory, existing, attempt):
    seed(mysql_factory, email=existing)
    before = users(mysql_factory)
    with pytest.raises(tool.BootstrapError, match="correo ya pertenece"):
        tool.create_first_admin("Local Admin", attempt, PASSWORD, factory=mysql_factory)
    assert users(mysql_factory) == before


def test_database_unique_constraint_also_blocks_racing_duplicate(tool, mysql_factory):
    seed(mysql_factory, email="existing@example.invalid")
    before = users(mysql_factory)
    def conflicting_flush(db, ctx, instances):
        for user in db.new:
            if isinstance(user, Usuario):
                user.correo_normalizado = "existing@example.invalid"
    engine = mysql_factory.kw["bind"]
    class ConflictingSession(Session):
        pass
    event.listen(ConflictingSession, "before_flush", conflicting_flush)
    factory = sessionmaker(bind=engine, class_=ConflictingSession, autoflush=False)
    try:
        with pytest.raises(tool.BootstrapError, match="identidad no disponible"):
            tool.create_first_admin("Local Admin", "new@example.invalid", PASSWORD, factory=factory)
    finally:
        event.remove(ConflictingSession, "before_flush", conflicting_flush)
    assert users(mysql_factory) == before


def test_rollback_after_insert_preserves_existing_users_and_releases_lock(tool, mysql_factory):
    seed(mysql_factory)
    before = users(mysql_factory)
    class FailingSession(Session):
        pass
    def fail_commit(db):
        raise RuntimeError("simulated precommit failure")
    event.listen(FailingSession, "before_commit", fail_commit)
    factory = sessionmaker(bind=mysql_factory.kw["bind"], class_=FailingSession, autoflush=False)
    try:
        with pytest.raises(RuntimeError, match="precommit"):
            tool.create_first_admin("Local Admin", "admin@example.invalid", PASSWORD, factory=factory)
    finally:
        event.remove(FailingSession, "before_commit", fail_commit)
    assert users(mysql_factory) == before
    assert tool.create_first_admin("Local Admin", "admin@example.invalid", PASSWORD, factory=mysql_factory) > 0


@pytest.mark.parametrize("password", ["short", "x" * 1025])
def test_invalid_password_no_change(tool, mysql_factory, password):
    seed(mysql_factory)
    before = users(mysql_factory)
    with pytest.raises(tool.BootstrapError, match="12 y 1024"):
        tool.create_first_admin("Local Admin", "admin@example.invalid", password, factory=mysql_factory)
    assert users(mysql_factory) == before


def test_two_concurrent_bootstraps_create_only_one_active_admin(tool, mysql_factory):
    barrier = Barrier(2)
    def attempt(i):
        barrier.wait(timeout=10)
        try:
            return tool.create_first_admin("Local Admin", f"admin{i}@example.invalid", PASSWORD, factory=mysql_factory)
        except tool.BootstrapError as exc:
            assert "deshabilitado" in str(exc)
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(value is not None for value in results) == 1
    with mysql_factory() as db:
        assert db.scalar(select(func.count()).select_from(Usuario).where(Usuario.rol == "ADMIN", Usuario.activo.is_(True))) == 1
