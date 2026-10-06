"""Adversarial approval HTTP contract shared with temporary real MySQL."""
import pytest
from sqlalchemy import select, func, event
from fastapi import HTTPException
from tests_unit.test_rbac_unit import rbac
from app.models.entities import (Usuario, Auditoria, Documento, VersionDocumento, DocumentoAuditoria,
    RondaAprobacion as Ronda, DecisionAprobacion as Decision, EventoAuditoria)
from app.services import aprobacion_service as service


@pytest.fixture
def approvals(rbac):
    c, db, actor, storage = rbac
    db.add(Usuario(id=8, nombre='Other approver', correo='8@example.invalid', correo_normalizado='8@example.invalid',
                   password_hash='unused', rol='APROBADOR', activo=True))
    for i in (1, 2, 3, 4):
        db.get(Auditoria, i).estado = 'IN_REVIEW'
    for i, version, approver in [(2, 3, 8), (3, 4, 8), (4, 5, 5)]:
        db.add(Ronda(id=i, version_documento_id=version, numero_ronda=1, estado='PENDING', solicitada_por_id=1))
        db.flush()
        db.add(Decision(id=i, ronda_aprobacion_id=i, aprobador_id=approver, estado='PENDING'))
    db.commit()
    return rbac


def detail(c, id=1):
    r = c.get(f'/api/v1/aprobaciones/{id}')
    assert r.status_code == 200, r.text
    return r.json()


def command(c, action, id=1, row=None, **extra):
    row = row or detail(c, id)
    return c.post(f'/api/v1/aprobaciones/{id}/{action}', json={
        'estado_esperado': row['estado'], 'updated_at_esperado': row['updated_at'], **extra})


def vote(c, state='APPROVED', id=1, row=None, **extra):
    row = row or detail(c, id)
    return c.post(f'/api/v1/aprobaciones/{id}/decision', json={
        'estado': state, 'updated_at_esperado': row['mi_decision']['updated_at'], **extra})


def body(**extra):
    return {'documento_id': 1, 'version_documento_id': 2, 'aprobadores_ids': [5], **extra}


@pytest.mark.parametrize('actor,ids', [(1,[1,2,3,4]),(2,[1,4]),(3,[3]),(4,[1,3]),(5,[1,4]),(6,[2]),(7,[2,4]),(8,[2,3])])
def test_sql_scope_count_pagination_detail_history(approvals, actor, ids):
    c, db, user, _ = approvals; user['id'] = actor
    for index, id in enumerate(ids):
        r = c.get('/api/v1/aprobaciones', params={'orden':'id', 'limit':1,'offset':index})
        assert r.status_code == 200, r.text
        assert r.headers['x-total-count'] == str(len(ids)) and [x['id'] for x in r.json()] == [id]
        assert detail(c,id)['id'] == id
    for id in set(range(1,5)) - set(ids) | {999}:
        for suffix in ('','/decisiones','/historial'):
            r=c.get(f'/api/v1/aprobaciones/{id}{suffix}')
            assert r.status_code == 404 and r.json()['detail'] == 'Recurso no encontrado'


@pytest.mark.parametrize('actor',[3,4,5,7,8])
def test_no_write_or_catalog_privilege(approvals,actor):
    c,db,user,_=approvals; row=detail(c); user['id']=actor
    assert c.post('/api/v1/aprobaciones',json=body()).status_code==403
    for suffix in ('iniciar','cancelar','finalizar'):
        assert command(c,suffix,row=row).status_code==403
    for suffix in ('recursos','aprobadores'):
        assert c.get('/api/v1/aprobaciones/'+suffix).status_code==403
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('actor,doc,version,audit,status',[(1,1,2,None,201),(2,1,2,None,404),
    (2,2,3,2,404),(2,1,2,1,404),(2,1,1,2,404),(1,2,2,None,404),(1,1,3,1,404),
    (1,1,2,1,404),(1,999,2,None,404),(1,1,999,None,404)])
def test_create_exact_subject_cross_document_audit(approvals,actor,doc,version,audit,status):
    c,db,user,_=approvals;user['id']=actor
    payload=body(documento_id=doc,version_documento_id=version)
    if audit is not None:payload['auditoria_id']=audit
    r=c.post('/api/v1/aprobaciones',json=payload)
    assert r.status_code==status,r.text
    assert db.scalar(select(func.count()).select_from(Ronda))==(5 if status==201 else 4)
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==(1 if status==201 else 0)


def test_internal_manage_own_exact_version_no_document_state_change(approvals):
    c,db,user,_=approvals;user['id']=2
    assert command(c,'cancelar').status_code==200
    r=c.post('/api/v1/aprobaciones',json=body(version_documento_id=1,auditoria_id=1))
    assert r.status_code==201 and r.json()['numero_ronda']==2 and r.json()['solicitada_por']['id']==2
    assert db.get(Documento,1).estado=='ACTIVE'
    assert command(c,'iniciar',r.json()['id']).status_code==200
    assert command(c,'finalizar',r.json()['id']).status_code==409


