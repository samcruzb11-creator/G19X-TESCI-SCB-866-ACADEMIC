"""Fail closed before collecting integration tests; never use the app engine."""

import os
from urllib.parse import unquote

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


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
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    yield factory
    test_engine.dispose()
