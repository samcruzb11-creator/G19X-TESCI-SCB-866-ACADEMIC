"""Adversarial 7B HTTP contract shared with real temporary MySQL."""
import io
import pytest
from sqlalchemy import select, func, event
from fastapi import HTTPException
from tests_unit.test_rbac_unit import rbac
from app.models.entities import Hallazgo, HallazgoEvidencia, Auditoria, Evidencia, EventoAuditoria, Usuario
from app.services import hallazgo_service as service
from app.services.evidencia_service import evidencia_service
from app.schemas.evidencia import EvidenciaCreate
from app.api.dependencies import current_user
from app.main import app


@pytest.fixture
def findings(rbac):
    c,db,actor,storage=rbac
    for audit_id in (1,2,3,4):
        db.get(Auditoria,audit_id).estado='IN_PROGRESS'
        db.add(Hallazgo(id=audit_id,auditoria_id=audit_id,numero=1,titulo=f'Finding {audit_id}',
            descripcion='Control gap',categoria='Control',severidad='HIGH',estado='OPEN',created_by_id=1))
    db.commit()
    return rbac


def body(**kw):
    return {'auditoria_id':1,'titulo':'New finding','descripcion':'Detailed issue','categoria':'Control','severidad':'MEDIUM',**kw}


def detail(c,id=1):
    r=c.get(f'/api/v1/hallazgos/{id}'); assert r.status_code==200,r.text
    return r.json()


def change(c,target,id=1,source=None,**kw):
    row=source or detail(c,id)
    return c.post(f'/api/v1/hallazgos/{id}/estado',json={'estado':target,'estado_esperado':row['estado'],
        'updated_at_esperado':row['updated_at'],**kw})


@pytest.mark.parametrize('actor,expected',[(1,[1,2,3,4]),(2,[1,4]),(3,[3])])
def test_scope_count_page_detail(findings,actor,expected):
    c,db,user,_=findings;user['id']=actor
    for offset,id in enumerate(expected):
        r=c.get('/api/v1/hallazgos',params={'limit':1,'offset':offset})
        assert r.status_code==200 and r.headers['x-total-count']==str(len(expected))
        assert [x['id'] for x in r.json()]==[id]
        assert detail(c,id)['auditoria_id']==id
    for id in set(range(1,5))-set(expected)|{999}:
        for suffix in ('','/evidencias'):
            r=c.get(f'/api/v1/hallazgos/{id}{suffix}')
            assert r.status_code==404 and r.json()['detail']=='Recurso no encontrado'


@pytest.mark.parametrize('actor',[4,5,7])
def test_no_area_or_approver_grants(findings,actor):
    c,_,user,_=findings;user['id']=actor
    assert c.get('/api/v1/hallazgos').status_code==403
    assert c.get('/api/v1/hallazgos/1').status_code==403
    assert c.post('/api/v1/hallazgos',json=body()).status_code==403


@pytest.mark.parametrize('operation',['create','patch','state','link','history'])
def test_external_read_only(findings,operation):
    c,db,user,_=findings;row=detail(c,3);user['id']=3
    if operation=='create':r=c.post('/api/v1/hallazgos',json=body(auditoria_id=3))
    elif operation=='patch':r=c.patch('/api/v1/hallazgos/3',json={'titulo':'Changed','updated_at_esperado':row['updated_at']})
    elif operation=='state':r=change(c,'IN_PROGRESS',3,source=row)
    elif operation=='link':r=c.post('/api/v1/hallazgos/3/evidencias',json={'evidencia_id':3})
    else:r=c.get('/api/v1/hallazgos/3/historial')
    assert r.status_code==403
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('operation',['create','patch','state','link'])
@pytest.mark.parametrize('id',[2,999])
def test_mutation_idor(findings,operation,id):
    c,db,user,_=findings;row=detail(c);user['id']=2
    if operation=='create':r=c.post('/api/v1/hallazgos',json=body(auditoria_id=id))
    elif operation=='patch':r=c.patch(f'/api/v1/hallazgos/{id}',json={'titulo':'Changed','updated_at_esperado':row['updated_at']})
    elif operation=='state':r=change(c,'IN_PROGRESS',id,source=row)
    else:r=c.post(f'/api/v1/hallazgos/{id}/evidencias',json={'evidencia_id':1})
    assert r.status_code==404
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('field,value', [('created_by_id',2),('updated_by_id',2),('actor_id',2),('registrado_por_id',2),
    ('numero',99),('estado','CLOSED'),('detectado_en','2026-01-01'),('cerrado_por_id',1),('titulo',' '),
    ('descripcion',''),('categoria','x'*41),('titulo','x'*201),('descripcion','x'*16001),('titulo','bad\x00'),
    ('severidad','MAX'),('auditoria_id',True),('auditoria_id','1'),('responsable_id',1.5),('responsable_id','2'),('fecha_limite','0999-01-01')])