@pytest.mark.parametrize('state', ['APPROVED','REJECTED','CHANGES_REQUESTED'])
def test_confirmed_decision_immutable_actor_result_events(approvals,state):
    c,db,user,_=approvals
    assert command(c,'iniciar').status_code==200
    user['id']=5;old=detail(c)
    r=vote(c,state,row=old,comentario='<script>alert(1)</script>')
    assert r.status_code==200 and r.json()['estado']==state and r.json()['resuelta_en'] is not None
    assert not r.json()['puede_decidir'] and r.json()['mi_decision']['aprobador_id']==5
    assert vote(c,'REJECTED',row=old).status_code==409
    assert c.patch('/api/v1/aprobaciones/1',json={'estado':'PENDING'}).status_code==405
    events=list(db.scalars(select(EventoAuditoria).order_by(EventoAuditoria.id)))
    assert [e.accion for e in events]==['INICIO_RONDA_APROBACION','DECISION_APROBACION','CIERRE_RONDA_APROBACION']
    assert [e.actor_id for e in events]==[1,5,5]
    assert events[-1].datos_nuevos['auditorias_ids']==[1]
    history=c.get('/api/v1/aprobaciones/1/historial').json()
    assert all('actor_snapshot' not in e and 'auditorias_ids' not in e['datos_nuevos'] for e in history)
    assert db.get(Documento,1).estado=='ACTIVE' and db.get(Auditoria,1).estado=='IN_REVIEW'


@pytest.mark.parametrize('first,second,expected', [('APPROVED','APPROVED','APPROVED'),
    ('CHANGES_REQUESTED','APPROVED','CHANGES_REQUESTED'),('CHANGES_REQUESTED','REJECTED','REJECTED')])
def test_all_assignments_minimal_result(approvals,first,second,expected):
    c,db,user,_=approvals
    db.add(Decision(ronda_aprobacion_id=1,aprobador_id=8,estado='PENDING'));db.commit()
    command(c,'iniciar');user['id']=5
    r=vote(c,first);assert r.status_code==200 and r.json()['estado']=='IN_REVIEW' and r.json()['pendientes_count']==1
    user['id']=8;r=vote(c,second)
    assert r.status_code==200 and r.json()['estado']==expected
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==4


@pytest.mark.parametrize('field,value', [('created_by_id',9),('solicitada_por_id',9),('estado','APPROVED'),
    ('numero_ronda',9),('resuelta_en','2026-01-01'),('actor_id',9),('resultado','APPROVED'),
    ('version_documento_id',True),('version_documento_id',1.0),('version_documento_id','1'),
    ('documento_id',0),('documento_id',2**64),('aprobadores_ids',[]),('aprobadores_ids',[5,5]),
    ('aprobadores_ids',[True]),('aprobadores_ids',['5']),('aprobadores_ids',list(range(21)))])
def test_create_mass_assignment_strict_ids(approvals,field,value):
    c,db,_,_=approvals
    r=c.post('/api/v1/aprobaciones',json=body(**{field:value}))
    assert r.status_code==422,r.text
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('extra',[{'aprobador_id':8},{'actor_id':8},{'decidida_en':'2026-01-01'},
    {'resultado':'APPROVED'},{'estado':'PENDING'},{'estado':'INVALID'}, {'comentario':'x'*16001},
    {'comentario':'nul\x00'}, {'comentario':[]}, {'updated_at_esperado':True}])
def test_decision_mass_assignment(approvals,extra):
    c,db,user,_=approvals;command(c,'iniciar');user['id']=5
    assert vote(c,**extra).status_code==422
    assert db.get(Decision,1).estado=='PENDING'
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==1


@pytest.mark.parametrize('ids', [[999],[1],[2],[4],[5,999]])
def test_ineligible_approvers_no_partial_round(approvals,ids):
    c,db,_,_=approvals
    assert c.post('/api/v1/aprobaciones',json=body(aprobadores_ids=ids)).status_code==404
    assert db.scalar(select(func.count()).select_from(Ronda))==4
    assert db.scalar(select(func.count()).select_from(Decision))==4


@pytest.mark.parametrize('operation',['create','iniciar','cancelar','finalizar','decision'])
@pytest.mark.parametrize('terminal',['COMPLETED','CANCELLED'])
def test_terminal_audit_blocks_all_mutations(approvals,operation,terminal):
    c,db,user,_=approvals
    if operation=='decision':command(c,'iniciar');user['id']=5
    before=db.scalar(select(func.count()).select_from(EventoAuditoria))
    db.get(Auditoria,1).estado=terminal;db.commit()
    if operation=='create':r=c.post('/api/v1/aprobaciones',json=body(version_documento_id=1))
    elif operation=='decision':r=vote(c)
    else:r=command(c,operation)
    assert r.status_code==409,r.text
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==before


