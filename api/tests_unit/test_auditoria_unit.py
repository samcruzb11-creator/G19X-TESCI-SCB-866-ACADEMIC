"""The same audit business/security contract runs on SQLite and temporary MySQL."""
from datetime import datetime, date
import pytest
from sqlalchemy import select, func, event

from tests_unit.test_rbac_unit import rbac
from app.main import app
from app.api.dependencies import current_user
from app.models.entities import Auditoria, Usuario, EventoAuditoria
from app.services import auditoria_service as service


def current(client, audit_id=1):
    result = client.get(f'/api/v1/auditorias/{audit_id}')
    assert result.status_code == 200
    return result.json()


def state(client, target, audit_id=1, source=None):
    row = source or current(client, audit_id)
    return client.post(f'/api/v1/auditorias/{audit_id}/estado', json={
        'estado': target, 'estado_esperado': row['estado'], 'updated_at_esperado': row['updated_at']})


@pytest.mark.parametrize('actor,expected', [(1,[1,2,3,4]), (2,[1,4]), (3,[3])])
def test_scoped_count_page_and_detail(rbac, actor, expected):
    c, db, user, _ = rbac; user['id'] = actor
    for offset, audit_id in enumerate(expected):
        r = c.get('/api/v1/auditorias', params={'limit':1,'offset':offset})
        assert r.status_code == 200 and int(r.headers['x-total-count']) == len(expected)
        assert [x['id'] for x in r.json()] == [audit_id]
        row = current(c, audit_id)
        assert row['responsable']['id'] == row['responsable_id']
        assert 'correo' not in row['responsable'] and 'password_hash' not in row['responsable']
    hidden = set(range(1,5))-set(expected)
    for audit_id in hidden | {999}: assert c.get(f'/api/v1/auditorias/{audit_id}').status_code == 404


@pytest.mark.parametrize('actor', [2,3,4,5,6,7])
@pytest.mark.parametrize('kind', ['patch','state','history'])
def test_new_operations_admin_only_direct_call(rbac, actor, kind):
    c,db,user,_=rbac; row=current(c); user['id']=actor
    if kind=='patch':r=c.patch('/api/v1/auditorias/1',json={'nombre':'No','updated_at_esperado':row['updated_at']})
    elif kind=='state':r=state(c,'IN_PROGRESS',source=row)
    else:r=c.get('/api/v1/auditorias/1/historial')
    assert r.status_code==403
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('actor',[4,5])
def test_no_area_role_read_grant(rbac,actor):
    c,db,user,_=rbac;user['id']=actor
    assert c.get('/api/v1/auditorias').status_code==403
    assert c.get('/api/v1/auditorias/1').status_code==403


@pytest.mark.parametrize('query', [{'limit':201},{'limit':0},{'offset':-1},{'offset':10001},
    {'orden':'id; DROP TABLE usuarios'}, {'estado':'BORRADOR'}, {'sort':'nombre'},
    {'responsable_id':0},{'area_id':-1},{'inicio_desde':'2026-02-02','inicio_hasta':'2026-01-01'},
    {'tipo':'made-up'}, {'q':'x'*101}])
def test_filter_validation(rbac,query):
    assert rbac[0].get('/api/v1/auditorias',params=query).status_code==422


@pytest.mark.parametrize('q', ["' OR 1=1 --", '%', '_', '\\'])
def test_search_is_bound_and_wildcards_literal(rbac,q):
    c,_,user,_=rbac;user['id']=2
    r=c.get('/api/v1/auditorias',params={'q':q})
    assert r.status_code==200 and r.json()==[] and r.headers['x-total-count']=='0'


def test_filters_dates_area_order_do_not_duplicate(rbac):
    c,db,user,_=rbac;user['id']=2
    db.get(Auditoria,1).fecha_inicio_prevista=date(2026,2,1);db.commit()
    r=c.get('/api/v1/auditorias',params={'area_id':1,'responsable_id':2,'estado':'PLANNED','orden':'-id'})
    assert [x['id'] for x in r.json()]==[4,1] and r.headers['x-total-count']=='2'
    assert [x['id'] for x in c.get('/api/v1/auditorias',params={'inicio_desde':'2026-01-01','inicio_hasta':'2026-03-01'}).json()]==[1]
    assert current(c)['areas']==[{'id':1,'nombre':'Area'}]


@pytest.mark.parametrize('field,value', [('codigo',' '),('codigo','x'*61),('nombre',' '),('nombre','x'*201),
    ('nombre','bad\x00name'),('alcance',' '),('alcance','x'*16001),('responsable_id',0),
    ('area_id',1),('tipo','INTERNAL'),('estado','COMPLETED'),('actor_id',1),('updated_by_id',1)])
def test_create_validation_and_mass_assignment(rbac,field,value):
    c=rbac[0];body={'codigo':'NEW','nombre':'New','alcance':'Scope','responsable_id':2};body[field]=value
    assert c.post('/api/v1/auditorias',json=body).status_code==422


