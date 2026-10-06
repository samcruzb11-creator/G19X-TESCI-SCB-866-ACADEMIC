"""Opt-in real MySQL tests: create/drop only a fresh, guarded temporary schema."""
import os
import re
import secrets
from pathlib import Path

import pymysql
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


@pytest.fixture(scope="session")
def mysql_factory():
    if os.environ.get("AUTH_MYSQL_TEST") != "1":
        pytest.skip("Opt in explicitly with AUTH_MYSQL_TEST=1; fresh local schema only")
    if settings.db_host not in {"localhost", "127.0.0.1"}:
        pytest.fail("Auth tests require a local MySQL endpoint; credentials hidden")
    name = "sistema_trazabilidad_test_auth_" + secrets.token_hex(8)
    assert re.fullmatch(r"sistema_trazabilidad_test_auth_[0-9a-f]{16}", name)
    assert name.casefold() not in {settings.db_name.casefold(), "sistema_trazabilidad"}
    admin = pymysql.connect(host=settings.db_host, port=settings.db_port,
                            user=settings.db_user, password=settings.db_password,
                            database=None, autocommit=True, connect_timeout=5)
    created = False
    engine = None
    try:
        with admin.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), VERSION()")
            selected, version = cursor.fetchone()
            assert selected is None, "Admin connection must not select a project schema"
            assert "mariadb" not in version.lower() and int(version.split(".")[0]) >= 8
            cursor.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (name,))
            assert cursor.fetchone() is None, "Never reuse or delete a pre-existing schema"
            cursor.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            created = True
        engine = create_engine(URL.create("mysql+pymysql", username=settings.db_user,
                               password=settings.db_password, host=settings.db_host,
                               port=settings.db_port, database=name), pool_pre_ping=True,
                               connect_args={"init_command": "SET time_zone='+00:00'"})

        @event.listens_for(engine, "checkout")
        def check_schema(connection, record, proxy):
            with connection.cursor() as cursor:
                cursor.execute("SELECT DATABASE()")
                assert cursor.fetchone()[0] == name, "Wrong schema: test aborted"

        root = Path(__file__).resolve().parents[1]
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "app/db/migrations"))
        with engine.connect() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "001")
            connection.execute(text("INSERT INTO usuarios (nombre,correo,correo_normalizado,password_hash,rol) "
                                    "VALUES ('Migration sentinel','sentinel@example.invalid',"
                                    "'sentinel@example.invalid','not-a-credential','ADMIN')"))
            connection.execute(text("INSERT INTO areas (codigo,nombre) VALUES ('AUTH_SENTINEL','Migration sentinel')"))
            connection.execute(text("INSERT INTO documentos (codigo,titulo,tipo,responsable_id,area_id,created_by_id) "
                                    "SELECT 'AUTH_SENTINEL','Migration sentinel','TEST',u.id,a.id,u.id "
                                    "FROM usuarios u JOIN areas a ON a.codigo='AUTH_SENTINEL' "
                                    "WHERE u.correo_normalizado='sentinel@example.invalid'"))
            connection.commit()

            def snapshot():
                tables = sorted(t for t in inspect(connection).get_table_names()
                                if t not in {"auth_sessions", "auth_login_limits", "alembic_version"})
                return {t: (connection.exec_driver_sql(f"SHOW CREATE TABLE `{t}`").one()[1],
                            [tuple(row) for row in connection.exec_driver_sql(f"SELECT * FROM `{t}`")])
                        for t in tables}

            baseline = snapshot()
            connection.commit()
            command.upgrade(cfg, "002")
            assert snapshot() == baseline
            connection.execute(text("INSERT INTO auth_sessions (sid,usuario_id,created_at,expires_at) "
                                    "SELECT :sid,id,UTC_TIMESTAMP(6),DATE_ADD(UTC_TIMESTAMP(6), INTERVAL 15 MINUTE) "
                                    "FROM usuarios WHERE correo_normalizado='sentinel@example.invalid'"),
                               {"sid": secrets.token_hex(32)})
            assert connection.execute(text("SELECT COUNT(*) FROM auth_sessions")).scalar_one() == 1
            connection.commit()
            command.downgrade(cfg, "001")
            assert "auth_sessions" not in inspect(connection).get_table_names()
            assert snapshot() == baseline
            connection.commit()
            command.upgrade(cfg, "002")
            assert snapshot() == baseline
            assert connection.execute(text("SELECT COUNT(*) FROM auth_sessions")).scalar_one() == 0
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "002"
            connection.commit()
            connection.execute(text("INSERT INTO auth_sessions (sid,usuario_id,created_at,expires_at) "
                "SELECT :sid,id,UTC_TIMESTAMP(6),DATE_ADD(UTC_TIMESTAMP(6), INTERVAL 15 MINUTE) "
                "FROM usuarios WHERE correo_normalizado='sentinel@example.invalid'"), {"sid": secrets.token_hex(32)})
            connection.commit()
            sessions_before = connection.execute(text("SELECT * FROM auth_sessions")).all()
            connection.commit()
            command.upgrade(cfg, "003")
            assert snapshot() == baseline
            assert connection.execute(text("SELECT * FROM auth_sessions")).all() == sessions_before
            assert "auth_login_limits" in inspect(connection).get_table_names()
            connection.commit()
            command.downgrade(cfg, "002")
            assert snapshot() == baseline
            assert connection.execute(text("SELECT * FROM auth_sessions")).all() == sessions_before
            assert "auth_login_limits" not in inspect(connection).get_table_names()
            assert {i['name'] for i in inspect(connection).get_indexes('auth_sessions')} == {'ix_auth_sessions_usuario'}
            connection.commit()
            command.upgrade(cfg, "003")
            assert snapshot() == baseline
            assert connection.execute(text("SELECT * FROM auth_sessions")).all() == sessions_before
            connection.commit()
            # Preserve every 003 table (DDL and rows), including auth limits/sessions.
            tables_003 = sorted(t for t in inspect(connection).get_table_names() if t != 'alembic_version')

            def snapshot_003():
                return {t: (connection.exec_driver_sql(f"SHOW CREATE TABLE `{t}`").one()[1],
                            [tuple(row) for row in connection.exec_driver_sql(f"SELECT * FROM `{t}`")])
                        for t in tables_003}

            before_004 = snapshot_003()
            connection.commit()
            added = {'access_requests', 'auth_action_limits', 'auth_action_tokens', 'auth_mail_jobs'}
            command.upgrade(cfg, '004')
            assert snapshot_003() == before_004
            assert added <= set(inspect(connection).get_table_names())
            connection.execute(text("INSERT INTO access_requests (identifier,nombre,motivo,status) "
                                    "VALUES ('sentinel-request@example.invalid','Sentinel','Migration test','PENDING')"))
            connection.commit()
            command.downgrade(cfg, '003')
            assert snapshot_003() == before_004
            assert not added.intersection(inspect(connection).get_table_names())
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '003'
            connection.commit()
            command.upgrade(cfg, '004')
            assert snapshot_003() == before_004
            assert connection.execute(text('SELECT COUNT(*) FROM access_requests')).scalar_one() == 0
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '004'
            connection.commit()
        print(f"\nMySQL {version}; temporary schema {name}; Alembic 001->002->001->002->003->002->003->004->003->004 OK; existing DDL/rows preserved")
        yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            # Delete only the random schema created by this exact fixture invocation.
            assert re.fullmatch(r"sistema_trazabilidad_test_auth_[0-9a-f]{16}", name)
            assert name.casefold() not in {settings.db_name.casefold(), "sistema_trazabilidad"}
            with admin.cursor() as cursor:
                cursor.execute(f"DROP DATABASE `{name}`")
            print(f"\nTemporary auth schema removed: {name}")
        admin.close()


