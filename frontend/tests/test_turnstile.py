"""6B.4B PHP contract/CSRF/CSP tests against an isolated backend double."""
import json
import os
import re
import subprocess

import pytest
from conftest import PHP, ROOT, csrf

FLOWS = [
    ('login', '/api/v1/auth/login', 'login'),
    ('solicitar_acceso', '/api/v1/auth/access-requests', 'access_request'),
    ('recuperar_password', '/api/v1/auth/password-reset/request', 'password_reset_request'),
]
CHALLENGE = 'https://challenges.cloudflare.com'


def payload(response):
    return dict(csrf_token=csrf(response), correo=' user@example.invalid ', password='private-password-6b4b',
                nombre='Applicant', motivo='Review documents')


def required(action):
    return 428, dict(detail='PRIVATE upstream', challenge_required=True, challenge_action=action), {}


@pytest.mark.parametrize('page,path,action', FLOWS)
def test_backend_challenge_only_exact_scoped_csp_and_no_secret_reflection(turnstile_frontend, page, path, action):
    client, api, private, _ = turnstile_frontend
    form = client.get('/index.php?pagina='+page)
    assert CHALLENGE not in form.text and CHALLENGE not in form.headers['content-security-policy']
    api.overrides['POST', path] = required(action)
    data = payload(form)
    data.update(turnstile_token='private-turnstile-first-token', challenge_required='true', challenge_action='admin',
                rol='ADMIN', recipient='attacker@example.invalid', user_id='99')
    result = client.post('/index.php?pagina='+page, data=data)
    assert result.status_code == 428 and 'Completa la verificación para continuar.' in result.text
    assert 'PRIVATE upstream' not in result.text and f'data-action="{action}"' in result.text
    assert f'src="{CHALLENGE}/turnstile/v0/api.js"' in result.text
    csp = result.headers['content-security-policy']
    assert f"script-src 'self' {CHALLENGE};" in csp and f'frame-src {CHALLENGE};' in csp
    assert 'unsafe-' not in csp and '*' not in csp
    assert "style-src 'self'" in csp and "form-action 'self'" in csp and "frame-ancestors 'none'" in csp
    assert 'no-store' in result.headers['cache-control'] and result.headers['referrer-policy'] == 'no-referrer'
    assert 'value="user@example.invalid"' in result.text
    assert 'name="turnstile_token" value=""' in result.text
    assert 'private-password-6b4b' not in result.text and data['turnstile_token'] not in result.text
    request = api.requests[-1]
    assert request['json']['turnstile_token'] == data['turnstile_token']
    assert not {'rol','recipient','user_id','challenge_required','challenge_action'} & request['json'].keys()
    assert 'Authorization' not in request['headers']
    session = (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+client.cookies.get('PHPSESSID'))).read_text()
    assert 'turnstile_display' in session and 'private-password-6b4b' not in session and data['turnstile_token'] not in session
    assert 'user@example.invalid' not in session
    logs = (private.parent/'php.log').read_text(encoding='utf-8')
    assert data['turnstile_token'] not in logs and 'private-password-6b4b' not in logs


@pytest.mark.parametrize('page,path,action', FLOWS)
def test_no_client_flag_activates_challenge_and_csrf_runs_first(turnstile_frontend, page, path, action):
    client, api, _, _ = turnstile_frontend
    form = client.get('/index.php?pagina='+page)
    data = payload(form)
    data.update(csrf_token='bad', turnstile_token='client-value', challenge_required='true')
    assert client.post('/index.php?pagina='+page, data=data).status_code == 403
    assert not api.requests
    data['csrf_token'] = csrf(form)
    api.overrides['POST', path] = (422, {'challenge_required': True, 'challenge_action': action}, {})
    result = client.post('/index.php?pagina='+page, data=data)
    assert result.status_code == 422 and CHALLENGE not in result.text


@pytest.mark.parametrize('body', [
    {}, {'challenge_required': True}, {'challenge_required': 'true', 'challenge_action':'login'},
    {'challenge_required': True, 'challenge_action':'access_request'},
    {'challenge_required': True, 'challenge_action':'<script>bad</script>'},
    {'detail':{'challenge_required':True,'challenge_action':'login'}},
])
def test_malformed_or_wrong_action_challenge_is_not_rendered(turnstile_frontend, body):
    client, api, _, _ = turnstile_frontend
    form = client.get('/index.php?pagina=login')
    api.overrides['POST','/api/v1/auth/login'] = (428, body, {})
    result = client.post('/index.php?pagina=login', data=payload(form))
    assert result.status_code == 502 and CHALLENGE not in result.text


