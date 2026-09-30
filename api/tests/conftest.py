"""Fail closed before collecting integration tests; never use the app engine."""

import os
from urllib.parse import unquote

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401 -- register all integration tables, without the app engine


def _abort(message):
    pytest.exit(message, returncode=2)


raw_url = os.environ.get("TEST_DATABASE_URL")
if not raw_url:
    _abort("Tests abortados: define TEST_DATABASE_URL con una base exclusiva de pruebas.")

try:
    test_url = make_url(raw_url)
    development_urls = [make_url(settings.database_url)]
    if os.environ.get("DATABASE_URL"):
        development_urls.append(make_url(os.environ["DATABASE_URL"]))
except Exception:
    _abort("Tests abortados: URL de base de datos invalida (credenciales ocultas).")


def _database_name(url):
    return unquote(url.database or "").strip().casefold()


# Reject the development schema even through a different host, driver or user.
forbidden_names = {"sistema_trazabilidad", *(_database_name(url) for url in development_urls)}
if test_url in development_urls or _database_name(test_url) in forbidden_names:
    _abort("Tests abortados: TEST_DATABASE_URL apunta a la base oficial o de desarrollo.")
if unquote(test_url.database or "") != "sistema_trazabilidad_test":
    _abort("Tests abortados: la unica base autorizada es sistema_trazabilidad_test.")
if test_url.drivername != "mysql+pymysql" or not test_url.database or test_url.query:
    _abort("Tests abortados: usa mysql+pymysql, una base de pruebas explicita y sin parametros URL.")

test_engine = create_engine(
    test_url, pool_pre_ping=True,
    connect_args={"init_command": "SET time_zone='+00:00'"},
)


@event.listens_for(test_engine, "checkout")
def verify_connected_database(dbapi_connection, connection_record, connection_proxy):
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE()")
        actual = (cursor.fetchone()[0] or "").strip().casefold()
    if actual in forbidden_names or actual != _database_name(test_url):
        dbapi_connection.close()
        _abort("Tests abortados: la conexion real no corresponde a la base de pruebas autorizada.")


@pytest.fixture(scope="session")
def db_session_factory():
    """Create only model DDL in the guarded test database; never seed real data."""
    try:
        with test_engine.begin() as connection:
            existing = set(inspect(connection).get_table_names())
            Base.metadata.create_all(bind=connection)
            created = sorted(set(Base.metadata.tables) - existing)
        print("\nIntegration schema: sistema_trazabilidad_test; created tables: "
              + (", ".join(created) or "none (already present)"))
        yield sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    finally:
        test_engine.dispose()


@pytest.fixture
def clean_test_database(db_session_factory):
    """Truncate only registered model tables on the guarded test engine."""
    def clean():
        with test_engine.connect() as connection:
            try:
                connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
                for table in Base.metadata.tables.values():
                    connection.exec_driver_sql(
                        "TRUNCATE TABLE " + connection.dialect.identifier_preparer.format_table(table)
                    )
                connection.commit()
            finally:
                try:
                    connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
                    connection.commit()
                except Exception:
                    # Never return a connection with disabled checks to the pool.
                    connection.invalidate()
                    raise

    clean()
    try:
        yield
    finally:
        clean()
