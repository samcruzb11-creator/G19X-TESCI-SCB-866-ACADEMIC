from urllib.parse import parse_qs
import pytest
from conftest import csrf, login


def mutations(api):
    return [x for x in api.requests if x['method']=='POST' and x['path'].startswith('/api/v1/aprobaciones')]


def active(frontend,role='ADMIN'):
    c,api,_,_=frontend;api.audit['estado']='IN_REVIEW';api.role=role;login(c)
    return c,api


def test_list_backend_pagination_filters_no_token(frontend):
    c,api=active(frontend);c.get('/index.php?pagina=aprobaciones')
    api.overrides['GET','/api/v1/aprobaciones']=(200,[api.approval],{'X-Total-Count':'61'})
    r=c.get('/index.php?pagina=aprobaciones&p=2&q=Document&estado=IN_REVIEW&documento_id=1&auditoria_id=1&orden=id&pendientes_propias=true')
    assert r.status_code==200 and '61 registros' in r.text and 'Anterior' in r.text and 'Siguiente' in r.text
    assert api.token not in r.text
    query=parse_qs(next(x for x in reversed(api.requests) if x['path']=='/api/v1/aprobaciones')['query'])
    assert query['limit']==['20'] and query['offset']==['20'] and query['pendientes_propias']==['true']


@pytest.mark.parametrize('query',['p=502','p[]=1','q[]=x','estado[]=x','auditoria_id[]=1'])
def test_manipulated_filters(frontend,query):
    c,_=active(frontend)
    assert c.get('/index.php?pagina=aprobaciones&'+query).status_code==422


@pytest.mark.parametrize('role',['AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR'])
def test_role_controls_and_direct_write(frontend,role):
    c,api=active(frontend,role)
    r=c.get('/index.php?pagina=aprobacion&id=1')
    assert r.status_code==200 and 'Iniciar revisión' not in r.text and 'Cancelar ronda' not in r.text
    assert c.get('/index.php?pagina=aprobacion_nueva').status_code==403
    r=c.post('/index.php?pagina=aprobacion&id=1',data={'csrf_token':csrf(c.get('/index.php?pagina=dashboard')),'accion':'iniciar'})
    assert r.status_code==403 and not mutations(api)


@pytest.mark.parametrize('page',['aprobacion&id=1','aprobacion_nueva'])
def test_csrf_no_mutation(frontend,page):
    c,api=active(frontend)
    assert c.post('/index.php?pagina='+page,data={'accion':'iniciar','csrf_token':'bad'}).status_code==403
    assert not mutations(api)


def test_create_commands_server_actor_and_mass_assignment_whitelist(frontend):
    c,api=active(frontend);page=c.get('/index.php?pagina=aprobacion_nueva&auditoria_id=1')
    r=c.post('/index.php?pagina=aprobacion_nueva&auditoria_id=1',data={'csrf_token':csrf(page),'version_documento_id':'1','aprobadores_ids[]':'7','actor_id':'999','estado':'APPROVED'})
    assert r.status_code==303,r.text
    assert mutations(api)[0]['json']=={'documento_id':1,'version_documento_id':1,'aprobadores_ids':[7],'auditoria_id':1}
    page=c.get('/index.php?pagina=aprobacion&id=1')
    r=c.post('/index.php?pagina=aprobacion&id=1',data={'csrf_token':csrf(page),'accion':'iniciar','estado_esperado':'PENDING','updated_at_esperado':'2000-01-01T00:00:00'})
    assert r.status_code==303
    assert mutations(api)[-1]['json']['updated_at_esperado']=='2000-01-01T00:00:00'


def test_approver_confirmation_and_immutable_display(frontend):
    c,api=active(frontend,'APROBADOR');c.get('/index.php?pagina=aprobacion&id=1');api.approval['estado']='IN_REVIEW'
    page=c.get('/index.php?pagina=aprobacion&id=1')
    assert 'Registrar mi decisión' in page.text
    r=c.post('/index.php?pagina=aprobacion&id=1',data={'csrf_token':csrf(page),'accion':'decision','estado':'CHANGES_REQUESTED','comentario':'<script>alert(1)</script>','updated_at_esperado':'2026-10-01T00:00:00','aprobador_id':'999','resultado':'APPROVED'})
    assert r.status_code==303
    assert mutations(api)[-1]['json']=={'estado':'CHANGES_REQUESTED','comentario':'<script>alert(1)</script>','updated_at_esperado':'2026-10-01T00:00:00'}
    page=c.get(r.headers['location'])
    assert '<script>alert(1)</script>' not in page.text and '&lt;script&gt;' in page.text
    assert 'Registrar mi decisión' not in page.text and 'Mi decisión' in page.text
    assert api.token not in page.text


@pytest.mark.parametrize('status',[401,403,404,409,422,503])
def test_backend_error_sanitized_no_false_success(frontend,status):
    c,api=active(frontend);page=c.get('/index.php?pagina=aprobacion&id=1')
    api.overrides['POST','/api/v1/aprobaciones/1/iniciar']=(status,{'detail':'SECRET SQL /private/path'}, {})
    r=c.post('/index.php?pagina=aprobacion&id=1',data={'csrf_token':csrf(page),'accion':'iniciar','estado_esperado':'PENDING','updated_at_esperado':api.approval['updated_at']})
    assert r.status_code==(303 if status==401 else status)
    assert 'SECRET' not in r.text and 'confirmada.' not in r.text


@pytest.mark.parametrize('state',['COMPLETED','CANCELLED'])
def test_terminal_no_actions(frontend,state):
    c,api=active(frontend);api.audit['estado']=state
    r=c.get('/index.php?pagina=aprobacion&id=1')
    assert r.status_code==200 and 'Iniciar revisión' not in r.text
    assert not mutations(api)


def test_expired_session_and_get_does_not_mutate(frontend):
    c,api=active(frontend)
    assert c.get('/index.php?pagina=aprobacion&id=1&accion=iniciar').status_code==200 and not mutations(api)
    api.valid=False
    r=c.get('/index.php?pagina=aprobaciones')
    assert r.status_code==303 and 'pagina=login' in r.headers['location']


def test_document_audit_integration(frontend):
    c,api=active(frontend)
    for page in ('documento','auditoria'):
        r=c.get('/index.php?pagina='+page+'&id=1')
        assert r.status_code==200 and 'Crear ronda de aprobación' in r.text and 'Ver todas las rondas' in r.text
    requests=[r for r in api.requests if r['path']=='/api/v1/aprobaciones']
    assert all(parse_qs(r['query'])['limit']==['5'] for r in requests)


@pytest.mark.parametrize('data',[{'version_documento_id':'999','aprobadores_ids[]':'7'},
    {'version_documento_id':'1','aprobadores_ids[]':'999'}, {'version_documento_id[]':'1','aprobadores_ids[]':'7'}])
def test_create_manipulated_ids(frontend,data):
    c,api=active(frontend);page=c.get('/index.php?pagina=aprobacion_nueva')
    r=c.post('/index.php?pagina=aprobacion_nueva',data={'csrf_token':csrf(page),**data})
    assert r.status_code==422 and not mutations(api)
