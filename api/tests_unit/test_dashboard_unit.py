"""Adversarial 7D HTTP contracts, shared with guarded real MySQL."""
from datetime import datetime
import json
import pytest
from pydantic import ValidationError
from sqlalchemy import select, func, event, text
from fastapi.testclient import TestClient

from tests_unit.test_rbac_unit import rbac
from tests_unit.test_aprobacion_unit import approvals
from app.models.entities import (Usuario, Auditoria, Documento, VersionDocumento,
    DocumentoAuditoria, Hallazgo, RondaAprobacion, DecisionAprobacion, EventoAuditoria)
from app.main import app
from app.api.dependencies import current_user
from app.schemas.dashboard import DashboardContext, DashboardPage, AlertFilters
from app.services import dashboard_service as service

STAMP = datetime(2026, 10, 1)
ENDPOINTS = ('resumen', 'indicadores', 'alertas', 'actividad')


@pytest.fixture
def dashboard(approvals):
    c, db, user, storage = approvals
    db.add(Usuario(id=9, nombre='Empty auditor', correo='9@example.invalid',
        correo_normalizado='9@example.invalid', password_hash='unused', rol='AUDITOR_INTERNO', activo=True))
    db.add(Documento(id=5, codigo='EMPTY', titulo='No version', tipo='TEST',
        estado='DRAFT', area_id=1, responsable_id=4, created_by_id=1))
    for aid in range(1,5):
        for number, state in enumerate(('OPEN','IN_PROGRESS','PENDING_VERIFICATION','CLOSED','ACCEPTED_RISK'),1):
            db.add(Hallazgo(auditoria_id=aid, numero=number, titulo=f'Finding {aid}/{number}',
                descripcion='No evidence is required', categoria='TEST', severidad='HIGH', estado=state,
                created_by_id=1, cerrado_por_id=1 if state=='CLOSED' else None,
                cerrado_en=STAMP if state=='CLOSED' else None))
        db.add(EventoAuditoria(accion='CREACION_RONDA_APROBACION', entidad_tipo='RONDA_APROBACION',
            entidad_id=str(aid), actor_id=1, ocurrido_en=STAMP, actor_snapshot='PRIVATE email',
            datos_nuevos={'auditorias_ids':[999], 'token':'PRIVATE', 'titulo':'<script>metadata</script>'}))
        db.add(EventoAuditoria(accion='CREACION_AUDITORIA', entidad_tipo='AUDITORIA',
            entidad_id=str(aid), actor_id=1, ocurrido_en=STAMP, datos_nuevos={'responsable_id':999}))
    db.commit()
    return approvals


def get(c, endpoint='resumen', **params):
    r = c.get('/api/v1/dashboard/'+endpoint, params=params)
    assert r.status_code == 200, r.text
    assert r.headers['cache-control']=='no-store'
    return r.json()


@pytest.mark.parametrize('actor,audits,findings,rounds,docs,versions,evidence,own', [
    (1,4,20,4,5,5,4,None), (2,2,10,2,2,3,1,None), (3,1,5,1,1,1,1,None),
    (4,None,None,2,3,3,None,None), (5,None,None,2,2,2,None,2),
    (6,1,5,1,1,1,1,None), (7,None,None,2,2,2,None,None), (8,None,None,2,2,2,None,2),
    (9,0,0,0,0,0,0,None)])
def test_indicators_exact_scopes_all_roles(dashboard,actor,audits,findings,rounds,docs,versions,evidence,own):
    c,db,user,_=dashboard;user['id']=actor
    data=get(c)['indicadores']
    for key,expected in [('auditorias',audits),('hallazgos',findings),('aprobaciones',rounds),('documentos',docs),('evidencias',evidence)]:
        assert (data[key]['total'] if data[key] is not None else None)==expected
    assert data['documentos']['versiones']==versions
    assert data['decisiones']['pendientes_propias']==own
    if actor in (5,8):
        assert data['documentos']['sin_version'] is None
        assert data['documentos_con_version']['estado']=='NOT_APPLICABLE'
    else:
        assert data['documentos']['sin_version']==(1 if actor in (1,4) else 0)