def test_shared_version_closed_other_audit_cannot_bypass(approvals):
    c,db,user,_=approvals
    db.add(DocumentoAuditoria(auditoria_id=2,documento_id=1,version_documento_id=1,proposito='TEST',asociado_por_id=1))
    db.get(Auditoria,2).estado='CANCELLED';db.commit();user['id']=2
    r=command(c,'iniciar');assert r.status_code==409 and '2' not in r.text
    assert not detail(c)['puede_gestionar']


def test_legacy_inconsistent_pivot_rejected(approvals):
    c,db,_,_=approvals
    db.add(DocumentoAuditoria(auditoria_id=2,documento_id=2,version_documento_id=1,proposito='TEST',asociado_por_id=1));db.commit()
    assert command(c,'iniciar').status_code==404
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


def test_approver_assignment_is_per_round_not_per_version(approvals):
    c,db,user,_=approvals
    db.add(Ronda(id=5,version_documento_id=1,numero_ronda=2,solicitada_por_id=1));db.flush()
    db.add(Decision(ronda_aprobacion_id=5,aprobador_id=8));db.commit();user['id']=5
    assert c.get('/api/v1/aprobaciones/5').status_code==404
    assert c.post('/api/v1/aprobaciones/5/decision',json={'estado':'APPROVED','updated_at_esperado':detail(c)['mi_decision']['updated_at']}).status_code==404


def test_admin_cannot_impersonate_assigned_approver(approvals):
    c,db,_,_=approvals;command(c,'iniciar')
    r=c.post('/api/v1/aprobaciones/1/decision',json={'estado':'APPROVED','updated_at_esperado':db.get(Decision,1).updated_at.isoformat()})
    assert r.status_code==404 and db.get(Decision,1).estado=='PENDING'


@pytest.mark.parametrize('operation',['create','decision','cancelar'])
@pytest.mark.parametrize('failure',['event','flush','commit'])
def test_atomic_rollback(approvals,monkeypatch,operation,failure):
    c,db,user,_=approvals
    if operation=='decision':command(c,'iniciar');user['id']=5
    row=detail(c);state=db.get(Ronda,1).estado
    before=db.scalar(select(func.count()).select_from(EventoAuditoria))
    def fail(*a,**kw):raise RuntimeError('secret failure')
    if failure=='event':monkeypatch.setattr(service,'_log_evento',fail)
    elif failure=='flush':
        original=db.flush
        def fail_write(*a,**kw):
            if db.new or db.dirty:fail()
            return original(*a,**kw)
        monkeypatch.setattr(db,'flush',fail_write)
    else:monkeypatch.setattr(db,failure,fail)
    if operation=='create':r=c.post('/api/v1/aprobaciones',json=body())
    elif operation=='decision':r=vote(c,row=row)
    else:r=command(c,operation,row=row)
    assert r.status_code==500 and 'secret' not in r.text
    monkeypatch.undo();db.expire_all()
    assert db.get(Ronda,1).estado==state and db.get(Decision,1).estado=='PENDING'
    assert db.scalar(select(func.count()).select_from(Ronda))==4
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==before


def test_legacy_finalization_calculated_and_double_finalize(approvals):
    c,db,_,_=approvals;command(c,'iniciar')
    d=db.get(Decision,1);d.estado='CHANGES_REQUESTED';d.decidida_en=service.now();db.commit()
    old=detail(c);r=command(c,'finalizar',row=old)
    assert r.status_code==200 and r.json()['estado']=='CHANGES_REQUESTED'
    assert command(c,'finalizar',row=old).status_code==409


@pytest.mark.parametrize('params',[{'orden':'id; DROP TABLE usuarios'}, {'limit':101},{'offset':10001},
    {'estado':'INVALID'},{'documento_id':0},{'q':'\x00'},{'unexpected':'value'},
    {'documento_id':'1.0'},{'auditoria_id':'1e0'},{'limit':'1.0'},{'offset':'false'}])
def test_filters_order_bounds(approvals,params):
    c,_,_,_=approvals;assert c.get('/api/v1/aprobaciones',params=params).status_code==422


