"""HTTP RBAC tests with real SQL scopes, memory SQLite and temporary files.
SQLite DDL is a test-only copy; production metadata and engines are untouched.
"""
import io
from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, MetaData, Integer, DateTime, select, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db, engine as application_engine
from app.api.dependencies import current_user
from app.main import app
from app.models.entities import (Usuario, Area, Auditoria, Documento, VersionDocumento,
    DocumentoAuditoria, RondaAprobacion, DecisionAprobacion, Evidencia, EventoAuditoria)
from app.services.storage_service import StorageService
from app.services.documento_service import documento_service
from app.services.evidencia_service import evidencia_service
from app.routers import documentos, evidencias
from app.services import authorization_service as authz

@pytest.fixture
def rbac(tmp_path, monkeypatch, request):
    def forbidden(*args, **kwargs):
        raise AssertionError('Production engine forbidden')
    event.listen(application_engine, 'do_connect', forbidden)
    mysql = getattr(request.module, 'MYSQL_RBAC', False)
    if mysql:
        request.getfixturevalue('clean_temporary_schema')
        engine = request.getfixturevalue('mysql_factory').kw['bind']
    else:
        engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        ddl = MetaData()
        for table in Base.metadata.tables.values():
            # This SQLite copy covers domain RBAC only. Authentication tables use
            # MySQL collation/locking and are exercised on real temporary MySQL.
            if table.name in {'auth_sessions', 'auth_login_limits', 'access_requests',
                              'auth_action_limits', 'auth_action_tokens', 'auth_mail_jobs'}: continue
            copy = table.to_metadata(ddl)
            for column in copy.columns:
                column.server_default = None
                if isinstance(column.type, Integer): column.type = Integer()
                if isinstance(column.type, DateTime): column.type = DateTime()
        ddl.create_all(engine)
    db = Session(engine)
    roles = ['ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO', 'RESPONSABLE_AREA', 'APROBADOR', 'AUDITOR_INTERNO', 'RESPONSABLE_AREA']
    for i, role in enumerate(roles, 1):
        db.add(Usuario(id=i, nombre=f'User {i}', correo=f'{i}@example.invalid', correo_normalizado=f'{i}@example.invalid', password_hash='unused', rol=role, activo=True))
    db.add(Area(id=1, codigo='AREA', nombre='Area', activa=True))
    for i, owner in [(1,2),(2,6),(3,3),(4,2)]:
        db.add(Auditoria(id=i,codigo=f'A{i}',nombre=f'Audit {i}',alcance='Test', responsable_id=owner, created_by_id=1,estado='PLANNED'))
    for i, owner in [(1,4),(2,7),(3,4),(4,7)]:
        db.add(Documento(id=i,codigo=f'D{i}',titulo=f'Document {i}',tipo='TEST',estado='ACTIVE',area_id=1,responsable_id=owner,created_by_id=1))
    db.flush()
    storage = StorageService(tmp_path)
    for i, doc in [(1,1),(2,1),(3,2),(4,3),(5,4)]:
        stored=storage.save_file(io.BytesIO(b'fixture'), f'{i}.txt')
        db.add(VersionDocumento(id=i,documento_id=doc,numero_version=2 if i==2 else 1,storage_key=stored.storage_key,nombre_original=f'{i}.txt',mime_type='text/plain',tamano_bytes=7,sha256=stored.sha256,subido_por_id=1))
    db.flush()
    db.get(Documento,1).version_vigente_id=2
    for i,a,d,v in [(1,1,1,1),(2,2,2,3),(3,3,3,4),(4,4,4,5)]:
        db.add(DocumentoAuditoria(id=i,auditoria_id=a,documento_id=d,version_documento_id=v,proposito='TEST',asociado_por_id=1))
    db.add(RondaAprobacion(id=1,version_documento_id=1,numero_ronda=1,solicitada_por_id=1,estado='PENDING'))
    db.flush()
    db.add(DecisionAprobacion(id=1,ronda_aprobacion_id=1,aprobador_id=5,estado='PENDING'))
    for i,a,d in [(1,1,1),(2,2,2),(3,3,3),(4,1,2)]:
        db.add(Evidencia(id=i,auditoria_id=a,documento_id=d,tipo='NOTE',titulo=f'Evidence {i}',registrada_por_id=1))
    db.commit()
    actor={'id':1}
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[current_user]=lambda:db.get(Usuario,actor['id'])
    monkeypatch.setattr(documento_service,'storage',storage)
    monkeypatch.setattr(evidencia_service,'storage',storage)
    monkeypatch.setattr(documentos,'storage_service',storage)
    monkeypatch.setattr(evidencias,'storage_service',storage)
    try:
        with TestClient(app,raise_server_exceptions=True) as client:
            yield client, db, actor, storage
    finally:
        app.dependency_overrides.clear()
        db.close()
        if not mysql: engine.dispose()
        event.remove(application_engine,'do_connect',forbidden)

