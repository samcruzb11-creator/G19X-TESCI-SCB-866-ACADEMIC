import json
import subprocess
import pytest
from conftest import csrf, login, LEGACY, PHP, ROOT


def test_login_session_and_token_secrecy(frontend):
    c, api, private, web = frontend
    before = c.cookies.get('PHPSESSID')
    result = login(c)
    assert result.status_code == 303 and result.headers['location'].endswith('pagina=dashboard')
    after = c.cookies.get('PHPSESSID')
    assert after != before
    cookie = result.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'path=/' in cookie
    assert not (private / 'sistema-trazabilidad-frontend-sessions' / ('sess_'+before)).exists()
    stored = (private / 'sistema-trazabilidad-frontend-sessions' / ('sess_'+after)).read_text()
    assert api.token in stored
    assert 'correct' not in stored and 'not-stored@example.invalid' not in stored
    assert not any(p.name.startswith('sess_') for p in web.rglob('*'))
    dashboard = c.get(result.headers['location'])
    assert dashboard.status_code == 200
    assert api.token not in dashboard.text and api.token not in str(dashboard.headers)
    assert 'Test User' in dashboard.text and 'Cerrar sesión' in dashboard.text
    assert 'Authorization' not in api.requests[0]['headers']


@pytest.mark.parametrize('email,password',[('user@example.invalid','wrong'),('inactive@example.invalid','correct')])
def test_invalid_login(frontend,email,password):
    c, api, _, _ = frontend
    page = c.get('/index.php?pagina=login')
    r = c.post('/index.php?pagina=login',data=dict(correo=email,password=password,csrf_token=csrf(page)))
    assert r.status_code == 401 and 'Credenciales inválidas.' in r.text
    assert f'value="{password}"' not in r.text
    assert c.get('/index.php?pagina=dashboard').status_code == 303


def test_me_failure_after_login_clears_auth(frontend):
    c, api, private, _ = frontend
    api.overrides['GET','/api/v1/auth/me']=(503,{'detail':'SECRET traceback'}, {})
    r = login(c)
    assert r.status_code == 503 and 'SECRET' not in r.text
    session = (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+c.cookies.get('PHPSESSID'))).read_text()
    assert api.token not in session
    assert c.get('/index.php?pagina=documentos').status_code == 303
    assert c.get('/index.php?pagina=login').status_code == 200


def test_anonymous_and_csrf(frontend):
    c, api, _, _ = frontend
    assert c.get('/index.php?pagina=documentos').status_code == 303
    assert c.get('/index.php?pagina=login').status_code == 200
    assert c.post('/index.php?pagina=login',data={'correo':'user@example.invalid','password':'correct','csrf_token':'bad'}).status_code == 403
    assert not api.requests


@pytest.mark.parametrize('failure',['expired','revoked','inactive'])
def test_invalidated_session(frontend,failure):
    c, api, private, _ = frontend
    assert login(c).status_code == 303
    old = c.cookies.get('PHPSESSID')
    api.overrides['GET','/api/v1/auth/me']=(401,{'detail':failure}, {})
    r = c.get('/index.php?pagina=documentos')
    assert r.status_code == 303 and c.cookies.get('PHPSESSID') != old
    assert not (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+old)).exists()
    page = c.get(r.headers['location'])
    assert page.status_code == 200 and 'La sesión expiró.' in page.text


@pytest.mark.parametrize('role,modules,create_doc,create_audit',[
    ('ADMIN',True,True,True),('AUDITOR_INTERNO',True,False,True),('AUDITOR_EXTERNO',True,False,False),
    ('RESPONSABLE_AREA',False,True,False),('APROBADOR',False,False,False)])