def test_catalogs_projection_pending_filter_and_bounded_queries(approvals):
    c,db,user,_=approvals
    r=c.get('/api/v1/aprobaciones/aprobadores',params={'limit':1,'offset':1})
    assert r.status_code==200 and r.json()==[{'id':8,'nombre':'Other approver'}] and r.headers['x-total-count']=='2'
    user['id']=2
    r=c.get('/api/v1/aprobaciones/recursos',params={'auditoria_id':1})
    assert r.status_code==200 and [x['version_documento_id'] for x in r.json()]==[1]
    assert c.get('/api/v1/aprobaciones/recursos',params={'auditoria_id':2}).status_code==404
    command(c,'iniciar');user['id']=5
    r=c.get('/api/v1/aprobaciones',params={'pendientes_propias':'true'})
    assert r.status_code==200 and [x['id'] for x in r.json()]==[1]
    statements=[]
    def count(conn,cursor,stmt,*args):
        if stmt.lstrip().upper().startswith('SELECT'):statements.append(stmt)
    event.listen(db.bind,'before_cursor_execute',count)
    try:r=c.get('/api/v1/aprobaciones')
    finally:event.remove(db.bind,'before_cursor_execute',count)
    assert r.status_code==200 and len(statements)<=5


def test_empty_stale_and_pending_decision_rejected(approvals):
    c,db,user,_=approvals
    assert c.post('/api/v1/aprobaciones',json={}).status_code==422
    assert c.post('/api/v1/aprobaciones/1/decision',json={}).status_code==422
    old=detail(c);command(c,'iniciar')
    assert command(c,'cancelar',row=old).status_code==409
    user['id']=5
    assert vote(c,updated_at_esperado='2000-01-01T00:00:00').status_code==409
    user['id']=1;command(c,'cancelar');user['id']=5
    assert vote(c).status_code==409


@pytest.mark.parametrize('actor,target',[(2,2),(2,999),(5,2),(5,999)])
def test_direct_mutation_idor(approvals,actor,target):
    c,db,user,_=approvals;stamp=detail(c)['updated_at'];user['id']=actor
    payload={'estado_esperado':'PENDING','updated_at_esperado':stamp} if actor==2 else {'estado':'APPROVED','updated_at_esperado':stamp}
    r=c.post(f'/api/v1/aprobaciones/{target}/'+('iniciar' if actor==2 else 'decision'),json=payload)
    assert r.status_code==404 and db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('failure',['decision_insert','round_update','decision_update','calculation','event_insert'])
def test_database_statement_and_calculation_rollback(approvals,monkeypatch,failure):
    c,db,user,_=approvals
    if failure in {'decision_update','calculation'}:command(c,'iniciar');user['id']=5
    row=detail(c);previous=row['estado'];before=db.scalar(select(func.count()).select_from(EventoAuditoria))
    def fail(*a,**kw):raise RuntimeError('Private driver failure')
    statement={'decision_insert':'INSERT INTO decisiones_aprobacion','round_update':'UPDATE rondas_aprobacion',
               'decision_update':'UPDATE decisiones_aprobacion','event_insert':'INSERT INTO eventos_auditoria'}.get(failure)
    def inject(conn,cursor,sql,*args):
        if statement and sql.startswith(statement):fail()
    if failure=='calculation':monkeypatch.setattr(service,'result',fail)
    else:event.listen(db.bind,'before_cursor_execute',inject)
    try:
        if failure=='decision_insert':r=c.post('/api/v1/aprobaciones',json=body())
        elif failure in {'decision_update','calculation'}:r=vote(c,row=row)
        else:r=command(c,'cancelar',row=row)
    finally:
        if failure!='calculation':event.remove(db.bind,'before_cursor_execute',inject)
    assert r.status_code==500 and 'Private' not in r.text
    db.expire_all();assert db.get(Ronda,1).estado==previous and db.get(Decision,1).estado=='PENDING'
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==before
    assert db.scalar(select(func.count()).select_from(Ronda))==4


def test_start_rechecks_legacy_approver_eligibility(approvals):
    c,db,_,_=approvals;db.get(Usuario,5).activo=False;db.commit()
    assert command(c,'iniciar').status_code==404
    assert db.get(Ronda,1).estado=='PENDING' and db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('id',['0','-1','1.0','1e0','18446744073709551616','true'])
def test_path_ids_do_not_coerce_invalid_values(approvals,id):
    c,_,_,_=approvals
    assert c.get('/api/v1/aprobaciones/'+id).status_code==422


@pytest.mark.parametrize('code',[1205,1213])
def test_mysql_lock_errors_rollback_without_automatic_replay(approvals,monkeypatch,code):
    from sqlalchemy.exc import OperationalError
    c,db,_,_=approvals
    def conflict():raise OperationalError('private query',None,Exception(code,'private lock failure'))
    monkeypatch.setattr(db,'commit',conflict)
    assert command(c,'cancelar').status_code==409
    db.expire_all()
    assert db.get(Ronda,1).estado=='PENDING' and db.scalar(select(func.count()).select_from(EventoAuditoria))==0
