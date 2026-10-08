"""Contract regression with a fake DB and strictly temporary storage."""
import importlib.util
import io
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.main import app
from app.db.session import get_db
from app.api.dependencies import current_user
from app.models.entities import Usuario
from app.models.entities import Documento, Evidencia, VersionDocumento
from app.routers import documentos, evidencias
from app.services.storage_service import StorageService
from app.services.file_transaction import CommitOutcomeUnknown


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Engine, 'connect', Mock(side_effect=AssertionError('Database forbidden')))
    storage = StorageService(tmp_path)
    stored = storage.save_file(io.BytesIO(b'fixture'), 'test.txt')
    stamp = datetime(2026, 1, 1)
    version = VersionDocumento(id=1, documento_id=1, numero_version=1, storage_key=stored.storage_key, nombre_original='test.txt', mime_type='text/plain', tamano_bytes=7, sha256=stored.sha256, subido_por_id=1, created_at=stamp)
    doc = Documento(id=1, codigo='TEST', titulo='Test document', tipo='TEST', estado='ACTIVE', area_id=1, responsable_id=1, created_by_id=1, created_at=stamp, updated_at=stamp, version_vigente_id=1, version_vigente=version)
    evidence = Evidencia(id=1, auditoria_id=1, tipo='FILE', titulo='Test evidence', storage_key=stored.storage_key, nombre_original='test.txt', mime_type='text/plain', tamano_bytes=7, sha256=stored.sha256, registrada_por_id=1, created_at=stamp, updated_at=stamp)
    db = Mock()
    db.scalar.return_value.estado = 'PLANNED'
    actor = Usuario(id=1, rol='ADMIN', activo=True)
    db.scalar.side_effect = lambda statement: actor if statement.column_descriptions[0].get('entity') is Usuario else db.scalar.return_value
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: actor
    monkeypatch.setattr(documentos, 'storage_service', storage)
    monkeypatch.setattr(evidencias, 'storage_service', storage)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, db, doc, version, evidence
    finally:
        app.dependency_overrides.clear()


def test_download_version_and_evidence(client):
    c, db, doc, version, evidence = client
    db.scalar.return_value = version
    r = c.get('/api/v1/documentos/1/versiones/1/descargar')
    assert r.status_code == 200 and r.content == b'fixture'
    assert 'attachment' in r.headers['content-disposition']
    db.scalar.return_value = evidence
    db.get.return_value = evidence
    r = c.get('/api/v1/evidencias/1/descargar')
    assert r.status_code == 200 and r.content == b'fixture'
    assert 'attachment' in r.headers['content-disposition']


@pytest.mark.parametrize('tipo', ['NOTE', 'REFERENCE', 'OTHER'])
def test_logical_evidence_never_accesses_storage(client, monkeypatch, tipo):
    c, db, _, _, evidence = client
    evidence.tipo = tipo
    evidence.storage_key = None
    db.scalar.return_value = evidence
    db.get.return_value = evidence
    guard = Mock(side_effect=AssertionError('Logical evidence cannot access storage'))
    monkeypatch.setattr(evidencias.storage_service, 'get_absolute_path', guard)
    assert c.get('/api/v1/evidencias/1/descargar').status_code == 400
    guard.assert_not_called()


def test_list_contracts_hide_storage_keys(client):
    c, db, doc, version, evidence = client
    for path, row in [('/api/v1/documentos', doc), ('/api/v1/documentos/1/versiones', version), ('/api/v1/evidencias', evidence)]:
        db.get.return_value = doc
        db.scalars.return_value.all.return_value = [row]
        r = c.get(path)
        assert r.status_code == 200, r.text
        assert 'storage_key' not in r.text
        assert r.json()[0]['id'] == 1
    spec = c.get('/openapi.json').json()
    assert 'storage_key' not in spec['components']['schemas']['VersionDocumentoListRead']['properties']


def test_missing_and_manipulated_paths(client):
    c, db, _, version, evidence = client
    db.scalar.return_value = None
    assert c.get('/api/v1/documentos/1/versiones/1/descargar').status_code == 404
    db.scalar.return_value = None
    db.get.return_value = None
    assert c.get('/api/v1/evidencias/1/descargar').status_code == 404
    evidence.storage_key = '../private'
    db.scalar.return_value = evidence
    db.get.return_value = evidence
    r = c.get('/api/v1/evidencias/1/descargar')
    assert r.status_code == 400 and 'private' not in r.text
    version.storage_key = '../private'
    db.scalar.return_value = version
    assert c.get('/api/v1/documentos/1/versiones/1/descargar').status_code == 404


@pytest.mark.parametrize('debug', [False, True])
def test_internal_filesystem_errors_are_sanitized(client, monkeypatch, debug, caplog):
    c, db, _, _, _ = client
    from app.core.config import settings
    monkeypatch.setattr(settings, 'debug', debug)
    monkeypatch.setattr(evidencias.evidencia_service, 'registrar_evidencia_desde_upload', Mock(side_effect=OSError('SECRET DATABASE_URL C:/private/file')))
    r = c.post('/api/v1/evidencias/archivo', data={'auditoria_id':1,'titulo':'Test evidence','registrada_por_id':1}, files={'archivo':('file.txt',b'test')})
    assert r.status_code == 500
    assert r.json() == {'detail':'Error interno del servidor'}
    assert app.debug is False
    assert 'SECRET' not in caplog.text
    assert ('HTTP operation failed (OSError)' in caplog.text) is debug


def test_existing_storage_regression_without_db(monkeypatch):
    """The existing pure-storage test is compatible without its DB autouse fixture."""
    monkeypatch.setattr(Engine, 'connect', Mock(side_effect=AssertionError('Database forbidden')))
    path = Path(__file__).resolve().parents[1] / 'tests/test_storage_and_traceability.py'
    spec = importlib.util.spec_from_file_location('legacy_storage_regression', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.test_storage_service_streaming_and_integrity()


def test_unknown_commit_has_controlled_response_without_retry(client, monkeypatch):
    c, _, _, _, _ = client
    upload = Mock(side_effect=CommitOutcomeUnknown('SECRET DATABASE_URL C:/private SQL traceback'))
    monkeypatch.setattr(evidencias.evidencia_service, 'registrar_evidencia_desde_upload', upload)
    response = c.post('/api/v1/evidencias/archivo', data={'auditoria_id': 1, 'titulo': 'Test evidence', 'registrada_por_id': 1}, files={'archivo': ('file.txt', b'test')})
    assert response.status_code == 503
    assert response.json() == {
        'detail': 'No fue posible confirmar el estado de la transacción. Verifique el expediente antes de reintentar.',
        'code': 'COMMIT_OUTCOME_UNKNOWN',
    }
    upload.assert_called_once()