def test_navigation_and_allowed_auxiliary_calls(frontend,role,modules,create_doc,create_audit):
    c, api, _, _ = frontend
    assert login(c,role,api).status_code == 303
    api.requests.clear()
    r = c.get('/index.php?pagina=dashboard')
    assert r.status_code == 200
    assert ('href="index.php?pagina=auditorias"' in r.text) == modules
    assert ('href="index.php?pagina=evidencias"' in r.text) == modules
    assert sum(req['path']=='/api/v1/auth/me' for req in api.requests)==1
    assert any(req['path']=='/api/v1/auditorias' for req in api.requests)==modules
    assert not any(req['path']=='/api/v1/usuarios' for req in api.requests)
    r = c.get('/index.php?pagina=documentos')
    assert ('href="index.php?pagina=documento_nuevo"' in r.text) == create_doc
    r = c.get('/index.php?pagina=auditorias')
    assert r.status_code == (200 if modules else 403)
    if modules: assert ('href="index.php?pagina=auditoria_nueva"' in r.text)==create_audit
    api.requests.clear()
    r = c.get('/index.php?pagina=documento&id=1')
    assert r.status_code==200
    assert ('id="nueva-version"' in r.text)==create_doc
    assert ('href="#nueva-version"' in r.text)==create_doc
    assert ('Historial de trazabilidad' in r.text)==(role=='ADMIN')
    assert any(req['path'].endswith('/historial') for req in api.requests)==(role=='ADMIN')
    assert any(req['path']=='/api/v1/usuarios' for req in api.requests)==(role=='ADMIN')


def test_role_change_is_refreshed(frontend):
    c, api, _, _ = frontend
    login(c)
    api.role='APROBADOR'
    r=c.get('/index.php?pagina=dashboard')
    assert r.status_code==200 and 'APROBADOR' in r.text
    assert 'href="index.php?pagina=auditorias"' not in r.text


@pytest.mark.parametrize('status',[403,404,500,503])
def test_api_errors_preserve_auth(frontend,status):
    c, api, _, _ = frontend
    login(c)
    sid=c.cookies.get('PHPSESSID')
    api.overrides['GET','/api/v1/documentos/1']=(status,{'detail':'SECRET traceback'}, {})
    r=c.get('/index.php?pagina=documento&id=1')
    assert r.status_code==status and 'SECRET' not in r.text
    assert c.cookies.get('PHPSESSID')==sid
    assert c.get('/index.php?pagina=dashboard').status_code==200


def test_transport_failure_preserves_session(frontend):
    c, api, _, _ = frontend
    login(c);sid=c.cookies.get('PHPSESSID')
    api.drop.add('/api/v1/documentos/1')
    assert c.get('/index.php?pagina=documento&id=1').status_code==502
    assert c.cookies.get('PHPSESSID')==sid
    assert c.get('/index.php?pagina=dashboard').status_code==200


@pytest.mark.parametrize('remote',['success','invalid','transport'])
def test_logout(frontend,remote):
    c, api, private, _ = frontend
    login(c)
    page=c.get('/index.php?pagina=dashboard');sid=c.cookies.get('PHPSESSID')
    assert c.get('/index.php?pagina=logout').status_code==405
    assert c.post('/index.php?pagina=logout',data={'csrf_token':'bad'}).status_code==403
    assert c.cookies.get('PHPSESSID')==sid
    if remote=='invalid': api.valid=False
    if remote=='transport': api.drop.add('/api/v1/auth/logout')
    r=c.post('/index.php?pagina=logout',data={'csrf_token':csrf(page)})
    assert r.status_code==303 and c.cookies.get('PHPSESSID')!=sid
    text=c.get(r.headers['location']).text
    assert ('No pudo confirmarse' in text)==(remote=='transport')
    assert not (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+sid)).exists()
    assert c.get('/index.php?pagina=documentos').status_code==303
    if remote!='transport':
        assert api.requests[-1]['path']=='/api/v1/auth/logout'
        assert api.requests[-1]['headers']['Authorization']=='Bearer '+api.token
    if remote=='success': assert not api.valid


