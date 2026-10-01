"""PHP -> HTTP FastAPI -> freshly created, guarded MySQL schema only."""
import importlib.util
import io
from pathlib import Path
import re
import secrets
import socket
from threading import Thread
import time

import httpx
import pytest
import uvicorn
from sqlalchemy import select

from app.main import app
from app.db.session import get_db
from app.core.security import hash_password
from app.models.auth import AuthSession
from app.models.entities import Area, Documento, Usuario, VersionDocumento
from app.routers import documentos, evidencias
from app.services.storage_service import StorageService
from app.services.documento_service import documento_service
from app.services.evidencia_service import evidencia_service

spec = importlib.util.spec_from_file_location('isolated_php_support', Path(__file__).resolve().parents[2] / 'frontend/tests/conftest.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


@pytest.fixture
def php_mysql(mysql_factory, clean_temporary_schema, tmp_path, monkeypatch):
    password = secrets.token_urlsafe(24)
    with mysql_factory() as db:
        users = [Usuario(nombre='PHP owner', correo='owner@example.invalid', correo_normalizado='owner@example.invalid',
                         rol='RESPONSABLE_AREA', password_hash=hash_password(password)),
                 Usuario(nombre='Other owner', correo='other@example.invalid', correo_normalizado='other@example.invalid',
                         rol='RESPONSABLE_AREA', password_hash=hash_password(password))]
        area = Area(codigo='PHP_TEST', nombre='PHP test area')
        db.add_all([*users, area]); db.flush()
        ids = [user.id for user in users]
        docs = [Documento(codigo=f'PHP{i}', titulo=f'Document {i}', tipo='TEST', area_id=area.id,
                          responsable_id=user.id, created_by_id=user.id) for i, user in enumerate(users)]
        db.add_all(docs); db.flush()
        doc_ids = [doc.id for doc in docs]
        area_id = area.id
        storage = StorageService(tmp_path / 'storage')
        versions = []
        for doc, user in zip(docs, users):
            stored = storage.save_file(io.BytesIO(b'isolated bytes'), 'isolated.txt')
            version = VersionDocumento(documento_id=doc.id, numero_version=1, storage_key=stored.storage_key,
                                       nombre_original='isolated.txt', mime_type='text/plain', tamano_bytes=stored.tamano_bytes,
                                       sha256=stored.sha256, subido_por_id=user.id)
            db.add(version); db.flush()
            versions.append(version.id)
        db.commit()
    for instance in [documentos, evidencias]: monkeypatch.setattr(instance, 'storage_service', storage)
    for instance in [documento_service, evidencia_service]: monkeypatch.setattr(instance, 'storage', storage)

    def isolated_db():
        with mysql_factory() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    thread = Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic()+10
        while not server.started:
            assert thread.is_alive() and time.monotonic()<deadline, 'Isolated FastAPI startup failed'
            time.sleep(.02)
        with support.php_server(tmp_path / 'php', f'http://127.0.0.1:{port}') as (client, private, web):
            yield client, private, password, ids, doc_ids, versions, area_id, port
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        app.dependency_overrides.clear()
        sock.close()
        assert not thread.is_alive(), 'Isolated FastAPI did not stop'


def php_login(client, password):
    page = client.get('/index.php?pagina=login')
    return client.post('/index.php?pagina=login', data=dict(correo='owner@example.invalid', password=password,
                                                         csrf_token=support.csrf(page)))


def test_real_login_forms_download_idor_and_logout(php_mysql, mysql_factory):
    c, private, password, users, docs, versions, area, port = php_mysql
    assert php_login(c, password).status_code == 303
    session = (private / 'sistema-trazabilidad-frontend-sessions' / ('sess_'+c.cookies.get('PHPSESSID'))).read_text()
    token = re.search(r's:12:"access_token";s:\d+:"([^"]+)"', session)[1]
    page = c.get('/index.php?pagina=documento_nuevo')
    r = c.post('/index.php?pagina=documento_nuevo', data=dict(csrf_token=support.csrf(page), codigo='PHP_CREATED',
        titulo='Created through PHP', tipo='TEST', estado='DRAFT', area_id=area, responsable_id=users[1], creador_id=users[1]))
    assert r.status_code == 303
    with mysql_factory() as db:
        doc = db.scalar(select(Documento).where(Documento.codigo == 'PHP_CREATED'))
        assert doc.responsable_id == users[0] and doc.created_by_id == users[0]
        assert db.scalar(select(AuthSession).where(AuthSession.usuario_id == users[0])).revoked_at is None
    own = c.get(f'/index.php?pagina=documento&id={docs[0]}&accion=descargar&version_id={versions[0]}')
    assert own.status_code == 200 and own.content == b'isolated bytes'
    denied = c.get(f'/index.php?pagina=documento&id={docs[1]}&accion=descargar&version_id={versions[1]}')
    assert denied.status_code == 404
    assert c.get('/index.php?pagina=auditorias').status_code == 403
    page = c.get('/index.php?pagina=dashboard')
    assert c.post('/index.php?pagina=logout', data={'csrf_token':support.csrf(page)}).status_code == 303
    with httpx.Client(base_url=f'http://127.0.0.1:{port}') as api:
        assert api.get('/api/v1/auth/me', headers={'Authorization':'Bearer '+token}).status_code == 401
    with mysql_factory() as db:
        assert db.scalar(select(AuthSession).where(AuthSession.usuario_id == users[0])).revoked_at is not None
    assert c.get('/index.php?pagina=documentos').status_code == 303


def test_real_role_change_and_deactivation(php_mysql, mysql_factory):
    c, _, password, users, _, _, _, _ = php_mysql
    assert php_login(c, password).status_code == 303
    with mysql_factory() as db:
        db.get(Usuario, users[0]).rol = 'APROBADOR'
        db.commit()
    dashboard = c.get('/index.php?pagina=dashboard')
    assert dashboard.status_code == 200 and 'APROBADOR' in dashboard.text
    assert 'href="index.php?pagina=documento_nuevo"' not in dashboard.text
    with mysql_factory() as db:
        db.get(Usuario, users[0]).activo = False
        db.commit()
    result = c.get('/index.php?pagina=documentos')
    assert result.status_code == 303
    assert 'La sesión expiró.' in c.get(result.headers['location']).text
