"""Phase 8 regressions on the guarded ephemeral MySQL/storage fixture."""
from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import app
from app.models.entities import Auditoria, Documento, Usuario, VersionDocumento
from app.schemas.documento import DocumentoUpdate
from app.services.documento_service import documento_service
from tests_unit.test_rbac_unit import rbac

MYSQL_RBAC = True


@pytest.mark.parametrize('payload', [
    {'titulo': None}, {'estado': None}, {'area_id': None}, {'responsable_id': None},
    {'estado': 'active'}, {'estado': 'ACTIVE '}, {'area_id': 0},
    {'responsable_id': 18446744073709551616}, {'descripcion': 'x' * 65536},
])
def test_invalid_document_patch_is_client_error_without_mutation(rbac, payload):
    _, db, _, _ = rbac
    before = db.get(Documento, 1).titulo
    with TestClient(app, raise_server_exceptions=False) as client:
        result = client.patch('/api/v1/documentos/1', json=payload)
    assert result.status_code == 422, result.text
    db.rollback()
    assert db.get(Documento, 1).titulo == before


@pytest.mark.parametrize('field', ['area_id', 'responsable_id'])
def test_nonexistent_document_reference_is_client_error(rbac, field):
    _, db, _, _ = rbac
    with TestClient(app, raise_server_exceptions=False) as client:
        result = client.patch('/api/v1/documentos/1', json={field: 99999})
    assert result.status_code in {400, 404, 409}, result.text
    db.rollback()
    assert getattr(db.get(Documento, 1), field) != 99999


@pytest.mark.parametrize('filename', ['x' * 256 + '.txt', 'bad\x00.txt', 'bad\n.txt',
    'x.' + 't' * 200, 'x.' + '\u0130' * 80])
def test_invalid_version_filename_is_client_error_and_no_orphan(rbac, filename):
    _, db, _, storage = rbac
    before = {p.relative_to(storage.base_path) for p in storage.base_path.rglob('*') if p.is_file()}
    with TestClient(app, raise_server_exceptions=False) as client:
        result = client.post('/api/v1/documentos/1/versiones', files={'archivo': (filename, b'phase8', 'text/plain')})
    assert result.status_code in {400, 422}, result.text
    db.rollback()
    assert db.scalar(select(func.count()).select_from(VersionDocumento).where(VersionDocumento.documento_id == 1)) == 2
    assert {p.relative_to(storage.base_path) for p in storage.base_path.rglob('*') if p.is_file()} == before


def test_upload_after_old_repeatable_read_snapshot_gets_next_number(rbac, mysql_factory):
    _, db, _, _ = rbac
    # Authentication starts a nonlocking snapshot before waiting on the document.
    assert db.scalar(select(func.max(VersionDocumento.numero_version)).where(VersionDocumento.documento_id == 1)) == 2
    with mysql_factory() as other:
        documento_service.crear_version_documento(other, 1, BytesIO(b'first'), 'first.txt', 1)
    version = documento_service.crear_version_documento(db, 1, BytesIO(b'second'), 'second.txt', 1)
    assert version.numero_version == 4
    assert db.get(Documento, 1).version_vigente_id == version.id