def test_formulas_states_cancelled_and_accepted_risk(dashboard):
    c,db,user,_=dashboard
    db.get(Auditoria,1).estado='COMPLETED';db.get(Auditoria,2).estado='CANCELLED'
    for id,state in [(1,'APPROVED'),(2,'REJECTED'),(3,'CHANGES_REQUESTED'),(4,'CANCELLED')]:
        r=db.get(RondaAprobacion,id);r.estado=state;r.resuelta_en=STAMP
        d=db.get(DecisionAprobacion,id)
        if state!='CANCELLED':d.estado=state;d.decidida_en=STAMP
    db.commit()
    data=get(c,'indicadores')
    assert data['auditorias_completadas']==dict(numerador=1,denominador=3,porcentaje=33.33,estado='OK')
    assert data['hallazgos_cerrados']==dict(numerador=4,denominador=20,porcentaje=20,estado='OK')
    assert data['rondas_resueltas']==dict(numerador=3,denominador=3,porcentaje=100,estado='OK')
    assert data['documentos_con_version']==dict(numerador=4,denominador=5,porcentaje=80,estado='OK')
    assert data['decisiones']['resueltas']==3
    assert data['hallazgos']['por_estado']['ACCEPTED_RISK']==4


def test_empty_denominators_no_nan(dashboard):
    c,db,user,_=dashboard;user['id']=9
    data=get(c)
    for key in ('auditorias_completadas','hallazgos_cerrados','rondas_resueltas','documentos_con_version'):
        assert data['indicadores'][key]==dict(numerador=0,denominador=0,porcentaje=None,estado='NO_DATA')
    assert data['alertas']['total']==data['actividad']['total']==0
    assert 'NaN' not in json.dumps(data)


@pytest.mark.parametrize('actor',[2,3,4,5,6,7,8,9])
def test_paged_alerts_and_activity_destinations_are_readable(dashboard,actor):
    c,db,user,_=dashboard;user['id']=actor
    paths={'auditoria':'auditorias','hallazgo':'hallazgos','documento':'documentos','aprobacion':'aprobaciones'}
    for endpoint in ('alertas','actividad'):
        first=get(c,endpoint,limit=1);total=first['total'];keys=[]
        for offset in range(total):
            data=get(c,endpoint,limit=1,offset=offset)
            assert data['total']==total and len(data['items'])==1
            item=data['items'][0];keys.append(item.get('clave',item.get('id')))
            target=item['destino']
            assert c.get(f"/api/v1/{paths[target['pagina']]}/{target['id']}").status_code==200
        assert len(keys)==len(set(keys))
        assert get(c,endpoint,offset=total)['items']==[]


@pytest.mark.parametrize('terminal',['COMPLETED','CANCELLED'])
def test_terminal_audits_and_findings_no_operational_alerts(dashboard,terminal):
    c,db,user,_=dashboard;user['id']=2
    for aid in (1,4):db.get(Auditoria,aid).estado=terminal
    db.commit()
    data=get(c,'alertas',limit=100)
    assert all(i['tipo']=='RONDA_PENDIENTE' and i['severidad']=='INFO' for i in data['items'])
    assert all('acciones disponibles' in i['descripcion'] for i in data['items'])
    # Historical rounds remain truthfully pending; no claim that 7C mutations are available.


def test_own_assignment_active_round_alert_distinct_from_historical_count(dashboard):
    c,db,user,_=dashboard;user['id']=5
    db.get(RondaAprobacion,1).estado='IN_REVIEW'
    r=db.get(RondaAprobacion,4);r.estado='CANCELLED';r.resuelta_en=STAMP;db.commit()
    data=get(c)
    assert data['indicadores']['decisiones']['pendientes_propias']==2
    assert [i['tipo'] for i in data['alertas']['items']]==['DECISION_PROPIA_PENDIENTE']
    assert data['alertas']['items'][0]['severidad']=='INFO'


def test_documents_without_version_not_without_current_version(dashboard):
    c,db,user,_=dashboard
    # Existing versions with version_vigente_id NULL are complete for this measure.
    data=get(c,'alertas',tipo='DOCUMENTO_SIN_VERSION')
    assert [i['recurso_id'] for i in data['items']]==[5]
    db.get(Documento,5).estado='ARCHIVED';db.commit()
    assert get(c,'alertas',tipo='DOCUMENTO_SIN_VERSION')['total']==0
    assert get(c,'indicadores')['documentos']['sin_version']==1