def test_create_validation_mass_assignment(findings,field,value):
    assert findings[0].post('/api/v1/hallazgos',json=body(**{field:value})).status_code==422


def test_create_actor_number_and_internal_responsible(findings):
    c,db,user,_=findings;user['id']=2
    r=c.post('/api/v1/hallazgos',json=body(responsable_id=2));assert r.status_code==201,r.text
    assert r.json()['numero']==2 and r.json()['created_by_id']==2 and r.json()['estado']=='OPEN'
    assert r.json()['responsable']=={'id':2,'nombre':'User 2'}
    assert c.post('/api/v1/hallazgos',json=body(responsable_id=6)).status_code==403
    assert db.scalar(select(EventoAuditoria)).actor_id==2


@pytest.mark.parametrize('id',[1,4,5,999])
def test_responsible_eligible_not_arbitrary_user(findings,id):
    assert findings[0].post('/api/v1/hallazgos',json=body(responsable_id=id)).status_code==404


@pytest.mark.parametrize('query',[{'limit':201},{'limit':0},{'offset':10001},{'offset':-1},{'orden':'id; DROP TABLE hallazgos'},
    {'sort':'titulo'},{'estado':'ACTIVE'},{'severidad':'EXTREME'},{'responsable_id':0},{'auditoria_id':-1},{'q':'x'*101}])
def test_query_validation(findings,query):
    assert findings[0].get('/api/v1/hallazgos',params=query).status_code==422


@pytest.mark.parametrize('q',["' OR 1=1 --",'%','_','\\'])
def test_literal_search(findings,q):
    r=findings[0].get('/api/v1/hallazgos',params={'q':q})
    assert r.status_code==200 and r.json()==[] and r.headers['x-total-count']=='0'


def test_filters_and_bounded_query_count(findings):
    c,db,user,_=findings;user['id']=2
    r=c.get('/api/v1/hallazgos',params={'estado':'OPEN','severidad':'HIGH','orden':'-id','q':'Control'})
    assert [x['id'] for x in r.json()]==[4,1]
    statements=[]
    def record(conn,cursor,stmt,params,context,many):statements.append(stmt)
    event.listen(db.get_bind(),'before_cursor_execute',record)
    try:assert c.get('/api/v1/hallazgos').status_code==200
    finally:event.remove(db.get_bind(),'before_cursor_execute',record)
    assert len(statements)<=3,statements


@pytest.mark.parametrize('payload',[{}, {'estado':'CLOSED'},{'titulo':None},{'severidad':None},{'auditoria_id':2},{'created_by_id':9},
    {'updated_by_id':9},{'numero':5},{'cerrado_en':'2026-01-01'}])
def test_patch_protected_empty(findings,payload):
    c=findings[0]
    assert c.patch('/api/v1/hallazgos/1',json={**payload,'updated_at_esperado':detail(c)['updated_at']}).status_code==422