def ids(response):
    assert response.status_code==200,response.text
    return [r['id'] for r in response.json()]

@pytest.mark.parametrize('actor,expected',[(1,[1,2,3,4]),(2,[1,4]),(3,[3])])
def test_audit_scopes(rbac,actor,expected):
    c,db,user,_=rbac;user['id']=actor
    assert ids(c.get('/api/v1/auditorias'))==expected

@pytest.mark.parametrize('actor,responsible,status',[(2,2,201),(2,6,403),(1,6,201),(1,3,201),(3,3,403),(1,4,404)])
def test_audit_creation(rbac,actor,responsible,status):
    c,db,user,_=rbac;user['id']=actor
    r=c.post('/api/v1/auditorias',json={'codigo':'NEW','nombre':'New audit','alcance':'Test','responsable_id':responsible,'created_by_id':7})
    assert r.status_code==status,r.text
    if status==201:
        assert r.json()['created_by_id']==actor
        assert db.scalar(select(EventoAuditoria)).actor_id==actor

@pytest.mark.parametrize('actor,allowed,denied',[(2,1,2),(3,3,1),(4,1,2),(5,1,3)])
def test_document_idor(rbac,actor,allowed,denied):
    c,db,user,_=rbac;user['id']=actor
    assert c.get(f'/api/v1/documentos/{allowed}').status_code==200
    assert c.get(f'/api/v1/documentos/{denied}').status_code==404

@pytest.mark.parametrize('actor,expected',[(1,[1,2,3,4]),(2,[1,4]),(3,[3]),(4,[1,3]),(5,[1])])
def test_document_lists_before_pagination(rbac,actor,expected):
    c,db,user,_=rbac;user['id']=actor
    assert ids(c.get('/api/v1/documentos'))==expected
    for offset,item in enumerate(expected):
        assert ids(c.get(f'/api/v1/documentos?limit=1&offset={offset}'))==[item]
    assert ids(c.get(f'/api/v1/documentos?limit=1&offset={len(expected)}'))==[]

def test_approver_nested_and_downloads(rbac):
    c,db,user,storage=rbac;user['id']=5
    for path in ['/api/v1/documentos','/api/v1/documentos/1?incluir_versiones=true']:
        response=c.get(path);assert response.status_code==200,response.text
        doc=response.json()[0] if isinstance(response.json(),list) else response.json()
        assert doc['version_vigente_id'] is None and doc['version_vigente'] is None
        if 'versiones' in doc: assert [v['id'] for v in doc['versiones']]==[1]
    assert ids(c.get('/api/v1/documentos/1/versiones'))==[1]
    assert c.get('/api/v1/documentos/1/versiones/1/descargar').content==b'fixture'
    assert c.get('/api/v1/documentos/1/versiones/2/descargar').status_code==404
    assert c.get('/api/v1/documentos/2/versiones/1/descargar').status_code==404

@pytest.mark.parametrize('actor,expected',[(1,[1,2,3,4]),(2,[1]),(3,[3])])
def test_evidence_scope_and_pagination(rbac,actor,expected):
    c,db,user,_=rbac;user['id']=actor
    assert ids(c.get('/api/v1/evidencias'))==expected
    assert ids(c.get('/api/v1/evidencias?limit=1'))==expected[:1]
    if actor!=1:
        assert c.get('/api/v1/evidencias/2').status_code==404
        assert c.get('/api/v1/evidencias/2/descargar').status_code==404