@pytest.mark.parametrize('actor',[2,3,4,5,6,7,8,9])
def test_invisible_insertions_cannot_change_aggregates_alerts_activity_pages(dashboard,actor):
    c,db,user,_=dashboard;user['id']=actor
    baseline={e:get(c,e,**({} if e=='indicadores' else {'limit':100})) for e in ENDPOINTS}
    baseline['resumen'].pop('generado_en')
    db.add(Auditoria(id=999,codigo='HIDDEN',nombre='PRIVATE audit',alcance='PRIVATE',
        estado='IN_REVIEW',responsable_id=1,created_by_id=1));db.flush()
    db.add(Documento(id=999,codigo='HIDDEN',titulo='PRIVATE document',tipo='TEST',
        estado='ACTIVE',area_id=1,responsable_id=1,created_by_id=1))
    db.add(Hallazgo(auditoria_id=999,numero=1,titulo='PRIVATE finding',descripcion='PRIVATE',
        categoria='TEST',severidad='CRITICAL',estado='OPEN',created_by_id=1))
    db.add(EventoAuditoria(accion='CREACION_AUDITORIA',entidad_tipo='AUDITORIA',entidad_id='999',actor_id=1))
    db.commit()
    for e in ENDPOINTS:
        data=get(c,e,**({} if e=='indicadores' else {'limit':100}))
        if e=='resumen':data.pop('generado_en')
        assert data==baseline[e]
        assert 'PRIVATE' not in json.dumps(data)


def test_hidden_shared_audit_state_does_not_create_counter_side_channel(dashboard):
    c,db,user,_=dashboard;user['id']=5
    before=get(c,'alertas',limit=100)
    db.add(DocumentoAuditoria(auditoria_id=2,documento_id=1,version_documento_id=1,
        proposito='TEST',asociado_por_id=1));db.get(Auditoria,2).estado='CANCELLED';db.commit()
    assert get(c,'alertas',limit=100)==before


@pytest.mark.parametrize('endpoint',ENDPOINTS)
def test_audit_filter_nonexistent_and_out_of_scope_indistinguishable(dashboard,endpoint):
    c,db,user,_=dashboard;user['id']=2
    a=c.get('/api/v1/dashboard/'+endpoint,params={'auditoria_id':2})
    b=c.get('/api/v1/dashboard/'+endpoint,params={'auditoria_id':999})
    assert a.status_code==b.status_code==404 and a.json()==b.json()
    assert a.json()=={'detail':'Recurso no encontrado'}
    data=get(c,endpoint,auditoria_id=1)
    if endpoint=='indicadores':assert data['auditorias']['total']==1 and data['hallazgos']['total']==5


@pytest.mark.parametrize('actor',[4,5,7,8])
@pytest.mark.parametrize('endpoint',ENDPOINTS)
def test_non_auditors_do_not_gain_audit_access_by_filter(dashboard,actor,endpoint):
    c,db,user,_=dashboard;user['id']=actor
    for aid in (1,999):assert c.get('/api/v1/dashboard/'+endpoint,params={'auditoria_id':aid}).status_code==403


@pytest.mark.parametrize('endpoint',ENDPOINTS)
@pytest.mark.parametrize('value',['0','-1','true','1.0','1e0','1 OR 1=1','18446744073709551616','١','NaN'])
def test_strict_query_ids_and_sqli(dashboard,endpoint,value):
    c,_,_,_=dashboard
    assert c.get('/api/v1/dashboard/'+endpoint,params={'auditoria_id':value}).status_code==422


@pytest.mark.parametrize('field,value',[('limit','0'),('limit','101'),('limit','1.0'),('limit','true'),
    ('offset','-1'),('offset','10001'),('offset','1e0'),('tipo',"x' OR 1=1"),
    ('severidad','CRITICAL'),('severidad',"INFO' UNION SELECT 1"),('orden','id;DROP TABLE usuarios'),
    ('estado','UNKNOWN'),('rol','ADMIN'),('usuario_id','1'),('total_global','999'),('q','test')])
def test_invalid_filters_extra_and_client_kpis_rejected(dashboard,field,value):
    c,_,_,_=dashboard
    assert c.get('/api/v1/dashboard/alertas',params={field:value}).status_code==422


@pytest.mark.parametrize('model',[DashboardContext,DashboardPage,AlertFilters])
@pytest.mark.parametrize('value',[True,False,1.0,'1.0','1e0',0,-1,2**64])
def test_schema_ids_no_coercion(model,value):
    with pytest.raises(ValidationError):model(auditoria_id=value)