def test_edit_stale_and_full_cycle_events(findings):
    c,db,user,_=findings;user['id']=2;old=detail(c)
    r=c.patch('/api/v1/hallazgos/1',json={'titulo':'Edited','updated_at_esperado':old['updated_at']})
    assert r.status_code==200 and r.json()['updated_by_id']==2
    assert c.patch('/api/v1/hallazgos/1',json={'titulo':'Stale','updated_at_esperado':old['updated_at']}).status_code==409
    assert change(c,'CLOSED').status_code==409
    assert change(c,'IN_PROGRESS').status_code==200
    assert change(c,'PENDING_VERIFICATION').status_code==200
    assert change(c,'CLOSED').status_code==422
    r=change(c,'CLOSED',resolucion='Verified corrective action');assert r.status_code==200,r.text
    assert r.json()['cerrado_por_id']==2 and r.json()['cerrado_en']
    assert c.patch('/api/v1/hallazgos/1',json={'titulo':'Terminal','updated_at_esperado':r.json()['updated_at']}).status_code==409
    assert c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':1}).status_code==409
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==4


def test_risk_acceptance_reserved_and_resolution(findings):
    c,db,user,_=findings;user['id']=2
    assert change(c,'ACCEPTED_RISK',resolucion='Risk rationale').status_code==403
    user['id']=1
    assert change(c,'ACCEPTED_RISK').status_code==422
    assert change(c,'ACCEPTED_RISK',resolucion='Risk rationale').status_code==200
    assert change(c,'IN_PROGRESS').status_code==409


@pytest.mark.parametrize('audit_state',['PLANNED','COMPLETED','CANCELLED'])
@pytest.mark.parametrize('operation',['create','patch','state','link'])
def test_audit_rejects_all_finding_mutations(findings,audit_state,operation):
    c,db,_,_=findings;db.get(Auditoria,1).estado=audit_state;db.commit();old=detail(c)
    if operation=='create':r=c.post('/api/v1/hallazgos',json=body())
    elif operation=='patch':r=c.patch('/api/v1/hallazgos/1',json={'titulo':'Frozen','updated_at_esperado':old['updated_at']})
    elif operation=='state':r=change(c,'IN_PROGRESS',source=old)
    else:r=c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':1})
    assert r.status_code==409 and detail(c)==old
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('actor,evidence,status',[(1,2,404),(2,2,404),(1,999,404),(1,4,404),(2,4,404),(1,3,404)])
def test_cross_audit_missing_inconsistent_evidence(findings,actor,evidence,status):
    c,db,user,_=findings;user['id']=actor
    assert c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':evidence}).status_code==status
    assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==0
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


def test_association_duplicate_count_reverse_history(findings):
    c,db,user,_=findings;user['id']=2
    old=detail(c)
    r=c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':1,'contexto':'Supporting control'});assert r.status_code==201,r.text
    assert r.json()['evidencias_count']==1 and r.json()['updated_at']!=old['updated_at']
    assert c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':1}).status_code==409
    r=c.get('/api/v1/hallazgos/1/evidencias');assert [x['id'] for x in r.json()]==[1] and r.headers['x-total-count']=='1'
    assert 'storage_key' not in r.text
    assert [x['id'] for x in c.get('/api/v1/hallazgos?evidencia_id=1').json()]==[1]
    assert c.get('/api/v1/hallazgos?evidencia_id=2').status_code==404
    assert c.get('/api/v1/hallazgos/1/historial').status_code==403
    user['id']=1
    r=c.get('/api/v1/hallazgos/1/historial');assert len(r.json())==1 and r.json()[0]['actor_id']==2
    link=db.get(HallazgoEvidencia,(1,1));assert link.vinculada_por_id==2


@pytest.mark.parametrize('payload',[{}, {'evidencia_id':True},{'evidencia_id':'1'},{'evidencia_id':0},
    {'evidencia_id':1,'actor_id':1},{'evidencia_id':1,'vinculada_por_id':1}])
def test_link_strict_payload(findings,payload):
    assert findings[0].post('/api/v1/hallazgos/1/evidencias',json=payload).status_code==422


