"""6C PHP routing, CSRF, escaping, server-only JWT and fragment handling."""
import json
import re
import secrets
import subprocess

import pytest
from conftest import ROOT, csrf, login

PUBLIC = {
    'solicitar_acceso':'/api/v1/auth/access-requests',
    'recuperar_password':'/api/v1/auth/password-reset/request',
    'restablecer_password':'/api/v1/auth/password-reset/confirm',
    'establecer_password':'/api/v1/auth/initial-password/confirm',
}
ROW = dict(id=1, nombre='<script>bad()</script>', identifier='applicant@example.invalid', motivo='<img src=x onerror=bad()>',
    status='PENDING', created_at='2026-10-01T00:00:00', resolved_by=None, resolved_at=None, approved_role=None, admin_reason=None)


@pytest.mark.parametrize('page', ['login',*PUBLIC])
def test_public_pages_headers_local_resources_labels(frontend, page):
    c, api, _, _ = frontend
    r = c.get('/index.php?pagina='+page)
    assert r.status_code == 200
    assert 'no-store' in r.headers['cache-control'] and r.headers['referrer-policy'] == 'no-referrer'
    assert "form-action 'self'" in r.headers['content-security-policy']
    assert 'Sistema de Trazabilidad' in r.text and 'auth-hero.svg' in r.text
    assert not re.search(r'(?:src|href)="https?://', r.text)
    assert 'name="csrf_token"' in r.text and not api.requests
    if page == 'login':
        assert 'Restablécela aquí' in r.text and 'Solicita acceso' in r.text
        assert 'autocomplete="username"' in r.text and 'autocomplete="current-password"' in r.text


@pytest.mark.parametrize('page', list(PUBLIC))
@pytest.mark.parametrize('bad_csrf', [None, 'wrong'])
def test_public_forms_csrf_before_api(frontend, page, bad_csrf):
    c, api, _, _ = frontend
    data = dict(correo='nobody@example.invalid', nombre='Test', motivo='Request access', token='A'*43,
                password='test-only-password', confirmation='test-only-password')
    if bad_csrf is not None: data['csrf_token'] = bad_csrf
    r = c.post('/index.php?pagina='+page, data=data)
    assert r.status_code == 403 and not api.requests


@pytest.mark.parametrize('page', ['solicitar_acceso','recuperar_password'])
def test_request_uniform_message_allowlisted_payload_and_no_jwt(frontend, page):
    c, api, _, _ = frontend
    api.overrides['POST',PUBLIC[page]] = (202, {'message':'PRIVATE upstream'}, {})
    login(c)  # Public requests must not accidentally forward the existing JWT.
    form = c.get('/index.php?pagina='+page)
    api.requests.clear()
    r = c.post('/index.php?pagina='+page, data=dict(csrf_token=csrf(form), correo='nobody@example.invalid',
        nombre='Applicant', motivo='Document review', rol='ADMIN', admin_id='999', recipient='attacker@example.com'))
    assert r.status_code == 202 and 'PRIVATE' not in r.text
    req = api.requests[-1]
    assert req['path'] == PUBLIC[page] and 'Authorization' not in req['headers']
    assert set(req['json']) == ({'nombre','correo','motivo'} if page == 'solicitar_acceso' else {'correo'})
    assert 'name="rol"' not in form.text


@pytest.mark.parametrize('page', ['restablecer_password','establecer_password'])
def test_password_confirm_rotates_session_and_no_autologin(frontend, page):
    c, api, private, _ = frontend
    login(c)
    old_sid = c.cookies.get('PHPSESSID')
    api.overrides['POST',PUBLIC[page]] = (200, {'message':'Changed'}, {})
    form = c.get('/index.php?pagina='+page)
    token = secrets.token_urlsafe(32)
    password = 'test-only-password'
    r = c.post('/index.php?pagina='+page, data=dict(csrf_token=csrf(form), token=token, password=password, confirmation=password))
    assert r.status_code == 303 and 'pagina=login' in r.headers['location']
    assert c.cookies.get('PHPSESSID') != old_sid
    session = (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+c.cookies.get('PHPSESSID'))).read_text()
    assert token not in session and password not in session and api.token not in session
    assert not (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+old_sid)).exists()
    assert api.requests[-1]['json'] == {'token':token,'password':password}
    assert 'Authorization' not in api.requests[-1]['headers']
    page_response = c.get(r.headers['location'])
    assert 'Contraseña' in page_response.text and token not in page_response.text
    assert c.get('/index.php?pagina=dashboard').status_code == 303
    assert token not in (private.parent/'php.log').read_text(encoding='utf-8')


@pytest.mark.parametrize('status', [400,422,429,503])
def test_password_error_never_reflects_token_or_password(frontend, status):
    c, api, private, _ = frontend
    path = PUBLIC['restablecer_password']
    api.overrides['POST',path] = (status, {'detail':'PRIVATE SMTP password'}, {'Retry-After':'30'})
    form = c.get('/index.php?pagina=restablecer_password')
    raw = secrets.token_urlsafe(32)
    r = c.post('/index.php?pagina=restablecer_password', data=dict(csrf_token=csrf(form), token=raw,
        password='new-password-test', confirmation='new-password-test'))
    assert r.status_code == status
    assert raw not in r.text and 'new-password-test' not in r.text and 'PRIVATE' not in r.text
    if status == 429: assert r.headers['retry-after'] == '30'
    assert raw not in (private.parent/'php.log').read_text(encoding='utf-8')


