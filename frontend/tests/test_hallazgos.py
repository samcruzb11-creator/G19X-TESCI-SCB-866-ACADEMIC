"""Real PHP forms against isolated transport double; API remains authoritative."""
from urllib.parse import parse_qs
import pytest
from conftest import csrf, login, LEGACY


def mutations(api):
    return [x for x in api.requests if x['method'] in {'POST','PATCH'} and x['path'].startswith('/api/v1/hallazgos')]


def active(frontend):
    c,api,_,_=frontend;api.audit['estado']='IN_PROGRESS';login(c)
    return c,api


def form_body(token,**kw):
    return dict(csrf_token=token,auditoria_id='1',titulo='New finding',descripcion='Issue',categoria='Control',severidad='HIGH',responsable_id='7',fecha_limite='',**kw)


def test_list_filters_pagination_backend_and_token_secrecy(frontend):
    c,api=active(frontend)
    api.overrides['GET','/api/v1/hallazgos']=(200,[api.finding],{'X-Total-Count':'61'})
    r=c.get('/index.php?pagina=hallazgos&p=2&q=Issue&estado=OPEN&severidad=HIGH&auditoria_id=1&responsable_id=7&orden=-id')
    assert r.status_code==200 and '61 registros' in r.text and 'Anterior' in r.text and 'Siguiente' in r.text
    query=parse_qs(next(x for x in reversed(api.requests) if x['path']=='/api/v1/hallazgos')['query'])
    assert query=={'q':['Issue'],'estado':['OPEN'],'severidad':['HIGH'],'auditoria_id':['1'],'responsable_id':['7'],'orden':['-id'],'limit':['20'],'offset':['20']}
    assert api.token not in r.text


@pytest.mark.parametrize('query',['p=502','p[]=1','q[]=x','estado[]=OPEN','auditoria_id[]=1'])
def test_invalid_filters(frontend,query):
    c,api=active(frontend)
    assert c.get('/index.php?pagina=hallazgos&'+query).status_code==422


@pytest.mark.parametrize('page',['hallazgo_nuevo&auditoria_id=1','hallazgo_editar&id=1','hallazgo&id=1'])
def test_csrf_no_business_mutation(frontend,page):
    c,api=active(frontend)
    r=c.post('/index.php?pagina='+page,data=form_body('bad',accion='asociar',evidencia_id='1'))
    assert r.status_code==403 and not mutations(api)


def test_create_edit_whitelist_actor_and_expected_version(frontend):
    c,api=active(frontend)
    form=c.get('/index.php?pagina=hallazgo_nuevo&auditoria_id=1')
    r=c.post('/index.php?pagina=hallazgo_nuevo&auditoria_id=1',data=form_body(csrf(form),created_by_id='999',estado='CLOSED',numero='88'))
    assert r.status_code==303
    sent=mutations(api)[0]['json'];assert not LEGACY.intersection(sent) and 'estado' not in sent and 'numero' not in sent
    assert sent['auditoria_id']==1 and sent['responsable_id']==7
    form=c.get('/index.php?pagina=hallazgo_editar&id=1')
    r=c.post('/index.php?pagina=hallazgo_editar&id=1',data=form_body(csrf(form),updated_at_esperado='2025-01-01T00:00:00',resolucion='Fix',updated_by_id='999'))
    assert r.status_code==303
    sent=mutations(api)[-1];assert sent['method']=='PATCH'
    assert sent['json']['updated_at_esperado']=='2025-01-01T00:00:00'
    assert 'auditoria_id' not in sent['json'] and 'updated_by_id' not in sent['json']


def test_state_and_association_commands_fixed_paths(frontend):
    c,api=active(frontend);page=c.get('/index.php?pagina=hallazgo&id=1')
    r=c.post('/index.php?pagina=hallazgo&id=1',data={'csrf_token':csrf(page),'accion':'estado','estado':'IN_PROGRESS','estado_esperado':'OPEN','updated_at_esperado':api.finding['updated_at'],'actor_id':'999'})
    assert r.status_code==303
    assert mutations(api)[0]['json']=={'estado':'IN_PROGRESS','estado_esperado':'OPEN','updated_at_esperado':'2026-10-01T00:00:00'}
    page=c.get('/index.php?pagina=hallazgo&id=1')
    r=c.post('/index.php?pagina=hallazgo&id=1',data={'csrf_token':csrf(page),'accion':'asociar','evidencia_id':'1','contexto':'Support','vinculada_por_id':'999'})
    assert r.status_code==303
    assert mutations(api)[-1]['json']=={'evidencia_id':1,'contexto':'Support'}