@pytest.mark.parametrize('actor,audit,document,version,status',[(2,1,1,None,201),(3,3,3,4,201),(2,2,2,None,404),(3,1,1,None,404),(2,1,4,None,404),(2,1,None,5,404),(1,1,2,None,404),(2,1,1,3,404)])
@pytest.mark.parametrize('file',[False,True])
def test_evidence_consistency_and_actor(rbac,actor,audit,document,version,status,file,monkeypatch):
    c,db,user,storage=rbac;user['id']=actor
    payload={'auditoria_id':audit,'titulo':'New evidence'}
    if document is not None: payload['documento_id']=document
    if version is not None: payload['version_documento_id']=version
    if not file and version == 5 and document is None: payload['documento_id']=4
    if status!=201:
        guard=Mock(side_effect=AssertionError('Unauthorized storage write'))
        monkeypatch.setattr(storage,'save_file',guard)
    if file:
        r=c.post('/api/v1/evidencias/archivo',data={**payload,'registrada_por_id':7},files={'archivo':('new.txt',b'new')})
    else:
        r=c.post('/api/v1/evidencias/logica?registrada_por_id=7',json={**payload,'tipo':'NOTE'})
    assert r.status_code==status,r.text
    if status==201:
        assert r.json()['registrada_por_id']==actor
        assert db.scalar(select(EventoAuditoria)).actor_id==actor
    else: guard.assert_not_called()

def test_document_create_update_upload_actor_and_denials(rbac,monkeypatch):
    c,db,user,storage=rbac;user['id']=4
    payload={'codigo':'NEW','titulo':'New document','tipo':'TEST','area_id':1,'responsable_id':7}
    assert c.post('/api/v1/documentos?creador_id=7',json=payload).status_code==403
    payload['responsable_id']=4
    r=c.post('/api/v1/documentos?creador_id=7',json=payload)
    assert r.status_code==201,r.text
    assert r.json()['created_by_id']==4
    r=c.patch('/api/v1/documentos/1?editor_id=7',json={'titulo':'Changed'})
    assert r.status_code==200,r.text
    assert r.json()['updated_by_id']==4
    assert c.patch('/api/v1/documentos/2',json={'titulo':'Changed'}).status_code==404
    assert c.patch('/api/v1/documentos/1',json={'responsable_id':7}).status_code==403
    assert c.patch('/api/v1/documentos/1',json={'responsable_id':None}).status_code==422
    r=c.post('/api/v1/documentos/1/versiones',data={'subido_por_id':7},files={'archivo':('new.txt',b'new')})
    assert r.status_code==201,r.text
    assert r.json()['subido_por_id']==4
    guard=Mock(side_effect=AssertionError('Unauthorized storage write'))
    monkeypatch.setattr(storage,'save_file',guard)
    assert c.post('/api/v1/documentos/2/versiones',files={'archivo':('bad.txt',b'bad')}).status_code==404
    guard.assert_not_called()
    assert all(e.actor_id==4 for e in db.scalars(select(EventoAuditoria)))

@pytest.mark.parametrize('actor,path,method',[(3,'auditorias','post'),(2,'documentos','post'),(5,'documentos/1','patch'),(4,'evidencias/logica','post'),(2,'documentos/1/historial','get'),(5,'usuarios','get')])
def test_vertical_denials(rbac,actor,path,method):
    c,db,user,_=rbac;user['id']=actor
    payload={'codigo':'NEW','nombre':'New audit','alcance':'Test','responsable_id':actor} if path=='auditorias' else {'codigo':'NEW','titulo':'New document','tipo':'TEST','area_id':1,'responsable_id':actor} if path=='documentos' else {'auditoria_id':1,'titulo':'Test','tipo':'NOTE'} if path=='evidencias/logica' else {'titulo':'Changed'}
    r=getattr(c,method)('/api/v1/'+path,**({'json':payload} if method!='get' else {}))
    assert r.status_code==403,r.text