@pytest.fixture(autouse=True)
def auth_config(monkeypatch):
    monkeypatch.setattr(settings, 'turnstile_mode', 'disabled')
    monkeypatch.setattr(settings, "jwt_secret_key", secrets.token_urlsafe(64))
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    from app.services import login_protection
    monkeypatch.setattr(login_protection, "global_budget", login_protection.GlobalLoginBudget())
    from app.services import auth_action_protection
    monkeypatch.setattr(auth_action_protection, 'budget', auth_action_protection.ActionBudget())
    # Even accidental sender invocation cannot open a real SMTP connection.
    import smtplib
    def no_smtp(*args, **kwargs):
        raise AssertionError('Real SMTP forbidden in tests')
    monkeypatch.setattr(smtplib, 'SMTP', no_smtp)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', no_smtp)
    from app.services import turnstile
    def no_siteverify(*args, **kwargs):
        raise AssertionError('Real Siteverify forbidden in tests')
    monkeypatch.setattr(turnstile, '_post', no_siteverify)
    # The application engine must never connect, including when testing the tool.
    from app.db.session import engine

    def forbidden(*args, **kwargs):
        raise AssertionError("Application DB connection forbidden in auth tests")

    event.listen(engine, "do_connect", forbidden)
    try:
        yield
    finally:
        event.remove(engine, "do_connect", forbidden)


@pytest.fixture
def clean_temporary_schema(mysql_factory):
    """Cleanup only the random schema owned by mysql_factory, never the app DB."""
    engine = mysql_factory.kw['bind']
    name = engine.url.database
    assert re.fullmatch(r'sistema_trazabilidad_test_auth_[0-9a-f]{16}', name)
    assert name.casefold() != settings.db_name.casefold()
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT DATABASE()').scalar_one() == name
        tables = inspect(connection).get_table_names()
        try:
            connection.exec_driver_sql('SET FOREIGN_KEY_CHECKS = 0')
            for table in tables:
                if table != 'alembic_version':
                    connection.exec_driver_sql('TRUNCATE TABLE ' + connection.dialect.identifier_preparer.quote(table))
            connection.commit()
        finally:
            try:
                connection.exec_driver_sql('SET FOREIGN_KEY_CHECKS = 1')
                connection.commit()
            except Exception:
                connection.invalidate()
                raise
    yield
