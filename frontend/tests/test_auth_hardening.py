"""PHP session/configuration and sanitized rate-limit UX."""
import json
import os
import subprocess

import pytest
from conftest import PHP, ROOT, csrf


@pytest.mark.parametrize('mode,https,secure', [
    ('auto', 'off', False), ('auto', 'on', True), ('always', 'off', True),
])
def test_gc_and_cookie_configuration(tmp_path, mode, https, secure):
    source = (ROOT / 'frontend/includes/session.php').as_posix()
    code = f'''require '{source}';
    $_SERVER['SCRIPT_NAME'] = '/index.php'; $_SERVER['HTTPS'] = '{https}';
    $_SERVER['HTTP_X_FORWARDED_PROTO'] = 'https';
    $ready = frontend_session_start();
    echo json_encode([$ready, session_get_cookie_params(), ini_get('session.save_handler'),
      ini_get('session.gc_maxlifetime'), ini_get('session.gc_probability'), ini_get('session.gc_divisor')]);
    session_destroy();'''
    env = dict(os.environ, FRONTEND_COOKIE_SECURE=mode)
    r = subprocess.run([PHP, '-d', f'sys_temp_dir={tmp_path}', '-r', code],
                       env=env, capture_output=True, text=True, check=True)
    ready, cookie, handler, lifetime, probability, divisor = json.loads(r.stdout)
    assert ready and cookie['secure'] is secure
    assert (handler, lifetime, probability, divisor) == ('files', '1800', '1', '100')


@pytest.mark.parametrize('mode', ['', 'never', 'AUTO', 'always '])
def test_invalid_cookie_configuration_fails_without_session(tmp_path, mode):
    source = (ROOT / 'frontend/includes/session.php').as_posix()
    code = f"require '{source}'; echo json_encode([frontend_session_start(), session_status(), headers_list()]);"
    r = subprocess.run([PHP, '-d', f'sys_temp_dir={tmp_path}', '-r', code],
        env=dict(os.environ, FRONTEND_COOKIE_SECURE=mode), capture_output=True, text=True, check=True)
    ready, status, headers = json.loads(r.stdout)
    assert not ready and status == 1
    assert not any('Set-Cookie' in h for h in headers)
    assert not list(tmp_path.rglob('sess_*'))


def test_active_session_survives_gc(tmp_path):
    source = (ROOT / 'frontend/includes/session.php').as_posix()
    # Native GC, not a handcrafted file deletion; a session younger than JWT TTL survives.
    code = f'''require '{source}';
    if (!frontend_session_start()) exit(2);
    $_SESSION['marker'] = 'active'; $sid = session_id(); $path = session_save_path();
    session_write_close(); touch($path . '/sess_' . $sid, time() - 899);
    session_id($sid); session_start(); session_gc();
    echo json_encode([$_SESSION['marker'], is_file($path . '/sess_' . $sid)]);
    session_destroy();'''
    r = subprocess.run([PHP, '-d', f'sys_temp_dir={tmp_path}', '-r', code],
                       capture_output=True, text=True, check=True)
    assert json.loads(r.stdout) == ['active', True]


def test_rate_limit_keeps_anonymous_session_and_csrf(frontend):
    c, api, private, _ = frontend
    page = c.get('/index.php?pagina=login')
    sid, token = c.cookies.get('PHPSESSID'), csrf(page)
    api.overrides['POST', '/api/v1/auth/login'] = (429, {'detail': 'PRIVATE identifier/password'}, {'Retry-After':'37'})
    r = c.post('/index.php?pagina=login', data={'correo':'nobody@example.invalid','password':'private','csrf_token':token})
    assert r.status_code == 429 and r.headers['retry-after'] == '37'
    assert 'no-store' in r.headers['cache-control'].split(', ')
    assert 'Demasiados intentos. Intente nuevamente más tarde.' in r.text
    assert 'PRIVATE' not in r.text and 'Location' not in r.headers
    assert c.cookies.get('PHPSESSID') == sid and csrf(r) == token
    session = (private / 'sistema-trazabilidad-frontend-sessions' / ('sess_' + sid)).read_text()
    assert 'access_token' not in session
    assert c.get('/index.php?pagina=login').status_code == 200


@pytest.mark.parametrize('value,expected', [('10',10), ('3',3), ('0',None), ('-1',None), ('abc',None), ('121',None)])
def test_auth_timeout_validation(value, expected):
    source = (ROOT / 'frontend/config/config.php').as_posix()
    code = f"require '{source}'; try {{ echo auth_api_timeout_seconds(); }} catch (RuntimeException $e) {{ echo 'invalid'; }}"
    r = subprocess.run([PHP, '-r', code], env=dict(os.environ, AUTH_API_TIMEOUT_SECONDS=value),
                       capture_output=True, text=True, check=True)
    assert r.stdout == ('invalid' if expected is None else str(expected))


def test_auth_timeout_applies_without_changing_upload_timeout(tmp_path):
    source = (ROOT / 'frontend/services/api_client.php').as_posix()
    # Disable only transport functions in the subprocess, capture the actual cURL options.
    code = f'''function curl_init($url) {{ return new stdClass(); }}
    function curl_setopt_array($h, $options) {{ $GLOBALS['options'] = $options; return true; }}
    function curl_setopt($h, $key, $value) {{ return true; }}
    function curl_exec($h) {{ return '{{"ok":true}}'; }}
    function curl_getinfo($h, $key) {{ return 200; }}
    function curl_close($h) {{}}
    require '{source}';
    $_SESSION = ['auth' => ['access_token' => 'test-only']];
    $timeouts = [];
    foreach (['/api/v1/auth/login','/api/v1/auth/logout','/api/v1/documentos'] as $path) {{
      api_request('POST', $path, [], null, $path === '/api/v1/auth/logout' ? null : []);
      $timeouts[] = $GLOBALS['options'][CURLOPT_TIMEOUT];
    }}
    echo json_encode($timeouts);'''
    disabled = 'curl_init,curl_setopt_array,curl_setopt,curl_exec,curl_getinfo,curl_close'
    r = subprocess.run([PHP, '-d', 'disable_functions=' + disabled, '-r', code],
                       env=dict(os.environ, AUTH_API_TIMEOUT_SECONDS='7'), capture_output=True, text=True, check=True)
    assert json.loads(r.stdout) == [7,7,120]
