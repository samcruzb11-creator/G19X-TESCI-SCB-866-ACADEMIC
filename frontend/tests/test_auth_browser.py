"""Opt-in real headless Chromium: local isolated PHP only, no installed browser profile."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import time

import httpx
import pytest
from websockets.sync.client import connect


@contextmanager
def chromium(tmp_path, request_handler=None, events=None):
    if os.environ.get('AUTH_BROWSER_TEST') != '1':
        pytest.skip('Opt in with AUTH_BROWSER_TEST=1 for isolated headless Chrome')
    executable = Path(os.environ.get('CHROME_TEST_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))
    assert executable.is_file(), 'Set CHROME_TEST_BINARY to a local Chromium binary'
    profile = tmp_path / 'chrome-profile'
    with (tmp_path/'chrome.log').open('wb') as log:
        proc = subprocess.Popen([str(executable), '--headless=new', '--disable-gpu', '--no-first-run',
            '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
            '--disable-sync', '--disable-extensions', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
            '--user-data-dir='+str(profile), 'about:blank'], stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic()+15
            active = profile/'DevToolsActivePort'
            while not active.exists():
                assert time.monotonic() < deadline and proc.poll() is None, 'Headless browser startup failed'
                time.sleep(.05)
            port = int(active.read_text().splitlines()[0])
            targets = httpx.get(f'http://127.0.0.1:{port}/json/list').json()
            target = next(t for t in targets if t['type'] == 'page')
            with connect(target['webSocketDebuggerUrl'], open_timeout=10) as ws:
                sequence = 0
                def command(method, **params):
                    nonlocal sequence
                    sequence += 1
                    command_id = sequence
                    ws.send(json.dumps(dict(id=command_id, method=method, params=params)))
                    while True:
                        response = json.loads(ws.recv(timeout=15))
                        if response.get('method') and events is not None:
                            events.append(response)
                        if response.get('method') == 'Fetch.requestPaused' and request_handler is not None:
                            fulfillment = request_handler(response['params'])
                            sequence += 1
                            ws.send(json.dumps(dict(id=sequence, method='Fetch.fulfillRequest', params={
                                'requestId':response['params']['requestId'], **fulfillment})))
                        if response.get('id') == command_id:
                            assert 'error' not in response, response
                            return response.get('result', {})
                command('Page.enable')
                yield command
        finally:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def evaluate(cdp, expression):
    result = cdp('Runtime.evaluate', expression=expression, returnByValue=True)
    assert 'exceptionDetails' not in result, result
    return result['result'].get('value')


def navigate(cdp, url):
    cdp('Page.navigate', url=url)
    deadline = time.monotonic()+10
    while not evaluate(cdp, "document.readyState === 'complete' && !!document.querySelector('.auth-form')"):
        assert time.monotonic() < deadline, 'Auth document did not render'
        time.sleep(.05)


def test_real_responsive_login_fragment_keyboard_and_no_token_in_requests(frontend, tmp_path):
    client, api, private, _ = frontend
    base = str(client.base_url).rstrip('/')
    with chromium(tmp_path) as cdp:
        for width, height in [(1440,1000),(390,844),(320,700)]:
            cdp('Emulation.setDeviceMetricsOverride', width=width,height=height,deviceScaleFactor=1,mobile=False)
            navigate(cdp, base+'/index.php?pagina=login')
            state = evaluate(cdp, """(() => {
                const form=document.querySelector('.auth-form-inner'), hero=document.querySelector('.auth-hero');
                return {width:form.getBoundingClientRect().width, overflow:document.documentElement.scrollWidth>innerWidth,
                    hero:getComputedStyle(hero).display, columns:getComputedStyle(document.querySelector('.auth-layout')).gridTemplateColumns,
                    labels:[...document.querySelectorAll('input:not([type=hidden])')].every(i=>!!document.querySelector('label[for="'+i.id+'"]'))};
            })()""")
            assert not state['overflow'] and state['labels']
            if width == 1440: assert 380 <= state['width'] <= 430 and state['hero'] != 'none'
            else: assert state['hero'] == 'none' and state['width'] <= width-40
            screenshot = cdp('Page.captureScreenshot', format='png')['data']
            (tmp_path/f'login-{width}.png').write_bytes(base64.b64decode(screenshot))
        evaluate(cdp, "document.getElementById('correo').focus()")
        cdp('Input.dispatchKeyEvent', type='keyDown', key='Tab', code='Tab', windowsVirtualKeyCode=9)
        cdp('Input.dispatchKeyEvent', type='keyUp', key='Tab', code='Tab', windowsVirtualKeyCode=9)
        assert evaluate(cdp, 'document.activeElement.id') == 'password'
        raw = 'B'*43
        navigate(cdp, base+'/index.php?pagina=restablecer_password#token='+raw)
        assert evaluate(cdp, 'location.hash') == ''
        assert evaluate(cdp, "document.getElementById('action-token').value") == raw
        assert evaluate(cdp, "document.getElementById('action-token').getAttribute('value')") is None
        assert not evaluate(cdp, "document.documentElement.outerHTML.includes('"+raw+"')")
        assert evaluate(cdp, 'localStorage.length + sessionStorage.length') == 0
    assert raw not in (private.parent/'php.log').read_text(encoding='utf-8')
    assert not api.requests