@pytest.mark.parametrize('status', [401, 422, 503])
def test_interaction_keeps_widget_but_never_previous_token(turnstile_frontend, status):
    client, api, _, _ = turnstile_frontend
    form = client.get('/index.php?pagina=login')
    api.overrides['POST','/api/v1/auth/login'] = required('login')
    challenged = client.post('/index.php?pagina=login', data=payload(form))
    api.overrides['POST','/api/v1/auth/login'] = (status, {'detail':'PRIVATE'}, {})
    data = payload(challenged)
    data['turnstile_token'] = 'used-token-never-store'
    result = client.post('/index.php?pagina=login', data=data)
    assert result.status_code == status and CHALLENGE in result.text
    assert data['turnstile_token'] not in result.text and data['password'] not in result.text
    assert 'name="turnstile_token" value=""' in result.text
    # Fresh interaction does not infer an ongoing challenge; backend decides again.
    fresh = client.get('/index.php?pagina=login')
    assert CHALLENGE not in fresh.text and CHALLENGE not in fresh.headers['content-security-policy']


def test_hard_lock_closes_widget_and_keeps_retry_after(turnstile_frontend):
    client, api, _, _ = turnstile_frontend
    form = client.get('/index.php?pagina=login')
    api.overrides['POST','/api/v1/auth/login'] = required('login')
    challenged = client.post('/index.php?pagina=login', data=payload(form))
    api.overrides['POST','/api/v1/auth/login'] = (429, {}, {'Retry-After':'60'})
    result = client.post('/index.php?pagina=login', data=payload(challenged))
    assert result.status_code == 429 and result.headers['retry-after'] == '60'
    assert CHALLENGE not in result.text and CHALLENGE not in result.headers['content-security-policy']


def test_missing_sitekey_fails_safe_without_external_resource(frontend, monkeypatch):
    client, api, _, web = frontend
    # Only mutate the isolated copied config; not the environment of the running process.
    config = web/'config/config.php'
    with config.open('a', encoding='utf-8') as file:
        file.write("\nputenv('TURNSTILE_SITE_KEY');\n")
    form = client.get('/index.php?pagina=login')
    api.overrides['POST','/api/v1/auth/login'] = required('login')
    result = client.post('/index.php?pagina=login', data=payload(form))
    assert result.status_code == 503 and 'No podemos completar la verificación' in result.text
    assert CHALLENGE not in result.text and CHALLENGE not in result.headers['content-security-policy']


@pytest.mark.parametrize('key,valid', [('',False), (' bad ',False), ('<script>',False), ('x'*257,False),
                                     ('1x00000000000000000000AA',True)])
def test_sitekey_environment_validation(key, valid):
    source = (ROOT/'frontend/config/config.php').as_posix()
    code = f"require '{source}'; echo json_encode(turnstile_site_key());"
    result = subprocess.run([PHP, '-r', code], env=dict(os.environ, TURNSTILE_SITE_KEY=key),
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == (key if valid else None)


@pytest.mark.parametrize('page,path', [
    ('restablecer_password','/api/v1/auth/password-reset/confirm'),
    ('establecer_password','/api/v1/auth/initial-password/confirm'),
])
def test_sensitive_token_page_never_turnstile_even_bad_backend_response(turnstile_frontend, page, path):
    client, api, private, _ = turnstile_frontend
    first = client.get('/index.php?pagina=login')
    api.overrides['POST','/api/v1/auth/login'] = required('login')
    assert client.post('/index.php?pagina=login', data=payload(first)).status_code == 428
    form = client.get('/index.php?pagina='+page+'#token='+'R'*43)
    api.overrides['POST',path] = required('login')
    result = client.post('/index.php?pagina='+page, data=dict(csrf_token=csrf(form), token='R'*43,
        password='private-password-6b4b', confirmation='private-password-6b4b', turnstile_token='discard-me'))
    for response in (form, result):
        assert CHALLENGE not in response.text and CHALLENGE not in response.headers['content-security-policy']
        assert 'turnstile.js' not in response.text and 'data-turnstile' not in response.text
        assert not re.search(r'(?:src|href)="https?://', response.text)
        assert 'no-store' in response.headers['cache-control'] and response.headers['referrer-policy'] == 'no-referrer'
        assert 'R'*43 not in response.text and 'private-password-6b4b' not in response.text
    assert api.requests[-1]['json'] == dict(token='R'*43, password='private-password-6b4b')
    assert 'R'*43 not in (private.parent/'php.log').read_text(encoding='utf-8')


@pytest.mark.parametrize('page,path,action', FLOWS)
def test_resolved_challenge_continues_normally(turnstile_frontend, page, path, action):
    client, api, private, _ = turnstile_frontend
    form = client.get('/index.php?pagina='+page)
    api.overrides['POST',path] = required(action)
    challenged = client.post('/index.php?pagina='+page, data=payload(form))
    if page == 'login': del api.overrides['POST',path]
    else: api.overrides['POST',path] = (202, {'message':'accepted'}, {})
    data = payload(challenged)
    data.update(password='correct', turnstile_token='one-new-token')
    result = client.post('/index.php?pagina='+page, data=data)
    assert result.status_code == (303 if page == 'login' else 202)
    assert CHALLENGE not in result.text
    session = (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+client.cookies.get('PHPSESSID'))).read_text()
    assert 'one-new-token' not in session and f'{action}|b:1' not in session