def test_xss_approver_metadata_and_ajax_expiry(frontend):
    c, api, _, _ = frontend
    api.name='<img src=x onerror=alert(1)>'
    api.document['titulo']='<script>alert(1)</script>'
    api.document['version_vigente']=None;api.document['version_vigente_id']=None
    login(c,'APROBADOR',api)
    r=c.get('/index.php?pagina=documento&id=1')
    assert 'No disponible' in r.text
    assert '<script>alert(1)</script>' not in r.text and '&lt;script&gt;' in r.text
    assert '<img src=x' not in r.text and '&lt;img' in r.text
    api.valid=False
    r=c.get('/index.php?pagina=versiones_documento&id=1',headers={'Accept':'application/json'})
    assert r.status_code==401 and r.json()=={'error':'session_expired'}
    assert c.get('/index.php?pagina=login').status_code==200


@pytest.mark.parametrize('role,page,api_path,payload',[
    ('RESPONSABLE_AREA','documento_nuevo','documentos',dict(codigo='NEW',titulo='New document',tipo='TEST',estado='DRAFT',area_id=1,responsable_id=8)),
    ('AUDITOR_INTERNO','auditoria_nueva','auditorias',dict(codigo='NEW',nombre='New audit',alcance='Test',responsable_id=8)),
    ('ADMIN','auditoria_nueva','auditorias',dict(codigo='NEW',nombre='New audit',alcance='Test',responsable_id=8)),
    ('AUDITOR_EXTERNO','evidencia_logica','evidencias/logica',dict(titulo='New evidence',auditoria_id=1,tipo='NOTE')),
])
def test_json_forms_actor_removal(frontend,role,page,api_path,payload):
    c, api, _, _ = frontend
    login(c,role,api)
    form=c.get('/index.php?pagina='+page)
    assert form.status_code==200
    assert all(f'name="{field}"' not in form.text for field in LEGACY)
    assert c.post('/index.php?pagina='+page,data={**payload,'csrf_token':'bad'}).status_code==403
    r=c.post('/index.php?pagina='+page,data={**payload,**dict.fromkeys(LEGACY,'999'),'csrf_token':csrf(form)})
    assert r.status_code==303,r.text
    req=next(req for req in reversed(api.requests) if req['method']=='POST' and req['path']=='/api/v1/'+api_path)
    assert req['headers']['Authorization']=='Bearer '+api.token
    assert not LEGACY.intersection(req['json']) and not any(field in req['query'] for field in LEGACY)
    if role in ['RESPONSABLE_AREA','AUDITOR_INTERNO']: assert req['json']['responsable_id']==7
    if role=='ADMIN':
        assert req['json']['responsable_id']==8
        assert any(req['query']=='elegibles_auditoria=true' for req in api.requests)


@pytest.mark.parametrize('role,page,path,fields',[
    ('RESPONSABLE_AREA','documento&id=1','documentos/1/versiones',{}),
    ('AUDITOR_EXTERNO','evidencia_archivo','evidencias/archivo',{'auditoria_id':'1','titulo':'File evidence'}),
])
def test_multipart_actor_and_csrf(frontend,role,page,path,fields):
    c, api, _, _ = frontend
    login(c,role,api)
    form=c.get('/index.php?pagina='+page)
    assert form.status_code==200
    assert all(f'name="{field}"' not in form.text for field in LEGACY)
    before=len([r for r in api.requests if r['method']=='POST'])
    denied=c.post('/index.php?pagina='+page,data={**fields,'csrf_token':'bad'},files={'archivo':('file.txt',b'test')})
    assert denied.status_code==403
    assert len([r for r in api.requests if r['method']=='POST'])==before
    r=c.post('/index.php?pagina='+page,data={**fields,**dict.fromkeys(LEGACY,'999'),'csrf_token':csrf(form)},files={'archivo':('file.txt',b'test')})
    assert r.status_code==303,r.text
    req=next(req for req in reversed(api.requests) if req['path']=='/api/v1/'+path and req['method']=='POST')
    assert not LEGACY.intersection(req['fields']) and req['fields']['archivo']==b'test'
    assert req['headers']['Authorization']=='Bearer '+api.token