@pytest.mark.parametrize('operation',['create','edit','state','link'])
def test_event_failure_rolls_back_no_partial_rows(findings,monkeypatch,operation):
    c,db,_,_=findings;old=detail(c)
    def fail(*a,**kw):raise RuntimeError('SECRET path/sql')
    monkeypatch.setattr(service,'_log_evento',fail)
    if operation=='create':r=c.post('/api/v1/hallazgos',json=body())
    elif operation=='edit':r=c.patch('/api/v1/hallazgos/1',json={'titulo':'Rollback','updated_at_esperado':old['updated_at']})
    elif operation=='state':r=change(c,'IN_PROGRESS',source=old)
    else:r=c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':1})
    assert r.status_code==500 and 'SECRET' not in r.text
    assert detail(c)==old and db.scalar(select(func.count()).select_from(Hallazgo))==4
    assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==0
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('file',[False,True])
def test_new_evidence_atomic_association_actor_and_events(findings,file):
    c,db,user,storage=findings;user['id']=2
    data={'auditoria_id':1,'titulo':'New supporting evidence','hallazgo_id':1}
    if file:r=c.post('/api/v1/evidencias/archivo',data=data,files={'archivo':('../../double.pdf.txt',b'proof','text/plain')})
    else:r=c.post('/api/v1/evidencias/logica',json={**data,'tipo':'NOTE'})
    assert r.status_code==201,r.text
    link=db.get(HallazgoEvidencia,(1,r.json()['id']));assert link and link.vinculada_por_id==2
    assert detail(c)['evidencias_count']==1
    events=list(db.scalars(select(EventoAuditoria)));assert len(events)==2 and all(e.actor_id==2 for e in events)
    assert {e.accion for e in events}=={'ASOCIACION_EVIDENCIA_HALLAZGO','CARGA_EVIDENCIA' if file else 'REGISTRO_EVIDENCIA_LOGICA'}
    if file:
        path=storage.get_absolute_path(r.json()['storage_key']);assert path.read_bytes()==b'proof'
        assert c.get(f"/api/v1/evidencias/{r.json()['id']}/descargar").content==b'proof'
        assert '..' not in r.json()['storage_key']
    assert 'storage_key' not in str([e.datos_nuevos for e in events])


@pytest.mark.parametrize('id',[2,999])
@pytest.mark.parametrize('file',[False,True])
def test_new_evidence_invalid_finding_before_storage(findings,monkeypatch,id,file):
    c,db,_,storage=findings
    def forbidden(*a,**kw):pytest.fail('Invalid relationship must precede storage')
    monkeypatch.setattr(storage,'save_file',forbidden)
    data={'auditoria_id':1,'titulo':'Invalid association','hallazgo_id':id}
    if file:r=c.post('/api/v1/evidencias/archivo',data=data,files={'archivo':('bad.txt',b'bad')})
    else:r=c.post('/api/v1/evidencias/logica',json={**data,'tipo':'NOTE'})
    assert r.status_code==404
    assert db.scalar(select(func.count()).select_from(Evidencia))==4


@pytest.mark.parametrize('file',[False,True])
def test_new_evidence_link_event_failure_compensates(findings,monkeypatch,file):
    c,db,user,storage=findings;old=detail(c);files_before={p for p in storage.base_path.rglob('*') if p.is_file()}
    def fail(*a,**kw):raise RuntimeError('link event failed')
    monkeypatch.setattr(service,'_log_evento',fail)
    with pytest.raises(RuntimeError):
        if file:evidencia_service.registrar_evidencia_archivo(db,1,'Proof',1,io.BytesIO(b'proof'),'proof.txt',hallazgo_id=1)
        else:evidencia_service.registrar_evidencia_logica(db,EvidenciaCreate(auditoria_id=1,titulo='Proof',tipo='NOTE',hallazgo_id=1),1)
    assert detail(c)==old
    assert {p for p in storage.base_path.rglob('*') if p.is_file()}==files_before
    assert db.scalar(select(func.count()).select_from(Evidencia))==4
    assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==0
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


def test_missing_file_cannot_attach(findings):
    c,db,_,_=findings
    db.add(Evidencia(id=5,auditoria_id=1,tipo='FILE',titulo='Missing file',storage_key='evidence/missing.txt',sha256='a'*64,tamano_bytes=1,registrada_por_id=1));db.commit()
    assert c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':5}).status_code==404


