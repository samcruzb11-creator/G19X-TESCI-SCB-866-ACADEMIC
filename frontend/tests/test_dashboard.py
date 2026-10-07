"""PHP HTTP rendering, safe links, errors and read-only dashboard contracts."""
import html
import pytest
from conftest import login, csrf


@pytest.mark.parametrize('role,auditor,own', [('ADMIN',True,False),('AUDITOR_INTERNO',True,False),
    ('AUDITOR_EXTERNO',True,False),('RESPONSABLE_AREA',False,False),('APROBADOR',False,True)])
def test_role_sections_server_aggregates_one_request_no_browser_jwt(frontend,role,auditor,own):
    c,api,_,_=frontend;login(c,role,api);api.requests.clear()
    r=c.get('/index.php?pagina=dashboard')
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert ('data-kpi="auditorias"' in r.text)==auditor
    assert ('Mis decisiones pendientes' in r.text)==own
    assert ('Documentos con versión</h3>' in r.text)==(not own)
    assert 'data-kpi="documentos">1' in r.text and api.token not in r.text
    assert [a['path'] for a in api.requests]==['/api/v1/auth/me','/api/v1/dashboard/resumen']
    assert all(a['headers']['Authorization']=='Bearer '+api.token for a in api.requests)
    assert 'href="index.php?pagina=alertas"' in r.text


@pytest.mark.parametrize('payload',['<script>window.dashboard_xss=1</script>', '<img src=x onerror=alert(1)>',
    '<svg onload=alert(1)>', '\"\' & < >', '&lt;script&gt;', '文档 🧪 \u202e suspicious'])
def test_stored_names_titles_descriptions_escape(frontend,payload):
    c,api,_,_=frontend;api.audit['estado']='IN_REVIEW';api.finding['titulo']=payload
    api.document['titulo']=payload;api.name=payload;login(c)
    for page in ('dashboard','alertas'):
        r=c.get('/index.php?pagina='+page)
        assert r.status_code==200
        assert html.escape(payload,quote=True).replace('&#x27;','&#039;') in r.text
        if '<' in payload:assert payload not in r.text
        assert '<svg onload' not in r.text and '<img src=x' not in r.text


@pytest.mark.parametrize('status',[404,500,503])
def test_summary_errors_never_fabricate_zero_or_disclose_error(frontend,status):
    c,api,_,_=frontend;login(c);sid=c.cookies.get('PHPSESSID')
    api.overrides['GET','/api/v1/dashboard/resumen']=(status,{'detail':'PRIVATE password local path'}, {})
    r=c.get('/index.php?pagina=dashboard')
    assert r.status_code==200 and 'Información no disponible' in r.text
    assert 'data-kpi=' not in r.text and 'PRIVATE' not in r.text
    assert c.cookies.get('PHPSESSID')==sid


@pytest.mark.parametrize('status',[401,403])
def test_dashboard_respects_authority_failures(frontend,status):
    c,api,_,_=frontend;login(c)
    api.overrides['GET','/api/v1/dashboard/resumen']=(status,{'detail':'PRIVATE'}, {})
    assert c.get('/index.php?pagina=dashboard').status_code==(303 if status==401 else 403)


def test_zero_denominators_display_no_data(frontend):
    c,api,_,_=frontend;login(c)
    _,data,_=api.answer_dashboard(dict(path='/api/v1/dashboard/resumen',query='',method='GET'))
    for item in data['indicadores'].values():
        if isinstance(item,dict) and 'porcentaje' in item:item.update(numerador=0,denominador=0,porcentaje=None,estado='NO_DATA')
    data['alertas'].update(total=0,items=[]);data['actividad'].update(total=0,items=[])
    api.overrides['GET','/api/v1/dashboard/resumen']=(200,data,{})
    r=c.get('/index.php?pagina=dashboard')
    assert r.text.count('Sin datos')==4 and '100,00%' not in r.text
    assert 'No hay alertas' in r.text and 'No hay actividad' in r.text


@pytest.mark.parametrize('value',['javascript:alert(1)','//example.invalid','https://evil.invalid','auditoria'])
def test_untrusted_destination_never_redirects_or_links_outside_scope(frontend,value):
    c,api,_,_=frontend;login(c,'APROBADOR',api)
    _,data,_=api.answer_dashboard(dict(path='/api/v1/dashboard/resumen',method='GET'))
    data['alertas']['items'][0]['destino']={'pagina':value,'id':1}
    api.overrides['GET','/api/v1/dashboard/resumen']=(200,data,{})
    r=c.get('/index.php?pagina=dashboard')
    assert r.status_code==200
    assert 'javascript:' not in r.text and 'evil.invalid' not in r.text
    assert 'href="index.php?pagina=auditoria&amp;id=1"' not in r.text


def test_filters_pagination_readonly_and_csrf_preserved(frontend):
    c,api,_,_=frontend;login(c);api.requests.clear()
    r=c.get('/index.php?pagina=alertas&tipo=RONDA_PENDIENTE&severidad=INFO&offset=20')
    assert r.status_code==200
    request=api.requests[-1]
    assert request['path']=='/api/v1/dashboard/alertas' and 'offset=20' in request['query']
    assert 'Alertas anteriores' in r.text
    token=csrf(r)
    for page in ('dashboard','alertas'):
        assert c.post('/index.php?pagina='+page,data={'csrf_token':token,'total':999}).status_code==405
    assert not any(a['method']!='GET' for a in api.requests)
    assert c.post('/index.php?pagina=logout',data={'csrf_token':token}).status_code==303


@pytest.mark.parametrize('query',['severidad=CRITICAL','severidad=INFO%27+OR+1%3D1','tipo[]=X','offset=-1','offset=1e0','offset=10001'])
def test_unsafe_frontend_filters_no_api_request(frontend,query):
    c,api,_,_=frontend;login(c);api.requests.clear()
    assert c.get('/index.php?pagina=alertas&'+query).status_code==422
    assert all(a['path']=='/api/v1/auth/me' for a in api.requests)
