"""Real PHP rendering and security contracts against isolated response fixtures."""
import html
import pytest
from conftest import login, csrf


def item(payload='Factura Enero.pdf'):
    return dict(tipo='DUPLICATE_HASH',clasificacion='posible duplicado',severidad='INFO',
        recurso='version',recurso_id=1,nombre=payload,titulo='Coincidencia binaria entre documentos',
        explicacion='Contenido binario idéntico en otro documento autorizado.',
        evidencia_tecnica=['SHA-256 válido idéntico; documentos distintos'],regla='7E:DUPLICATE_HASH:1',
        evaluado_en='2026-10-07T12:00:00Z',destino=dict(pagina='documento',id=1,version_id=1),
        relacionado=dict(pagina='documento',id=2,version_id=3),similitud_nombre=None)


def install(api,payload='Factura Enero.pdf'):
    api.overrides['GET','/api/v1/analisis/resumen']=(200,dict(evaluado_en='2026-10-07T12:00:00Z',
        total=1,por_tipo={'DUPLICATE_HASH':1},por_severidad=dict(INFO=1,WARNING=0)),{})
    page=dict(total=1,limit=20,offset=0,items=[item(payload)])
    api.overrides['GET','/api/v1/analisis/anomalias']=(200,page,{})
    detail=dict(evaluado_en='2026-10-07T12:00:00Z',anomalias=page,comprobaciones_locales=[],
        versiones_comprobadas=2,versiones_comprobadas_limite=100,comprobacion_completa=True,
        candidatos_comparados=0,candidatos_limite=64,candidatos_truncados=False)
    for path in ('documentos/1','versiones/1'):
        api.overrides['GET','/api/v1/analisis/'+path]=(200,detail,{})
    return page,detail


@pytest.mark.parametrize('role',['ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR'])
def test_role_page_links_filters_detail_and_server_only_jwt(frontend,role):
    c,api,_,_=frontend;install(api);login(c,role,api);api.requests.clear()
    response=c.get('/index.php?pagina=analisis')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert '¿Por qué se marcó?' in response.text and '7E:DUPLICATE_HASH:1' in response.text
    assert 'pagina=documento&amp;id=1' in response.text and 'pagina=documento&amp;id=2' in response.text
    assert api.token not in response.text and 'sha256' not in response.text
    assert [r['path'] for r in api.requests]==['/api/v1/auth/me','/api/v1/analisis/resumen','/api/v1/analisis/anomalias']
    assert ('id="analysis-audit"' in response.text)==(role in {'ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO'})
    for key in ('documento_id','version_id'):
        response=c.get('/index.php?pagina=analisis&'+key+'=1')
        assert response.status_code==200 and 'Comprobaciones locales' in response.text
    response=c.get('/index.php?pagina=analisis&offset=20&tipo=DUPLICATE_HASH&severidad=INFO')
    assert 'Anteriores' in response.text and 'offset=20' in api.requests[-1]['query']
    assert c.post('/index.php?pagina=analisis',data={'csrf_token':csrf(response)}).status_code==405


@pytest.mark.parametrize('payload',['<script>window.analysis_xss=1</script>',
    '<img src=x onerror=alert(1)>','<svg onload=alert(1)>','"\' & &lt; Unicode 文档 🧪'])
def test_all_dynamic_text_escaped(frontend,payload):
    c,api,_,_=frontend;page,detail=install(api,payload)
    for field in ('titulo','explicacion','regla'):page['items'][0][field]=payload
    page['items'][0]['evidencia_tecnica']=[payload];login(c)
    for query in ('','&documento_id=1'):
        response=c.get('/index.php?pagina=analisis'+query)
        assert response.status_code==200
        assert html.escape(payload,quote=True).replace('&#x27;','&#039;') in response.text
        if '<' in payload:assert payload not in response.text


@pytest.mark.parametrize('status',[401,403,404,409,500,503])
def test_api_failures_session_and_sanitized_errors(frontend,status):
    c,api,_,_=frontend;install(api);login(c)
    api.overrides['GET','/api/v1/analisis/resumen']=(status,{'detail':'PRIVATE token local path'},{})
    api.overrides['GET','/api/v1/analisis/anomalias']=(status,{'detail':'PRIVATE token local path'},{})
    response=c.get('/index.php?pagina=analisis')
    assert response.status_code==(303 if status==401 else 403 if status==403 else 200)
    assert 'PRIVATE' not in response.text
    if status==401:assert 'pagina=login' in response.headers['location']
    elif status!=403:assert 'Información no disponible' in response.text


@pytest.mark.parametrize('query',['tipo[]=X','tipo=FRAUDE','severidad=CRITICAL','documento_id=1e0',
    'documento_id=1.0','documento_id[]=1','documento_id=0','version_id=-1','offset=10001',
    'documento_id=18446744073709551616','auditoria_id=1%27+OR+1%3D1'])
def test_invalid_input_does_not_reach_analysis_api(frontend,query):
    c,api,_,_=frontend;install(api);login(c);api.requests.clear()
    assert c.get('/index.php?pagina=analisis&'+query).status_code==422
    assert all(r['path']=='/api/v1/auth/me' for r in api.requests)


def test_empty_truncated_local_results_and_hostile_links(frontend):
    c,api,_,_=frontend;page,detail=install(api);login(c)
    for bad in ('javascript:alert(1)','//evil.invalid','https://evil.invalid'):
        page['items'][0]['destino']['pagina']=bad;page['items'][0]['relacionado']['pagina']=bad
        response=c.get('/index.php?pagina=analisis')
        assert bad not in response.text
    page['items']=[];page['total']=0;detail['comprobacion_completa']=False;detail['candidatos_truncados']=True
    response=c.get('/index.php?pagina=analisis&documento_id=1')
    assert 'No hay señales' in response.text and 'Alcance parcial' in response.text and 'Candidatos truncados' in response.text


def test_unsigned_bigint_is_displayed_exactly_without_float_or_broken_link(frontend):
    c,api,_,_=frontend;page,_=install(api);login(c)
    huge=2**64-1
    page['items'][0]['recurso_id']=huge
    page['items'][0]['destino'].update(id=huge,version_id=huge)
    response=c.get('/index.php?pagina=analisis')
    assert response.status_code==200 and str(huge) in response.text
    assert 'E+19' not in response.text
    assert 'pagina=documento&amp;id='+str(huge) not in response.text
    assert 'pagina=analisis&amp;documento_id='+str(huge) in response.text