def test_event_history_permissions_metadata_whitelist_and_legacy_ids(dashboard):
    c,db,user,_=dashboard
    for entity in ('1.0','01','1e0','1junk','-1','1 ','18446744073709551616'):
        db.add(EventoAuditoria(accion='CREACION_RONDA_APROBACION',entidad_tipo='RONDA_APROBACION',
            entidad_id=entity,datos_nuevos={'token':'PRIVATE'}))
    db.add(EventoAuditoria(accion='LOGIN_PRIVATE',entidad_tipo='RONDA_APROBACION',entidad_id='1'))
    db.commit()
    assert get(c,'actividad',limit=100)['total']==8
    for actor,expected in [(2,2),(3,1),(4,2),(5,2),(8,2),(9,0)]:
        user['id']=actor;data=get(c,'actividad',limit=100)
        assert data['total']==expected
        assert all(i['destino']['pagina']=='aprobacion' for i in data['items'])
        assert all(set(i)=={'id','accion','titulo','ocurrido_en','destino'} for i in data['items'])
        assert 'PRIVATE' not in json.dumps(data) and 'datos_nuevos' not in json.dumps(data)


@pytest.mark.parametrize('actor',[1,2,3,4,5,9])
def test_no_n_plus_one_query_budget(dashboard,actor):
    c,db,user,_=dashboard;user['id']=actor
    get(c)  # Identity warmup belongs to the existing authentication path.
    statements=[]
    def capture(conn,cursor,stmt,*args):statements.append(stmt)
    event.listen(db.get_bind(),'before_cursor_execute',capture)
    try:
        get(c,limit=100)
        assert len(statements)<=12,statements
        assert all(s.lstrip().upper().startswith('SELECT') for s in statements)
    finally:event.remove(db.get_bind(),'before_cursor_execute',capture)


def test_get_only_no_mutations_and_deny_unknown_role(dashboard):
    c,db,user,_=dashboard
    before=db.scalar(select(func.count()).select_from(EventoAuditoria))
    for endpoint in ENDPOINTS:
        for method in ('post','patch','delete'):
            assert getattr(c,method)('/api/v1/dashboard/'+endpoint).status_code==405
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==before
    # CONSULTA is not an effective role and must not obtain a fallback global scope.
    original=app.dependency_overrides[current_user]
    try:
        app.dependency_overrides[current_user]=lambda:Usuario(id=9,rol='CONSULTA',activo=True)
        assert c.get('/api/v1/dashboard/resumen').status_code==403
    finally:app.dependency_overrides[current_user]=original


def test_no_identity_is_401(dashboard):
    c,db,_,_=dashboard
    override=app.dependency_overrides.pop(current_user)
    try:assert c.get('/api/v1/dashboard/resumen').status_code==401
    finally:app.dependency_overrides[current_user]=override


def test_backend_errors_sanitized(dashboard,monkeypatch):
    c,db,_,_=dashboard
    def fail(*args,**kw):raise RuntimeError('PRIVATE password local path')
    monkeypatch.setattr(service,'indicators',fail)
    with TestClient(app,raise_server_exceptions=False) as safe:
        response=safe.get('/api/v1/dashboard/resumen')
    assert response.status_code==500 and response.json()=={'detail':'Error interno del servidor'}


@pytest.mark.parametrize('state',['PLANNED','IN_PROGRESS','IN_REVIEW','COMPLETED','CANCELLED'])
def test_audit_state_distributions_and_alerts_exact(dashboard,state):
    c,db,_,_=dashboard
    db.get(Auditoria,1).estado=state;db.commit()
    data=get(c,'indicadores',auditoria_id=1)
    assert data['auditorias']['por_estado'][state]==1
    alerts=get(c,'alertas',auditoria_id=1,limit=100)
    audit_alerts=[a for a in alerts['items'] if a['recurso']=='auditoria']
    assert len(audit_alerts)==int(state in {'IN_PROGRESS','IN_REVIEW'})


@pytest.mark.parametrize('state',['PENDING','IN_REVIEW','APPROVED','REJECTED','CHANGES_REQUESTED','CANCELLED'])
def test_round_states_exact_and_terminal_no_alert(dashboard,state):
    c,db,_,_=dashboard
    row=db.get(RondaAprobacion,1);row.estado=state
    row.resuelta_en=STAMP if state not in {'PENDING','IN_REVIEW'} else None
    db.commit()
    data=get(c,'indicadores',auditoria_id=1)
    assert data['aprobaciones']['por_estado'][state]==1
    alerts=get(c,'alertas',auditoria_id=1,tipo='RONDA_PENDIENTE')
    assert alerts['total']==int(state in {'PENDING','IN_REVIEW'})