def test_php_password_mismatch_and_lengths_do_not_call_api(frontend):
    c, api, _, _ = frontend
    form = c.get('/index.php?pagina=restablecer_password')
    for password, confirmation in [('short','short'), ('a'*1025,'a'*1025), ('a'*12,'b'*12)]:
        r = c.post('/index.php?pagina=restablecer_password', data=dict(csrf_token=csrf(form), token='A'*43,
            password=password, confirmation=confirmation))
        assert r.status_code == 422
    assert not api.requests


def test_access_form_escapes_reflected_values(frontend):
    c, api, _, _ = frontend
    api.overrides['POST', PUBLIC['solicitar_acceso']] = (422, {}, {})
    form = c.get('/index.php?pagina=solicitar_acceso')
    r = c.post('/index.php?pagina=solicitar_acceso', data=dict(csrf_token=csrf(form),
        nombre='<script>bad()</script>', correo='x@example.invalid', motivo='</textarea><script>bad()</script>'))
    assert r.status_code == 422 and '<script>bad()' not in r.text
    assert '&lt;script&gt;bad()' in r.text


@pytest.mark.parametrize('role', ['AUDITOR_INTERNO','AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR'])
def test_php_admin_routes_forbidden(frontend, role):
    c, api, _, _ = frontend
    login(c, role, api)
    api.requests.clear()
    assert c.get('/index.php?pagina=solicitudes_acceso').status_code == 403
    assert c.get('/index.php?pagina=solicitud_acceso&id=1').status_code == 403
    assert c.post('/index.php?pagina=solicitud_acceso&id=1', data={'accion':'approve','rol':'ADMIN'}).status_code == 403
    assert all(r['path'] == '/api/v1/auth/me' for r in api.requests)


@pytest.mark.parametrize('action', ['approve','reject','resend'])
def test_admin_csrf_and_actor_allowlist(frontend, action):
    c, api, _, _ = frontend
    login(c)
    api.overrides['GET','/api/v1/access-requests/1'] = (200, ROW, {})
    api.overrides['POST','/api/v1/access-requests/1/'+action] = (200, ROW, {})
    form = c.get('/index.php?pagina=solicitud_acceso&id=1')
    assert form.status_code == 200 and '<script>bad()' not in form.text and '&lt;script&gt;' in form.text
    assert 'name="admin_id"' not in form.text and 'name="resolved_by"' not in form.text
    assert '<option value="">Selecciona explícitamente un rol</option>' in form.text
    api.requests.clear()
    r = c.post('/index.php?pagina=solicitud_acceso&id=1', data={'accion':action,'rol':'ADMIN','csrf_token':'bad'})
    assert r.status_code == 403 and not any(q['method'] == 'POST' for q in api.requests)
    r = c.post('/index.php?pagina=solicitud_acceso&id=1', data=dict(accion=action,rol='AUDITOR_INTERNO',motivo='No procede',
        csrf_token=csrf(form),admin_id='999',resolved_by='999'))
    assert r.status_code == 303
    req = next(q for q in reversed(api.requests) if q['method'] == 'POST')
    expected = {'rol':'AUDITOR_INTERNO'} if action == 'approve' else {'motivo':'No procede'} if action == 'reject' else {}
    assert req['json'] == expected
    assert req['headers']['Authorization'] == 'Bearer '+api.token


def test_admin_listing_and_missing_role(frontend):
    c, api, _, _ = frontend
    login(c)
    api.overrides['GET','/api/v1/access-requests'] = (200, [ROW], {})
    r = c.get('/index.php?pagina=solicitudes_acceso')
    assert r.status_code == 200 and 'solicitud_acceso&amp;id=1' in r.text
    assert '<script>bad()' not in r.text and '&lt;script&gt;' in r.text
    api.requests.clear()
    r = c.post('/index.php?pagina=solicitud_acceso&id=1', data={'accion':'approve','csrf_token':csrf(r)})
    assert r.status_code == 422 and not any(q['method'] == 'POST' for q in api.requests)


@pytest.mark.parametrize('fragment', ['#token='+'A'*43, '#token=bad', '#token=%3Cscript%3E', ''])
def test_fragment_script_executes_removes_url_and_clears_on_pagehide(fragment):
    source = ROOT / 'frontend/assets/js/password_reset.js'
    # Execute the real JS in a browser-shaped VM; actual browser layout is tested separately.
    code = r'''
const fs = require('fs'), vm = require('vm');
const input = {value:''}, status = {textContent:''}, events = {}, replaced = [];
const context = {URLSearchParams, window:{location:{hash:process.argv[2],pathname:'/index.php',search:'?pagina=restablecer_password'},
 addEventListener:(name, fn)=>events[name]=fn}, history:{replaceState:(...args)=>replaced.push(args)},
 document:{getElementById:id=>id==='action-token'?input:status}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const value = input.value;
events.pagehide();
console.log(JSON.stringify({value,after:input.value,replaced,leaked:context.actionToken!==undefined}));
'''
    result = subprocess.run(['node','-e',code,str(source),fragment],capture_output=True,text=True,check=True)
    output = json.loads(result.stdout)
    assert output['value'] == ('A'*43 if fragment == '#token='+'A'*43 else '')
    assert output['after'] == '' and not output['leaked']
    assert len(output['replaced']) == bool(fragment)
    if fragment: assert output['replaced'][0][2] == '/index.php?pagina=restablecer_password'
