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
                                if t not in {"auth_sessions", "alembic_version"})
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
        print(f"\nMySQL {version}; temporary schema {name}; Alembic 001->002->001->002 OK; domain DDL/rows unchanged")
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
    monkeypatch.setattr(settings, "jwt_secret_key", secrets.token_urlsafe(64))
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    # The application engine must never connect, including when testing the tool.
    from app.db.session import engine

    def forbidden(*args, **kwargs):
        raise AssertionError("Application DB connection forbidden in auth tests")

    event.listen(engine, "do_connect", forbidden)
    try:
        yield
    finally:
        event.remove(engine, "do_connect", forbidden)