@pytest.mark.parametrize('model,table,check,resource',[
    (Auditoria,'auditorias','ck_auditorias_estado','auditorias'),
    (Hallazgo,'hallazgos','ck_hallazgos_estado','hallazgos'),
    (RondaAprobacion,'rondas_aprobacion','ck_rondas_estado','aprobaciones')])
def test_corrupt_legacy_state_counted_safely_never_reflected(dashboard,model,table,check,resource):
    c,db,_,_=dashboard
    mysql=db.get_bind().dialect.name=='mysql'
    row=db.scalar(select(model).order_by(model.id));id=row.id;old=row.estado
    if mysql:
        assert db.get_bind().url.database.startswith('sistema_trazabilidad_test_auth_')
        db.execute(text(f'ALTER TABLE {table} ALTER CHECK {check} NOT ENFORCED'));db.commit()
    else:db.execute(text('PRAGMA ignore_check_constraints=ON'))
    try:
        if model is RondaAprobacion:row.resuelta_en=STAMP
        row.estado='<svg>PRIVATE</svg>';db.commit()
        data=get(c,'indicadores');assert data[resource]['por_estado']['DESCONOCIDO']==1
        assert 'PRIVATE' not in json.dumps(data)
        alerts=get(c,'alertas',limit=100)
        assert all(a['recurso_id']!=id or a['recurso']!= {'auditorias':'auditoria','hallazgos':'hallazgo','aprobaciones':'aprobacion'}[resource] for a in alerts['items'])
    finally:
        db.get(model,id).estado=old;db.commit()
        if mysql:db.execute(text(f'ALTER TABLE {table} ALTER CHECK {check} ENFORCED'));db.commit()
        else:db.execute(text('PRAGMA ignore_check_constraints=OFF'))


def test_duplicate_and_cross_document_pivots_do_not_amplify_counts(dashboard):
    c,db,user,_=dashboard;user['id']=2
    before=get(c,'indicadores')
    db.add(DocumentoAuditoria(auditoria_id=4,documento_id=1,version_documento_id=1,
        proposito='TEST',asociado_por_id=1))
    # A legacy mismatched pivot cannot grant approval access to the other version.
    db.add(DocumentoAuditoria(auditoria_id=1,documento_id=1,version_documento_id=4,
        proposito='TEST',asociado_por_id=1));db.commit()
    assert get(c,'indicadores')==before
    assert c.get('/api/v1/aprobaciones/3').status_code==404


@pytest.mark.parametrize('model,state,group,resource',[
    (Auditoria,'in_review','auditorias','auditoria'),
    (Auditoria,'IN_REVIEW ','auditorias','auditoria'),
    (Hallazgo,'open','hallazgos','hallazgo'),
    (Hallazgo,'ÓPEN','hallazgos','hallazgo'),
    (Hallazgo,'OPEN ','hallazgos','hallazgo'),
    (RondaAprobacion,'pending','aprobaciones','aprobacion'),
    (DecisionAprobacion,'pending','decisiones',None)])
def test_case_accent_padding_legacy_states_cannot_break_dashboard(dashboard,model,state,group,resource):
    c,db,_,_=dashboard
    row=db.scalar(select(model).order_by(model.id));id=row.id;old=row.estado
    sqlite=db.get_bind().dialect.name=='sqlite'
    if sqlite:db.execute(text('PRAGMA ignore_check_constraints=ON'))
    try:
        # These values can pass a MySQL utf8mb4_unicode_ci CHECK unchanged.
        row.estado=state;db.commit()
        data=get(c)
        assert data['indicadores'][group]['por_estado']['DESCONOCIDO']==1
        assert all(a['recurso']!=resource or a['recurso_id']!=id for a in data['alertas']['items'])
    finally:
        db.get(model,id).estado=old;db.commit()
        if sqlite:db.execute(text('PRAGMA ignore_check_constraints=OFF'))


def test_event_action_and_entity_whitelists_exact_under_mysql_collation(dashboard):
    c,db,_,_=dashboard
    for action,entity in [('creacion_ronda_aprobacion','RONDA_APROBACION'),
            ('CREACION_RONDA_APROBACION ','RONDA_APROBACION'),
            ('CREACIÓN_RONDA_APROBACION','RONDA_APROBACION'),
            ('CREACION_RONDA_APROBACION','ronda_aprobacion')]:
        db.add(EventoAuditoria(accion=action,entidad_tipo=entity,entidad_id='1'))
    db.commit()
    assert get(c,'actividad',limit=100)['total']==8