def test_legacy_bad_links_do_not_leak_or_count(findings):
    c,db,user,_=findings
    db.add_all([HallazgoEvidencia(hallazgo_id=1,evidencia_id=2,vinculada_por_id=1),
        HallazgoEvidencia(hallazgo_id=1,evidencia_id=4,vinculada_por_id=1)])
    db.commit()
    for id in (1,2):
        user['id']=id
        assert detail(c)['evidencias_count']==0
        assert c.get('/api/v1/hallazgos/1/evidencias').json()==[]
    user['id']=1
    assert c.get('/api/v1/hallazgos?evidencia_id=2').json()==[]


@pytest.mark.parametrize('path',['hallazgos','hallazgos/1','hallazgos/1/evidencias','hallazgos/1/historial'])
def test_identity_required(findings,path):
    del app.dependency_overrides[current_user]
    assert findings[0].get('/api/v1/'+path).status_code==401


def test_history_safe_legacy_projection(findings):
    c,db,_,_=findings
    db.add(EventoAuditoria(actor_id=1,accion='LEGACY',entidad_tipo='HALLAZGO',entidad_id='1',
        datos_nuevos={'estado':'OPEN','password_hash':'SECRET','storage_key':'SECRET'},actor_snapshot='SECRET'))
    db.commit()
    r=c.get('/api/v1/hallazgos/1/historial');assert 'SECRET' not in r.text and r.json()[0]['datos_nuevos']=={'estado':'OPEN'}


@pytest.mark.parametrize('data',[b'',b'123456789'])
def test_empty_oversize_upload_compensates(findings,monkeypatch,data):
    from app.core.config import settings
    c,db,_,storage=findings
    monkeypatch.setattr(settings,'max_evidence_file_bytes',8)
    before={p for p in storage.base_path.rglob('*') if p.is_file()}
    r=c.post('/api/v1/evidencias/archivo',data={'auditoria_id':1,'titulo':'Rejected file','hallazgo_id':1},files={'archivo':('test.txt',data)})
    assert r.status_code==400
    assert {p for p in storage.base_path.rglob('*') if p.is_file()}==before
    assert db.scalar(select(func.count()).select_from(Evidencia))==4
    assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==0
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('title',['   ','x'*201])
def test_file_title_rejected_before_committing_invalid_response(findings,title):
    c,db,_,_=findings
    r=c.post('/api/v1/evidencias/archivo',data={'auditoria_id':1,'titulo':title},files={'archivo':('test.txt',b'proof')})
    assert r.status_code==422
    assert db.scalar(select(func.count()).select_from(Evidencia))==4


@pytest.mark.parametrize('url',['javascript:alert(1)','file:///C:/private','https://user:pass@example.invalid','https://'])
def test_logical_reference_does_not_accept_credentials_or_unsafe_scheme(findings,url):
    assert findings[0].post('/api/v1/evidencias/logica',json={'auditoria_id':1,'titulo':'Reference','tipo':'REFERENCE','referencia_url':url}).status_code==422


@pytest.mark.parametrize('field',['created_by_id','updated_by_id','actor_id','registrada_por_id','storage_key','sha256'])
def test_evidence_json_extras_cannot_spoof_actor_or_storage(findings,field):
    assert findings[0].post('/api/v1/evidencias/logica',json={'auditoria_id':1,'titulo':'Proof','tipo':'NOTE',field:1}).status_code==422


def test_associated_upload_post_commit_refresh_failure_retains_file_and_rows(findings,monkeypatch):
    c,db,_,storage=findings
    before={p for p in storage.base_path.rglob('*') if p.is_file()}
    def fail(*a,**kw):raise RuntimeError('Refresh failure after commit')
    monkeypatch.setattr(db,'refresh',fail)
    with pytest.raises(RuntimeError):
        evidencia_service.registrar_evidencia_archivo(db,1,'Proof',1,io.BytesIO(b'proof'),'proof.txt',hallazgo_id=1)
    assert len({p for p in storage.base_path.rglob('*') if p.is_file()}-before)==1
    assert db.scalar(select(func.count()).select_from(Evidencia))==5
    assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==1
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==2


