"""Demo seed and adversarial HTTP checks on a fixture-owned MySQL schema only."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.db.session import get_db
from app.main import app
from app.core.security import verify_password
from app.models.entities import Area, Usuario, Documento, Auditoria, VersionDocumento, EventoAuditoria, RondaAprobacion, DecisionAprobacion
from app.scripts import seed_evaluation_demo as demo
from app.scripts.evaluation_credentials import generate_file, load_credentials
from app.services.storage_service import StorageService


@pytest.fixture
def credentials_file(tmp_path):
    return generate_file(tmp_path / 'private.md')


@pytest.fixture
def demo_accounts(credentials_file):
    return tuple((a.email, a.role, a.name, a.password) for a in load_credentials(credentials_file))


@pytest.fixture
def seeded(clean_temporary_schema, mysql_factory, tmp_path, monkeypatch, credentials_file):
    monkeypatch.setattr(demo.settings, 'app_env', 'development')
    storage = StorageService(tmp_path / 'storage')
    assert demo.seed(factory=mysql_factory, credentials_file=credentials_file, storage=storage, with_dataset=True) == 4
    return storage


def snapshot(factory):
    with factory() as db:
        tables = ['usuarios', 'areas', 'auditorias', 'documentos', 'versiones_documento',
                  'eventos_auditoria', 'hallazgos', 'evidencias', 'rondas_aprobacion', 'decisiones_aprobacion']
        return {t: db.connection().exec_driver_sql('SELECT * FROM ' + t + ' ORDER BY id').all() for t in tables}


def test_seed_is_idempotent_preserves_rows_and_files(seeded, mysql_factory, credentials_file, demo_accounts):
    before = snapshot(mysql_factory)
    files = {p.relative_to(seeded.base_path): p.read_bytes() for p in seeded.base_path.rglob('*') if p.is_file()}
    assert demo.seed(factory=mysql_factory, credentials_file=credentials_file, storage=seeded, with_dataset=True) == 0
    assert snapshot(mysql_factory) == before
    assert {p.relative_to(seeded.base_path): p.read_bytes() for p in seeded.base_path.rglob('*') if p.is_file()} == files
    with mysql_factory() as db:
        for email, role, name, password in demo_accounts:
            user = db.scalar(select(Usuario).where(Usuario.correo_normalizado == email))
            assert user.rol == role and user.activo and verify_password(password, user.password_hash)
        assert db.scalar(select(func.count()).select_from(Usuario)) == 4
        assert db.scalar(select(func.count()).select_from(Area)) == 1


@pytest.mark.parametrize('field,value', [('rol', 'AUDITOR_EXTERNO'), ('activo', False), ('nombre', 'Existing non-demo identity'), ('password_hash', 'not-a-hash')])
def test_identity_conflict_never_overwrites(seeded, mysql_factory, field, value, credentials_file, demo_accounts):
    with mysql_factory() as db:
        user = db.scalar(select(Usuario).where(Usuario.correo_normalizado == demo_accounts[0][0]))
        setattr(user, field, value); db.commit()
    before = snapshot(mysql_factory)
    with pytest.raises(demo.DemoConflict):
        demo.seed(factory=mysql_factory, credentials_file=credentials_file, storage=seeded, with_dataset=True)
    assert snapshot(mysql_factory) == before


def test_concurrent_seeds_create_one_dataset(clean_temporary_schema, mysql_factory, tmp_path, monkeypatch, credentials_file):
    monkeypatch.setattr(demo.settings, 'app_env', 'development')
    storage = StorageService(tmp_path / 'storage')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: demo.seed(factory=mysql_factory, credentials_file=credentials_file, storage=storage, with_dataset=True), range(2)))
    assert sorted(results) == [0, 4]
    with mysql_factory() as db:
        assert db.scalar(select(func.count()).select_from(VersionDocumento)) == 1


def test_demo_http_login_scope_escalation_and_admin_integrity(seeded, mysql_factory, monkeypatch, demo_accounts):
    from app.services.documento_service import documento_service
    from app.routers import documentos
    monkeypatch.setattr(documento_service, 'storage', seeded)
    monkeypatch.setattr(documentos, 'storage_service', seeded)
    def sessions():
        with mysql_factory() as db:
            yield db
    app.dependency_overrides[get_db] = sessions
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            headers = []
            for email, role, _, password in demo_accounts:
                login = client.post('/api/v1/auth/login', json={'correo': email, 'password': password})
                assert login.status_code == 200
                auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
                assert client.get('/api/v1/auth/me', headers=auth).json()['rol'] == role
                headers.append(auth)
            admin, owner = headers[:2]
            global_docs = client.get('/api/v1/documentos', headers=admin).json()
            owned_docs = client.get('/api/v1/documentos', headers=owner).json()
            assert len(global_docs) == 2 and len(owned_docs) == 1
            doc = owned_docs[0]; hidden = next(d for d in global_docs if d['id'] != doc['id'])
            audits = client.get('/api/v1/auditorias', headers=admin).json()
            assert len(audits) == 2
            for path in ('/usuarios', '/access-requests', '/auditorias', '/hallazgos', f"/auditorias/{audits[0]['id']}"):
                assert client.get('/api/v1' + path, headers=owner).status_code == 403
            assert client.get(f"/api/v1/documentos/{hidden['id']}", headers=owner).status_code == 404
            for path in ('/dashboard/resumen', '/analisis/resumen', '/aprobaciones'):
                assert client.get('/api/v1' + path, headers=admin).status_code == 200
                assert client.get('/api/v1' + path, headers=owner).status_code == 200
            for payload in ({'rol': 'ADMIN'}, {'usuario_id': 1}, {'sha256': '0'*64}, {'responsable_id': hidden['responsable_id']}):
                assert client.patch(f"/api/v1/documentos/{doc['id']}", headers=owner, json=payload).status_code in {403, 422}
            assert client.post('/api/v1/auditorias', headers=owner, json={
                'codigo': 'ATTACK', 'nombre': 'Attack', 'alcance': 'No', 'responsable_id': 1}).status_code == 403
            upload = client.post(f"/api/v1/documentos/{doc['id']}/versiones", headers=owner,
                data={'subido_por_id': str(hidden['responsable_id'])}, files={'archivo': ('demo.txt', b'Synthetic second version', 'text/plain')})
            assert upload.status_code == 201 and upload.json()['subido_por_id'] == doc['responsable_id']
            with mysql_factory() as db:
                event = db.scalar(select(EventoAuditoria).where(EventoAuditoria.accion == 'CREACION_VERSION').order_by(EventoAuditoria.id.desc()))
                assert event.actor_id == doc['responsable_id']
                round_ = db.scalar(select(RondaAprobacion))
                round_id, stamp = round_.id, round_.updated_at.isoformat()
            assert client.post(f'/api/v1/aprobaciones/{round_id}/decision', headers=admin,
                json={'estado': 'APPROVED', 'updated_at_esperado': stamp}).status_code in {403, 404, 409}
            for path in ('/eventos/1', f"/documentos/{doc['id']}/versiones/1", '/usuarios/1'):
                assert client.delete('/api/v1' + path, headers=admin).status_code in {404, 405}
            for auth in headers:
                assert client.post('/api/v1/auth/logout', headers=auth).status_code == 204
                assert client.get('/api/v1/auth/me', headers=auth).status_code == 401
    finally:
        app.dependency_overrides.clear()