@pytest.mark.parametrize('actor',[1,2,3,4,5])
def test_catalogs(rbac,actor):
    c,db,user,_=rbac;user['id']=actor
    assert ids(c.get('/api/v1/areas'))==[1]
    r=c.get('/api/v1/usuarios')
    if actor==1: assert ids(r)==list(range(1,8))
    elif actor==2: assert ids(r)==[2,3,6]
    else: assert r.status_code==403

def test_missing_identity_is_401(rbac):
    c,db,user,_=rbac
    del app.dependency_overrides[current_user]
    for path in ['documentos/1','evidencias/1/descargar','areas','auditorias']:
        assert c.get('/api/v1/'+path).status_code==401

def test_unknown_role_and_action_denied():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err: authz.require_permission(Usuario(rol='UNKNOWN'),'documento.read')
    assert err.value.status_code==403
    with pytest.raises(HTTPException): authz.require_permission(Usuario(rol='ADMIN'),'unknown.action')


def test_admin_operations_and_reassignment(rbac):
    c, db, user, storage = rbac
    payload = {'codigo': 'NEW', 'titulo': 'Admin document', 'tipo': 'TEST', 'area_id': 1, 'responsable_id': 7}
    r = c.post('/api/v1/documentos', json=payload)
    assert r.status_code == 201, r.text
    assert r.json()['created_by_id'] == 1
    r = c.patch('/api/v1/documentos/2', json={'responsable_id': 4})
    assert r.status_code == 200 and r.json()['responsable_id'] == 4
    r = c.post('/api/v1/documentos/2/versiones', files={'archivo': ('admin.txt', b'admin')})
    assert r.status_code == 201, r.text
    assert r.json()['subido_por_id'] == 1
    assert c.get('/api/v1/documentos/2/historial').status_code == 200
    assert c.get('/api/v1/documentos/2/versiones/3/descargar').status_code == 200
    assert c.get('/api/v1/evidencias/2').status_code == 200
    assert all(e.actor_id == 1 for e in db.scalars(select(EventoAuditoria)))


@pytest.mark.parametrize('actor,document,version', [(2, 1, 1), (3, 3, 4), (4, 1, 1)])
def test_download_scope_before_filesystem(rbac, monkeypatch, actor, document, version):
    c, db, user, storage = rbac
    user['id'] = actor
    assert c.get(f'/api/v1/documentos/{document}/versiones/{version}/descargar').content == b'fixture'
    guard = Mock(side_effect=AssertionError('Unauthorized filesystem lookup'))
    monkeypatch.setattr(storage, 'get_absolute_path', guard)
    assert c.get('/api/v1/documentos/2/versiones/3/descargar').status_code == 404
    guard.assert_not_called()


def test_file_evidence_download_scope(rbac, monkeypatch):
    c, db, user, storage = rbac
    user['id'] = 2
    r = c.post('/api/v1/evidencias/archivo', data={'auditoria_id': 1, 'titulo': 'File evidence'}, files={'archivo': ('e.txt', b'evidence')})
    assert r.status_code == 201, r.text
    evidence_id = r.json()['id']
    assert c.get(f'/api/v1/evidencias/{evidence_id}/descargar').content == b'evidence'
    guard = Mock(side_effect=AssertionError('Unauthorized filesystem lookup'))
    monkeypatch.setattr(storage, 'get_absolute_path', guard)
    user['id'] = 3
    assert c.get(f'/api/v1/evidencias/{evidence_id}/descargar').status_code == 404
    user['id'] = 4
    assert c.get(f'/api/v1/evidencias/{evidence_id}/descargar').status_code == 403
    guard.assert_not_called()


def test_current_assigned_version_and_multiple_assignments(rbac):
    c, db, user, storage = rbac
    db.add(RondaAprobacion(id=2, version_documento_id=2, numero_ronda=1, solicitada_por_id=1, estado='PENDING'))
    db.flush()
    db.add(DecisionAprobacion(ronda_aprobacion_id=2, aprobador_id=5, estado='PENDING'))
    db.commit()
    user['id'] = 5
    r = c.get('/api/v1/documentos/1?incluir_versiones=true')
    assert r.status_code == 200, r.text
    assert r.json()['version_vigente_id'] == 2
    assert r.json()['version_vigente']['id'] == 2
    assert [v['id'] for v in r.json()['versiones']] == [1, 2]
    assert ids(c.get('/api/v1/documentos')) == [1]