def test_real_event_insert_failure_rolls_back_link(findings):
    c,db,_,_=findings
    def fail(*a,**kw):raise RuntimeError('Database event insert failed')
    event.listen(EventoAuditoria,'before_insert',fail)
    try:r=c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':1})
    finally:event.remove(EventoAuditoria,'before_insert',fail)
    assert r.status_code==500
    assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==0
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0


@pytest.mark.parametrize('file',[False,True])
def test_terminal_finding_rejects_new_evidence_before_storage(findings,monkeypatch,file):
    c,db,_,storage=findings
    row=db.get(Hallazgo,1);row.estado='ACCEPTED_RISK';row.resolucion='Legacy accepted risk';db.commit()
    def forbidden(*a,**kw):pytest.fail('Terminal finding must reject before storage')
    monkeypatch.setattr(storage,'save_file',forbidden)
    data={'auditoria_id':1,'titulo':'Proof','hallazgo_id':1}
    if file:r=c.post('/api/v1/evidencias/archivo',data=data,files={'archivo':('proof.txt',b'proof')})
    else:r=c.post('/api/v1/evidencias/logica',json={**data,'tipo':'NOTE'})
    assert r.status_code==409
    assert db.scalar(select(func.count()).select_from(Evidencia))==4


@pytest.mark.parametrize('filename',['x'*256+'.txt','bad\x00.txt','bad\n.txt'])
def test_invalid_filename_fails_before_storage(findings,monkeypatch,filename):
    c,db,_,storage=findings
    def forbidden(*a,**kw):pytest.fail('Invalid filename must precede storage')
    monkeypatch.setattr(storage,'save_file',forbidden)
    with pytest.raises(ValueError,match='Nombre de archivo'):
        evidencia_service.registrar_evidencia_archivo(db,1,'Proof',1,io.BytesIO(b'proof'),filename,hallazgo_id=1)
    assert db.scalar(select(func.count()).select_from(Evidencia))==4


def test_untrusted_user_agent_is_not_persisted_as_metadata(findings):
    c,db,_,_=findings
    r=c.post('/api/v1/evidencias/logica',headers={'User-Agent':'SECRET test bearer token'},json={
        'auditoria_id':1,'titulo':'Proof','tipo':'NOTE','hallazgo_id':1})
    assert r.status_code==201
    assert 'SECRET' not in str([e.datos_nuevos for e in db.scalars(select(EventoAuditoria))])


@pytest.mark.parametrize('file',[False,True])
def test_evidence_control_characters_are_rejected_without_commit(findings,file):
    c,db,_,_=findings
    data={'auditoria_id':1,'titulo':'bad\x00title'}
    if file:r=c.post('/api/v1/evidencias/archivo',data=data,files={'archivo':('proof.txt',b'proof')})
    else:r=c.post('/api/v1/evidencias/logica',json={**data,'tipo':'NOTE'})
    assert r.status_code==422
    assert db.scalar(select(func.count()).select_from(Evidencia))==4


def test_file_version_can_still_resolve_its_document_before_association(findings):
    c,db,_,_=findings
    r=c.post('/api/v1/evidencias/archivo',data={'auditoria_id':1,'titulo':'Proof','hallazgo_id':1,'version_documento_id':1},
        files={'archivo':('proof.txt',b'proof')})
    assert r.status_code==201,r.text
    assert r.json()['documento_id']==1 and r.json()['version_documento_id']==1
    assert db.get(HallazgoEvidencia,(1,r.json()['id'])) is not None


@pytest.mark.parametrize('kind',['path','create','owner','query','link'])
def test_identifiers_outside_mysql_domain_rejected_before_sql(findings,kind):
    c,db,_,_=findings;huge=2**64
    if kind=='path':r=c.get(f'/api/v1/hallazgos/{huge}')
    elif kind=='create':r=c.post('/api/v1/hallazgos',json=body(auditoria_id=huge))
    elif kind=='owner':r=c.post('/api/v1/hallazgos',json=body(responsable_id=huge))
    elif kind=='query':r=c.get('/api/v1/hallazgos',params={'auditoria_id':huge})
    else:r=c.post('/api/v1/hallazgos/1/evidencias',json={'evidencia_id':huge})
    assert r.status_code==422
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==0