def test_create_actor_and_duplicate_code(rbac):
    c,db,user,_=rbac;user['id']=2
    body={'codigo':' NEW ','nombre':' New audit ','alcance':'Scope','responsable_id':2,'created_by_id':1}
    r=c.post('/api/v1/auditorias',json=body);assert r.status_code==201,r.text
    assert r.json()['created_by_id']==2 and r.json()['codigo']=='NEW' and r.json()['estado']=='PLANNED'
    eventrow=db.scalar(select(EventoAuditoria));assert eventrow.actor_id==2 and eventrow.accion=='CREACION_AUDITORIA'
    assert c.post('/api/v1/auditorias',json=body).status_code==409


@pytest.mark.parametrize('responsible',[1,4,5,999])
def test_responsible_eligible_only(rbac,responsible):
    assert rbac[0].post('/api/v1/auditorias',json={'codigo':'NEW','nombre':'New','alcance':'Scope','responsable_id':responsible}).status_code==404


def test_inactive_responsible_refused(rbac):
    c,db,_,_=rbac;db.get(Usuario,2).activo=False;db.commit()
    assert c.post('/api/v1/auditorias',json={'codigo':'NEW','nombre':'New','alcance':'Scope','responsable_id':2}).status_code==404
    assert state(c,'IN_PROGRESS').status_code==404


def test_complete_cycle_and_events(rbac):
    c,db,_,_=rbac
    row=current(c)
    r=c.patch('/api/v1/auditorias/1',json={'nombre':'Edited','updated_at_esperado':row['updated_at']});assert r.status_code==200
    started=state(c,'IN_PROGRESS');assert started.status_code==200 and started.json()['iniciada_en']
    start_time=started.json()['iniciada_en']
    for target in ['IN_REVIEW','IN_PROGRESS','IN_REVIEW','COMPLETED']:
        r=state(c,target);assert r.status_code==200,r.text
    row=current(c);assert row['completada_en'] and row['iniciada_en']==start_time and row['updated_by_id']==1
    history=c.get('/api/v1/auditorias/1/historial');assert history.status_code==200
    assert len(history.json())==6 and history.json()[0]['accion']=='CIERRE_AUDITORIA'
    assert all(x['actor_id']==1 and 'actor_snapshot' not in x and 'correlation_id' not in x for x in history.json())
    assert len(c.get('/api/v1/auditorias/1/historial?limit=1&offset=1').json())==1
    assert c.patch('/api/v1/auditorias/1',json={'nombre':'Closed mutation','updated_at_esperado':row['updated_at']}).status_code==409
    assert state(c,'IN_PROGRESS').status_code==409
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==6


@pytest.mark.parametrize('initial,target',[('PLANNED','IN_REVIEW'),('PLANNED','COMPLETED'),
    ('IN_PROGRESS','COMPLETED'),('IN_PROGRESS','IN_PROGRESS'),('COMPLETED','IN_PROGRESS'),
    ('CANCELLED','IN_PROGRESS')])
def test_illegal_transitions(rbac,initial,target):
    c,db,_,_=rbac;db.get(Auditoria,1).estado=initial;db.commit()
    assert state(c,target).status_code==409
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


def test_stale_form_state_edit_and_logical_double_transition(rbac):
    c,db,_,_=rbac;old=current(c)
    assert state(c,'IN_PROGRESS',source=old).status_code==200
    assert state(c,'IN_PROGRESS',source=old).status_code==409
    assert c.patch('/api/v1/auditorias/1',json={'nombre':'Stale','updated_at_esperado':old['updated_at']}).status_code==409
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==1


@pytest.mark.parametrize('payload',[{}, {'estado':'COMPLETED'},{'created_by_id':9},{'updated_by_id':9},
    {'responsable_id':None},{'alcance':None},{'nombre':None},{'codigo':'Changed'},{'iniciada_en':'2026-01-01'}])
def test_patch_protected_empty_null_fields(rbac,payload):
    c=rbac[0];payload={**payload,'updated_at_esperado':current(c)['updated_at']}
    assert c.patch('/api/v1/auditorias/1',json=payload).status_code==422


def test_patch_date_merge_and_clear(rbac):
    c,db,_,_=rbac;row=db.get(Auditoria,1);row.fecha_inicio_prevista=date(2026,2,1);row.fecha_fin_prevista=date(2026,3,1);db.commit()
    old=current(c)
    assert c.patch('/api/v1/auditorias/1',json={'fecha_fin_prevista':'2026-01-01','updated_at_esperado':old['updated_at']}).status_code==422
    assert current(c)['fecha_fin_prevista']=='2026-03-01'
    r=c.patch('/api/v1/auditorias/1',json={'fecha_fin_prevista':None,'updated_at_esperado':old['updated_at']});assert r.status_code==200
    assert r.json()['fecha_fin_prevista'] is None