@pytest.mark.parametrize('role',['AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR'])
def test_roles_hide_or_deny_write(frontend,role):
    c,api=active(frontend);api.role=role
    assert c.get('/index.php?pagina=hallazgo_nuevo&auditoria_id=1').status_code==403
    assert c.get('/index.php?pagina=hallazgo_editar&id=1').status_code==403
    detail=c.get('/index.php?pagina=hallazgo&id=1')
    if role=='AUDITOR_EXTERNO':
        assert detail.status_code==200 and 'Editar hallazgo' not in detail.text and 'Asociar evidencia existente' not in detail.text
        assert c.post('/index.php?pagina=hallazgo&id=1',data={'csrf_token':csrf(c.get('/index.php?pagina=dashboard')),'accion':'asociar','evidencia_id':'1'}).status_code==403
    else:assert detail.status_code==403
    assert not mutations(api)


@pytest.mark.parametrize('state',['COMPLETED','CANCELLED'])
def test_closed_audit_no_actions_or_submit(frontend,state):
    c,api=active(frontend);api.audit['estado']=state
    r=c.get('/index.php?pagina=hallazgo&id=1')
    assert r.status_code==200 and 'Editar hallazgo' not in r.text and 'Cambiar estado' not in r.text
    assert c.get('/index.php?pagina=hallazgo_nuevo&auditoria_id=1').status_code==409
    assert not mutations(api)


@pytest.mark.parametrize('status',[401,403,404,409,422,503])
def test_api_errors_no_false_success_no_secret(frontend,status):
    c,api=active(frontend);form=c.get('/index.php?pagina=hallazgo&id=1')
    api.overrides['POST','/api/v1/hallazgos/1/evidencias']=(status,{'detail':'SECRET SQL /server/path'}, {})
    r=c.post('/index.php?pagina=hallazgo&id=1',data={'csrf_token':csrf(form),'accion':'asociar','evidencia_id':'1'})
    assert r.status_code==(303 if status==401 else status)
    assert 'SECRET' not in r.text and 'actualizado correctamente' not in r.text


def test_new_evidence_atomic_link_id_passed_to_existing_endpoint(frontend):
    c,api=active(frontend)
    form=c.get('/index.php?pagina=evidencia_logica&auditoria_id=1&hallazgo_id=1')
    assert form.status_code==200 and 'hallazgo_id=1' in form.text
    r=c.post('/index.php?pagina=evidencia_logica&hallazgo_id=1',data={'csrf_token':csrf(form),'auditoria_id':'1','titulo':'New proof','descripcion':'Proof','tipo':'NOTE','documento_id':'','version_documento_id':''})
    assert r.status_code==303
    sent=next(x for x in api.requests if x['method']=='POST' and x['path']=='/api/v1/evidencias/logica')
    assert sent['json']['hallazgo_id']==1
    assert not mutations(api),'No second transaction for association'


def test_reverse_links_detail_pagination_and_xss(frontend):
    c,api=active(frontend);api.finding['titulo']='<script>alert(1)</script>'
    r=c.get('/index.php?pagina=evidencia&id=1&fp=2')
    assert r.status_code==200 and '&lt;script&gt;' in r.text and '<script>alert(1)</script>' not in r.text
    query=parse_qs(next(x for x in reversed(api.requests) if x['path']=='/api/v1/hallazgos')['query'])
    assert query=={'evidencia_id':['1'],'limit':['20'],'offset':['20']}


def test_audit_integration_and_get_cannot_mutate(frontend):
    c,api=active(frontend)
    r=c.get('/index.php?pagina=auditoria&id=1')
    assert 'Crear hallazgo' in r.text and 'Ver todos los hallazgos' in r.text and 'Test finding' in r.text
    r=c.get('/index.php?pagina=hallazgo&id=1&accion=asociar&evidencia_id=1&estado=CLOSED')
    assert r.status_code==200 and not mutations(api)


def test_detail_three_independent_bounded_pages(frontend):
    c,api=active(frontend)
    api.overrides['GET','/api/v1/hallazgos/1/evidencias']=(200,[api.evidence],{'X-Total-Count':'61'})
    api.overrides['GET','/api/v1/evidencias']=(200,[api.evidence],{'X-Total-Count':'61'})
    api.overrides['GET','/api/v1/hallazgos/1/historial']=(200,[],{'X-Total-Count':'61'})
    r=c.get('/index.php?pagina=hallazgo&id=1&ep=2&cp=3&hp=2');assert r.status_code==200
    for path,offset in [('/api/v1/hallazgos/1/evidencias',20),('/api/v1/evidencias',40),('/api/v1/hallazgos/1/historial',20)]:
        query=parse_qs(next(x for x in reversed(api.requests) if x['path']==path)['query'])
        assert query['offset']==[str(offset)] and query['limit']==['20']


def test_api_validation_fields_use_safe_highlighting(frontend):
    c,api=active(frontend);form=c.get('/index.php?pagina=hallazgo_nuevo&auditoria_id=1')
    api.overrides['POST','/api/v1/hallazgos']=(422,{'detail':[{'loc':['body','fecha_limite'],'msg':'SECRET raw error'}]}, {})
    r=c.post('/index.php?pagina=hallazgo_nuevo&auditoria_id=1',data=form_body(csrf(form)))
    assert r.status_code==422 and 'fecha_limite-error' in r.text and 'SECRET' not in r.text