def test_inconsistent_evidence_is_clean_form_error(frontend):
    c,api,_,_=frontend
    login(c,'AUDITOR_INTERNO',api)
    form=c.get('/index.php?pagina=evidencia_logica')
    assert 'debe estar vinculado' in form.text
    api.overrides['POST','/api/v1/evidencias/logica']=(404,{'detail':'SECRET policy'}, {})
    r=c.post('/index.php?pagina=evidencia_logica',data=dict(csrf_token=csrf(form),titulo='Evidence',auditoria_id=1,documento_id=1,tipo='NOTE'))
    assert r.status_code==404 and 'SECRET' not in r.text
    assert 'name="titulo"' in r.text and 'value="Evidence"' in r.text


def test_session_fixation_and_csrf_rotation(frontend):
    c, api, _, _ = frontend
    c.cookies.clear()
    c.cookies.set('PHPSESSID', 'attackerchosenunknownsessionid')
    form = c.get('/index.php?pagina=login')
    sid = c.cookies.get('PHPSESSID', domain='127.0.0.1', path='/')
    assert sid != 'attackerchosenunknownsessionid'
    c.cookies.clear()
    c.cookies.set('PHPSESSID', sid, domain='127.0.0.1', path='/')
    old_csrf = csrf(form)
    assert c.post('/index.php?pagina=login', data=dict(correo='user@example.invalid', password='correct', csrf_token=old_csrf)).status_code == 303
    dashboard = c.get('/index.php?pagina=dashboard')
    assert csrf(dashboard) != old_csrf
    assert c.post('/index.php?pagina=logout', data={'csrf_token': old_csrf}).status_code == 403
    assert not any(r['path'].endswith('/logout') for r in api.requests)


@pytest.mark.parametrize('https,secure', [('on', True), ('off', False)])
def test_session_cookie_configuration(tmp_path, https, secure):
    source = (ROOT / 'frontend/includes/session.php').as_posix()
    script = f'''require '{source}';
    $_SERVER['SCRIPT_NAME'] = '/trazabilidad/index.php';
    $_SERVER['HTTPS'] = '{https}';
    $ready = frontend_session_start();
    echo json_encode([$ready, session_get_cookie_params(), ini_get('session.use_strict_mode'), ini_get('session.use_only_cookies')]);
    session_destroy();'''
    result = subprocess.run([PHP, '-d', f'sys_temp_dir={tmp_path}', '-r', script], capture_output=True, text=True, check=True)
    ready, cookie, strict, only_cookies = json.loads(result.stdout)
    assert ready and strict == only_cookies == '1'
    assert cookie['secure'] is secure and cookie['httponly'] and cookie['samesite'] == 'Lax'
    assert cookie['path'] == '/trazabilidad/' and cookie['domain'] == ''


@pytest.mark.parametrize('status', [403, 404, 503])
def test_me_errors_on_existing_session_do_not_clear_auth(frontend, status):
    c, api, private, _ = frontend
    login(c)
    sid = c.cookies.get('PHPSESSID')
    api.overrides['GET', '/api/v1/auth/me'] = (status, {'detail': 'PRIVATE upstream failure'}, {})
    result = c.get('/index.php?pagina=dashboard')
    assert result.status_code == status and 'PRIVATE' not in result.text
    assert c.cookies.get('PHPSESSID') == sid
    del api.overrides['GET', '/api/v1/auth/me']
    assert c.get('/index.php?pagina=dashboard').status_code == 200


def test_legacy_fields_absent_from_all_frontend_forms_and_requests():
    # Output metadata is legitimate; only forms and outbound payloads must omit actors.
    for path in (ROOT / 'frontend/pages').glob('*.php'):
        source = path.read_text(encoding='utf-8')
        assert all(f'name="{field}"' not in source for field in LEGACY)
    for path in (ROOT / 'frontend/services').glob('*.php'):
        source = path.read_text(encoding='utf-8')
        assert all(field not in source for field in LEGACY)