@pytest.mark.parametrize('operation',['create','edit','transition'])
def test_event_failure_rolls_back_business_change(rbac,monkeypatch,operation):
    c,db,_,_=rbac;row=current(c)
    def fail(*a,**kw):raise RuntimeError('SECRET sql/path/hash should never be exposed')
    monkeypatch.setattr(service,'_log_evento',fail)
    if operation=='create':r=c.post('/api/v1/auditorias',json={'codigo':'ROLLBACK','nombre':'New','alcance':'Scope','responsable_id':2})
    elif operation=='edit':r=c.patch('/api/v1/auditorias/1',json={'nombre':'Must rollback','updated_at_esperado':row['updated_at']})
    else:r=state(c,'IN_PROGRESS',source=row)
    assert r.status_code==500 and 'SECRET' not in r.text
    assert current(c)==row and db.scalar(select(func.count()).select_from(Auditoria))==4
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


def test_page_no_n_plus_one(rbac):
    c,db,_,_=rbac
    c.get('/api/v1/auditorias');statements=[]
    def record(conn,cursor,statement,parameters,context,many):statements.append(statement)
    event.listen(db.get_bind(),'before_cursor_execute',record)
    try:
        assert c.get('/api/v1/auditorias').status_code==200
    finally:event.remove(db.get_bind(),'before_cursor_execute',record)
    assert len(statements)<=4,statements


@pytest.mark.parametrize('method,path,body',[('get','auditorias/1',None),('get','auditorias/1/historial',None),
    ('patch','auditorias/1',{'nombre':'X','updated_at_esperado':'2026-01-01T00:00:00'}),
    ('post','auditorias/1/estado',{'estado':'IN_PROGRESS','estado_esperado':'PLANNED','updated_at_esperado':'2026-01-01T00:00:00'})])
def test_new_routes_require_identity(rbac,method,path,body):
    del app.dependency_overrides[current_user]
    assert rbac[0].request(method,'/api/v1/'+path,json=body).status_code==401


@pytest.mark.parametrize('target',['PLANNED','CANCELLED','BORRADOR'])
def test_unexposed_targets_rejected(rbac,target):
    assert state(rbac[0],target).status_code==422


@pytest.mark.parametrize('field',['actor_id','created_by_id','updated_by_id','completada_en','iniciada_en','nombre'])
def test_transition_mass_assignment_rejected(rbac,field):
    c=rbac[0];row=current(c)
    r=c.post('/api/v1/auditorias/1/estado',json={'estado':'IN_PROGRESS','estado_esperado':'PLANNED','updated_at_esperado':row['updated_at'],field:1})
    assert r.status_code==422


@pytest.mark.parametrize('verb',['patch','post','get'])
def test_missing_resource_mutation_history_uniform(rbac,verb):
    c=rbac[0];row=current(c)
    if verb=='patch':r=c.patch('/api/v1/auditorias/999',json={'nombre':'New','updated_at_esperado':row['updated_at']})
    elif verb=='post':r=state(c,'IN_PROGRESS',999,source=row)
    else:r=c.get('/api/v1/auditorias/999/historial')
    assert r.status_code==404 and r.json()['detail']=='Recurso no encontrado'


@pytest.mark.parametrize('state_name',['IN_REVIEW','COMPLETED','CANCELLED'])
def test_frozen_business_edit(rbac,state_name):
    c,db,_,_=rbac;db.get(Auditoria,1).estado=state_name;db.commit();row=current(c)
    assert c.patch('/api/v1/auditorias/1',json={'nombre':'Forbidden','updated_at_esperado':row['updated_at']}).status_code==409


@pytest.mark.parametrize('file',[False,True])
def test_closed_audit_rejects_new_evidence_before_storage(rbac,monkeypatch,file):
    c,db,_,storage=rbac;db.get(Auditoria,1).estado='COMPLETED';db.commit()
    def forbidden(*a,**kw):pytest.fail('Closed audit must not write storage')
    monkeypatch.setattr(storage,'save_file',forbidden)
    if file:r=c.post('/api/v1/evidencias/archivo',data={'auditoria_id':1,'titulo':'Forbidden'},files={'archivo':('no.txt',b'no')})
    else:r=c.post('/api/v1/evidencias/logica',json={'auditoria_id':1,'titulo':'Forbidden','tipo':'NOTE'})
    assert r.status_code==409


def test_history_whitelist_does_not_disclose_legacy_extra(rbac):
    c,db,_,_=rbac
    db.add(EventoAuditoria(actor_id=1,accion='LEGACY',entidad_tipo='AUDITORIA',entidad_id='1',
        actor_snapshot='SECRET email',datos_nuevos={'estado':'PLANNED','password_hash':'SECRET hash','storage_key':'SECRET path'}));db.commit()
    r=c.get('/api/v1/auditorias/1/historial');assert r.status_code==200
    assert 'SECRET' not in r.text and r.json()[0]['datos_nuevos']=={'estado':'PLANNED'}


@pytest.mark.parametrize('value',[True,1.5,'2'])
def test_create_responsible_id_is_strict_json_integer(rbac,value):
    assert rbac[0].post('/api/v1/auditorias',json={'codigo':'N','nombre':'New','alcance':'Scope','responsable_id':value}).status_code==422