def test_inactive_auditor_not_eligible(rbac):
    c, db, user, storage = rbac
    db.get(Usuario, 6).activo = False
    db.commit()
    user['id'] = 2
    assert ids(c.get('/api/v1/usuarios')) == [2, 3]
    user['id'] = 1
    r = c.post('/api/v1/auditorias', json={'codigo': 'NEW', 'nombre': 'Audit', 'alcance': 'Test', 'responsable_id': 6})
    assert r.status_code == 404


@pytest.mark.parametrize('actor,status', [(1, 200), (2, 200), (3, 403), (4, 403), (5, 403)])
def test_optional_eligible_audit_catalog(rbac, actor, status):
    c, db, user, _ = rbac
    db.get(Usuario, 6).activo = False
    db.commit()
    user['id'] = actor
    response = c.get('/api/v1/usuarios?elegibles_auditoria=true')
    assert response.status_code == status
    if status == 200:
        assert ids(response) == [2, 3]
        assert all(set(row) == {'id', 'nombre', 'activo'} for row in response.json())
    if actor == 1:
        assert ids(c.get('/api/v1/usuarios')) == list(range(1, 8))
        assert ids(c.get('/api/v1/usuarios?elegibles_auditoria=false')) == list(range(1, 8))


def test_version_permission_refreshes_locked_document(rbac, monkeypatch):
    """A stale ORM owner must never authorize a write after reassignment."""
    from sqlalchemy import update
    c, db, user, storage = rbac
    user['id'] = 4
    stale = db.get(Documento, 1)
    assert stale.responsable_id == 4
    with Session(db.bind) as other:
        other.execute(update(Documento).where(Documento.id == 1).values(responsable_id=7))
        other.commit()
    assert stale.responsable_id == 4
    guard = Mock(side_effect=AssertionError('Unauthorized storage write'))
    monkeypatch.setattr(storage, 'save_file', guard)
    r = c.post('/api/v1/documentos/1/versiones', files={'archivo': ('stale.txt', b'stale')})
    assert r.status_code == 404, r.text
    assert stale.responsable_id == 7
    guard.assert_not_called()


def test_foreign_archived_document_returns_404_before_business_checks(rbac, monkeypatch):
    c, db, user, storage = rbac
    db.get(Documento, 2).estado = 'ARCHIVED'
    db.commit()
    user['id'] = 4
    guard = Mock(side_effect=AssertionError('Unauthorized storage write'))
    monkeypatch.setattr(storage, 'save_file', guard)
    assert c.post('/api/v1/documentos/2/versiones', files={'archivo': ('bad.txt', b'bad')}).status_code == 404
    guard.assert_not_called()


def test_audit_and_evidence_offsets(rbac):
    c, db, user, storage = rbac
    user['id'] = 2
    assert ids(c.get('/api/v1/auditorias?limit=1&offset=1')) == [4]
    assert ids(c.get('/api/v1/evidencias?limit=1&offset=1')) == []


@pytest.mark.parametrize('method,path,payload', [
    ('post', 'documentos', {'codigo': 'NEW', 'titulo': 'Test', 'tipo': 'TEST', 'area_id': 1, 'responsable_id': 4}),
    ('patch', 'documentos/1', {'titulo': 'Updated'}),
    ('post', 'auditorias', {'codigo': 'NEW', 'nombre': 'Test', 'alcance': 'Test', 'responsable_id': 2}),
    ('post', 'evidencias/logica', {'auditoria_id': 1, 'titulo': 'Test', 'tipo': 'NOTE'}),
])
def test_write_routes_require_identity(rbac, method, path, payload):
    c, db, user, storage = rbac
    del app.dependency_overrides[current_user]
    assert getattr(c, method)('/api/v1/' + path, json=payload).status_code == 401