@pytest.mark.parametrize('operation', ['patch', 'upload'])
@pytest.mark.parametrize('revocation', ['owner', 'inactive', 'role'])
def test_document_write_rechecks_committed_revocation(rbac, mysql_factory, operation, revocation):
    _, db, _, storage = rbac
    assert db.get(Documento, 1).responsable_id == 4
    user = db.get(Usuario, 4)
    assert user.activo and user.rol == 'RESPONSABLE_AREA'
    with mysql_factory() as other:
        if revocation == 'owner':
            other.get(Documento, 1).responsable_id = 7
        elif revocation == 'inactive':
            other.get(Usuario, 4).activo = False
        else:
            other.get(Usuario, 4).rol = 'AUDITOR_EXTERNO'
        other.commit()
    before = {p for p in storage.base_path.rglob('*') if p.is_file()}
    with pytest.raises(HTTPException) as rejected:
        if operation == 'patch':
            documento_service.actualizar_cabecera(db, 1, DocumentoUpdate(titulo='Unauthorized phase8'), 4)
        else:
            documento_service.crear_version_documento(db, 1, BytesIO(b'unauthorized'), 'phase8.txt', 4)
    assert rejected.value.status_code in {401, 403, 404}
    db.rollback()
    assert db.get(Documento, 1).titulo != 'Unauthorized phase8'
    assert {p for p in storage.base_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('size,status', [(0,201),(16,201),(17,400)])
def test_document_upload_size_boundary_is_atomic(rbac, monkeypatch, size, status):
    from app.core.config import settings
    client, db, _, storage = rbac
    monkeypatch.setattr(settings, 'max_document_file_bytes', 16)
    before = {p for p in storage.base_path.rglob('*') if p.is_file()}
    response = client.post('/api/v1/documentos/1/versiones', files={'archivo': ('boundary.txt', b'x'*size, 'text/plain')})
    assert response.status_code == status, response.text
    db.rollback()
    after = {p for p in storage.base_path.rglob('*') if p.is_file()}
    assert len(after-before) == int(status==201)


@pytest.mark.parametrize('operation', ['audit','finding','evidence'])
@pytest.mark.parametrize('revocation', ['inactive','role'])
def test_other_domain_writes_recheck_actor_after_old_snapshot(rbac, mysql_factory, operation, revocation):
    from app.services import auditoria_service, hallazgo_service, authorization_service as authz
    _, db, _, _ = rbac
    actor = db.get(Usuario, 2)
    audit = db.get(Auditoria, 1)
    with mysql_factory() as other:
        current = other.get(Usuario, 2)
        if revocation=='inactive':
            current.activo=False
        else:
            current.rol='RESPONSABLE_AREA'
        other.commit()
    with pytest.raises(HTTPException) as result:
        if operation=='audit':
            auditoria_service.resource(db, actor, audit.id, action='auditoria.create', locking=True)
        elif operation=='finding':
            hallazgo_service.lock_audit(db, actor, audit.id, 'hallazgo.create')
        else:
            authz.authorize_evidence_references(db, actor, audit.id, None, None)
    assert result.value.status_code in {403,404}
    db.rollback()


def test_analysis_fresh_barrier_with_single_pool_connection(rbac, mysql_factory):
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from fastapi import Response
    from app.routers.analisis import evaluate
    from app.schemas.analisis import AnalysisContext
    from app.services import analisis_service
    _, fixture, _, _ = rbac
    fixture.rollback()
    url = mysql_factory.kw['bind'].url
    engine = create_engine(url, pool_size=1, max_overflow=0, pool_timeout=.2,
        connect_args={'init_command': "SET time_zone='+00:00'"})
    @event.listens_for(engine, 'checkout')
    def guard(connection, *args):
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE()')
            assert cursor.fetchone()[0] == url.database != 'sistema_trazabilidad'
    try:
        with Session(engine) as db:
            actor = db.get(Usuario, 1)
            context = AnalysisContext()
            result = evaluate(db, actor, context, Response(),
                              lambda stamp: analisis_service.summary(db, actor, context, stamp))
            assert result.total >= 0
            assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize('state', ['completed','COMPLETED ','cancelled','CANCELLED '])
@pytest.mark.parametrize('operation', ['evidence','approval'])
def test_legacy_terminal_audit_alias_cannot_accept_writes(rbac, state, operation):
    from app.models.entities import RondaAprobacion
    client, db, _, _ = rbac
    db.get(Auditoria,1).estado=state
    db.commit()
    if operation=='evidence':
        result=client.post('/api/v1/evidencias/logica',json=dict(auditoria_id=1,titulo='Legacy attack',tipo='NOTE'))
    else:
        stamp=db.get(RondaAprobacion,1).updated_at.isoformat()
        result=client.post('/api/v1/aprobaciones/1/iniciar',json=dict(estado_esperado='PENDING',updated_at_esperado=stamp))
    assert result.status_code==409,result.text


@pytest.mark.parametrize('state', ['archived','ARCHIVED ','obsolete','OBSOLETE '])
def test_legacy_document_alias_cannot_accept_version(rbac, state):
    client, db, _, storage = rbac
    db.get(Documento,1).estado=state;db.commit()
    before={p for p in storage.base_path.rglob('*') if p.is_file()}
    result=client.post('/api/v1/documentos/1/versiones',files={'archivo':('legacy.txt',b'legacy')})
    assert result.status_code==400,result.text
    assert {p for p in storage.base_path.rglob('*') if p.is_file()}==before


@pytest.mark.parametrize('actor_id', [1, 2, 3, 4, 5])
def test_analysis_disk_spill_preserves_results_and_scope(rbac, actor_id):
    from datetime import datetime, timezone
    from app.schemas.analisis import AnalysisFilters
    from app.services import analisis_service
    _, db, _, _ = rbac
    actor = db.get(Usuario, actor_id)
    filters = AnalysisFilters(limit=100)
    stamp = datetime.now(timezone.utc)
    expected = analisis_service.page(db, actor, filters, stamp).model_dump()
    connection = db.connection()
    original = connection.exec_driver_sql('SELECT @@SESSION.tmp_table_size').scalar_one()
    try:
        # Session-local only, on the factory-guarded disposable schema. Force the
        # derived tables through the on-disk path that exposed MySQL error 1146.
        connection.exec_driver_sql('SET SESSION tmp_table_size=1024')
        for _ in range(2):
            assert analisis_service.page(db, actor, filters, stamp).model_dump() == expected
    finally:
        connection.exec_driver_sql('SET SESSION tmp_table_size=%s', (original,))


@pytest.mark.parametrize('resource', ['evidencias', 'auditorias', 'hallazgos', 'aprobaciones'])
def test_extreme_resource_id_is_client_error(rbac, resource):
    client, _, _, _ = rbac
    response = client.get('/api/v1/' + resource + '/' + str(10 ** 400))
    assert response.status_code in {400, 404, 422}, response.text


def test_extreme_evidence_reference_is_client_error(rbac):
    client, _, _, _ = rbac
    response = client.post('/api/v1/evidencias/logica', json=dict(
        auditoria_id=10 ** 400, titulo='Extreme reference', tipo='NOTE'))
    assert response.status_code in {400, 404, 422}, response.text


@pytest.mark.parametrize('role', ['admin', 'APROBADOR ', 'LEGACY'])
def test_login_rejects_noncanonical_role_without_creating_session(rbac, role):
    from app.core.security import hash_password
    from app.models.auth import AuthSession
    client, db, _, _ = rbac
    password = 'SyntheticPhase8Password!2026'
    actor = db.get(Usuario, 2)
    email = actor.correo
    original_role = actor.rol
    if role == 'LEGACY':
        connection = db.connection()
        schema = connection.exec_driver_sql('SELECT DATABASE()').scalar_one()
        assert schema.startswith('sistema_trazabilidad_test_auth_') and schema != 'sistema_trazabilidad'
        # A corrupt historical row cannot be seeded with the normal role CHECK.
        # Only this disposable schema is altered and enforcement is restored.
        connection.exec_driver_sql('ALTER TABLE usuarios ALTER CHECK ck_usuarios_rol NOT ENFORCED')
        db.commit()
    actor.rol = role
    actor.password_hash = hash_password(password)
    db.commit()
    try:
        before = db.scalar(select(func.count()).select_from(AuthSession))
        response = client.post('/api/v1/auth/login', json=dict(correo=email, password=password))
        assert response.status_code == 401
        db.rollback()
        assert db.scalar(select(func.count()).select_from(AuthSession)) == before
    finally:
        if role == 'LEGACY':
            db.rollback()
            db.get(Usuario, 2).rol = original_role
            db.commit()
            connection = db.connection()
            assert connection.exec_driver_sql('SELECT DATABASE()').scalar_one() == schema
            connection.exec_driver_sql('ALTER TABLE usuarios ALTER CHECK ck_usuarios_rol ENFORCED')
            db.commit()


@pytest.mark.parametrize('role', ['auditor_interno', 'AUDITOR_INTERNO '])
def test_audit_cannot_assign_noncanonical_legacy_auditor(rbac, role):
    client, db, _, _ = rbac
    db.get(Usuario, 2).rol = role
    db.commit()
    response = client.post('/api/v1/auditorias', json=dict(
        codigo='PHASE8_ROLE', nombre='Synthetic legacy role', alcance='Synthetic scope', responsable_id=2))
    assert response.status_code == 404, response.text


@pytest.mark.parametrize('role', ['aprobador', 'APROBADOR '])
def test_approver_catalog_excludes_noncanonical_roles(rbac, role):
    client, db, _, _ = rbac
    db.get(Usuario, 5).rol = role
    db.commit()
    response = client.get('/api/v1/aprobaciones/aprobadores')
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    assert 5 not in {item['id'] for item in payload}


@pytest.mark.parametrize('kind', ['document', 'evidence'])
@pytest.mark.parametrize('declared_length', [None, '1'])
def test_upload_total_body_limit_cannot_be_bypassed_by_unused_file(rbac, monkeypatch, kind, declared_length):
    from app.core.config import settings
    client, db, _, storage = rbac
    monkeypatch.setattr(settings, 'max_document_file_bytes', 16)
    monkeypatch.setattr(settings, 'max_evidence_file_bytes', 16)
    before = {p for p in storage.base_path.rglob('*') if p.is_file()}
    path = '/api/v1/documentos/1/versiones' if kind == 'document' else '/api/v1/evidencias/archivo'
    data = {} if kind == 'document' else dict(auditoria_id='1', titulo='Synthetic body limit')
    headers = {} if declared_length is None else {'Content-Length': declared_length}
    response = client.post(path, data=data, headers=headers, files={
        'archivo': ('selected.txt', b'chosen', 'text/plain'),
        'unused': ('unused.bin', b'x' * (128 * 1024 + 17), 'application/octet-stream')})
    assert response.status_code in {400, 413}, response.status_code
    db.rollback()
    assert {p for p in storage.base_path.rglob('*') if p.is_file()} == before


def test_oversized_json_is_rejected_before_schema_expansion(rbac):
    client, _, _, _ = rbac
    response = client.post('/api/v1/documentos', content='{"unused":"' + 'x' * (1024 * 1024) + '"}',
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 413


def test_deep_json_is_client_error_without_traceback(rbac):
    client, _, _, _ = rbac
    response = client.post('/api/v1/documentos', content='[' * 2000 + '0' + ']' * 2000,
                           headers={'Content-Type': 'application/json'})
    assert response.status_code in {400, 422}
    assert 'Traceback' not in response.text
