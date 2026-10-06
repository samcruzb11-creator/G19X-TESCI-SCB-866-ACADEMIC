"""Real isolated Chrome, intercepted official URL, deterministic widget and API doubles."""
import base64
import json
import time

import pytest
from test_auth_browser import chromium, evaluate, navigate
from test_turnstile import CHALLENGE, FLOWS, required


STUB = r'''
(() => {
    const state = window.__turnstileTest = {options:null, resets:0, renders:0, removed:0};
    let frame;
    window.turnstile = {
        ready: callback => callback(),
        render: (container, options) => {
            state.options=options; state.renders++;
            frame=document.createElement('iframe');
            frame.title='Verificación de prueba'; frame.tabIndex=0;
            frame.width=options.size==='compact'?'150':String(container.clientWidth);
            frame.height=options.size==='compact'?'140':'65';
            frame.src='https://challenges.cloudflare.com/test-widget';
            container.append(frame);
            return 'offline-widget';
        },
        reset: () => { state.resets++; },
        remove: () => { state.removed++; if(frame) frame.remove(); },
    };
})();
'''


def offline_widget(params):
    url = params['request']['url']
    assert url.startswith(CHALLENGE+'/'), url
    if url == CHALLENGE+'/turnstile/v0/api.js':
        content, mime = STUB, 'application/javascript'
    else:
        assert url == CHALLENGE+'/test-widget', url
        content, mime = '<!doctype html><html lang="es"><body><label><input type="checkbox">Verificación de prueba</label></body></html>', 'text/html'
    return dict(responseCode=200, responseHeaders=[dict(name='Content-Type', value=mime+'; charset=utf-8')],
                body=base64.b64encode(content.encode()).decode())


def wait_for(cdp, condition):
    deadline = time.monotonic()+10
    while not evaluate(cdp, condition):
        assert time.monotonic() < deadline, condition
        time.sleep(.03)


def post_form(cdp, page, password='private-browser-password'):
    # Native submission exercises PHP with real cookies and CSRF from the document.
    fields = dict(correo='user@example.invalid', password=password, nombre='Browser Applicant', motivo='Review documents')
    evaluate(cdp, '(() => { const values='+json.dumps(fields)+''';
        for (const [name,value] of Object.entries(values)) {
            const field=document.querySelector('[name="'+name+'"]'); if(field) field.value=value;
        }
        document.querySelector('.auth-form').requestSubmit();
    })()''')


@pytest.mark.parametrize('page,path,action', FLOWS)
def test_real_adaptive_widget_responsive_expiry_reset_and_completion(turnstile_frontend, tmp_path, page, path, action):
    client, api, private, _ = turnstile_frontend
    base = str(client.base_url).rstrip('/')
    events = []
    with chromium(tmp_path, offline_widget, events) as cdp:
        cdp('Network.enable')
        cdp('Fetch.enable', patterns=[dict(urlPattern=CHALLENGE+'/*', requestStage='Request')])
        for width, height in [(1440,1000),(390,844),(320,700)]:
            cdp('Emulation.setDeviceMetricsOverride', width=width,height=height,deviceScaleFactor=1,mobile=False)
            navigate(cdp, base+'/index.php?pagina='+page)
            assert not evaluate(cdp, "!!document.querySelector('[data-turnstile]')")
            assert not evaluate(cdp, "[...document.scripts].some(s=>s.src.includes('cloudflare'))")
            api.overrides['POST',path] = required(action)
            post_form(cdp, page)
            wait_for(cdp, '!!window.__turnstileTest && !!window.__turnstileTest.options')
            assert evaluate(cdp, 'window.__turnstileTest.options.action') == action
            assert evaluate(cdp, 'window.__turnstileTest.options.retry') == 'never'
            assert evaluate(cdp, "window.__turnstileTest.options['response-field']") is False
            state = evaluate(cdp, '''(() => ({overflow:document.documentElement.scrollWidth>innerWidth,
                size:window.__turnstileTest.options.size, available:document.getElementById('turnstile-widget').clientWidth,
                password:document.getElementById('password')?.value || '',
                email:document.getElementById('correo').value, status:document.getElementById('verification-status').getAttribute('aria-live')}))()''')
            assert not state['overflow'] and state['password'] == '' and state['email'] == 'user@example.invalid'
            assert state['status'] == 'polite'
            assert state['size'] == ('flexible' if width == 1440 else 'compact')
            full_height = evaluate(cdp, 'document.documentElement.scrollHeight')
            screenshot = cdp('Page.captureScreenshot', format='png', captureBeyondViewport=True,
                clip=dict(x=0, y=0, width=width, height=full_height, scale=1))
            (tmp_path/f'{action}-challenged-{width}.png').write_bytes(base64.b64decode(screenshot['data']))

        if page == 'login':
            evaluate(cdp, "document.getElementById('correo').focus()")
            cdp('Input.dispatchKeyEvent', type='keyDown', key='Tab', code='Tab', windowsVirtualKeyCode=9)
            cdp('Input.dispatchKeyEvent', type='keyUp', key='Tab', code='Tab', windowsVirtualKeyCode=9)
            assert evaluate(cdp, 'document.activeElement.id') == 'password'

        # Missing client token blocks submission and offers keyboard-accessible feedback.
        before = len(api.requests)
        post_form(cdp, page)
        assert len(api.requests) == before
        assert evaluate(cdp, 'document.activeElement.id') == 'verification-status'
        for callback in ['expired-callback','timeout-callback','error-callback']:
            evaluate(cdp, "window.__turnstileTest.options.callback('test-token-before-expiry')")
            assert evaluate(cdp, "document.querySelector('[name=turnstile_token]').value") == ''
            evaluate(cdp, f"window.__turnstileTest.options['{callback}']()")
            assert evaluate(cdp, "document.querySelector('[name=turnstile_token]').value") == ''
            assert not evaluate(cdp, "document.querySelector('.verification-retry').hidden")
            post_form(cdp, page)
            assert len(api.requests) == before
            evaluate(cdp, "document.querySelector('.verification-retry').click()")
        assert evaluate(cdp, 'window.__turnstileTest.resets') == 3
        assert evaluate(cdp, 'window.__turnstileTest.renders') == 1  # No challenge/reload loops.

        # A rejected single-use token produces a fresh widget, without restoring
        # either credential. The second submit must await another completion.
        evaluate(cdp, "window.__turnstileTest.options.callback('rejected-browser-token'); window.__oldChallengePage=true")
        post_form(cdp, page)
        wait_for(cdp, '!window.__oldChallengePage && !!window.__turnstileTest?.options')
        assert len(api.requests) == before + 1
        assert evaluate(cdp, "document.querySelector('[name=turnstile_token]').value") == ''
        assert evaluate(cdp, "document.querySelector('input[type=password]')?.value || ''") == ''
        post_form(cdp, page)
        assert len(api.requests) == before + 1

        # Back/forward cache lifecycle destroys the old credential and widget.
        evaluate(cdp, "window.__turnstileTest.options.callback('bfcache-must-discard')")
        evaluate(cdp, "window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}))")
        evaluate(cdp, "window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))")
        assert evaluate(cdp, 'window.__turnstileTest.removed') == 1
        assert evaluate(cdp, 'window.__turnstileTest.renders') == 2
        post_form(cdp, page)
        assert len(api.requests) == before + 1

        # Callback output is transient DOM state, never an attribute/storage entry.
        evaluate(cdp, "window.__turnstileTest.options.callback('single-use-browser-token')")
        assert not evaluate(cdp, "document.documentElement.outerHTML.includes('single-use-browser-token')")
        assert evaluate(cdp, 'localStorage.length + sessionStorage.length') == 0
        if page == 'login': del api.overrides['POST',path]
        else: api.overrides['POST',path] = (202, {'message':'accepted'}, {})
        post_form(cdp, page, password='correct')
        wait_for(cdp, "document.readyState === 'complete' && !document.querySelector('[data-turnstile]')")
        request = next(r for r in reversed(api.requests) if r['method']=='POST' and r['path']==path)
        assert request['json']['turnstile_token'] == 'single-use-browser-token'
        if page == 'login': assert evaluate(cdp, 'location.search') == '?pagina=dashboard'
        else: assert evaluate(cdp, "document.querySelector('[role=status]').textContent").strip()

    logs = (private.parent/'php.log').read_text(encoding='utf-8')
    assert 'single-use-browser-token' not in logs and 'private-browser-password' not in logs
    cf_requests = [event['params']['request'] for event in events if event.get('method')=='Network.requestWillBeSent'
                   and event['params']['request']['url'].startswith(CHALLENGE)]
    assert cf_requests
    for request in cf_requests:
        assert all(not value for name, value in request['headers'].items() if name.lower() == 'referer'), request
        assert 'private-browser-password' not in json.dumps(request) and 'user@example.invalid' not in json.dumps(request)


@pytest.mark.parametrize('page', ['restablecer_password','establecer_password'])
def test_real_sensitive_fragment_has_no_external_requests_and_cleans_bfcache(turnstile_frontend, tmp_path, page):
    client, api, private, _ = turnstile_frontend
    base = str(client.base_url).rstrip('/')
    raw = 'SensitiveFragmentTokenNeverExternal12345678'
    assert len(raw) == 43
    events = []
    with chromium(tmp_path, offline_widget, events) as cdp:
        cdp('Network.enable')
        cdp('Fetch.enable', patterns=[dict(urlPattern=CHALLENGE+'/*', requestStage='Request')])
        navigate(cdp, base+'/index.php?pagina='+page+'#token='+raw)
        assert evaluate(cdp, 'location.hash') == ''
        assert evaluate(cdp, "document.getElementById('action-token').value") == raw
        assert not evaluate(cdp, f'document.documentElement.outerHTML.includes({json.dumps(raw)})')
        assert not evaluate(cdp, "[...document.scripts].some(s=>s.src.includes('cloudflare'))")
        assert not evaluate(cdp, "!!document.querySelector('iframe')")
        evaluate(cdp, "window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}))")
        assert evaluate(cdp, "document.getElementById('action-token').value") == ''
        assert evaluate(cdp, 'localStorage.length + sessionStorage.length') == 0
    requests = [event['params']['request'] for event in events if event.get('method')=='Network.requestWillBeSent']
    assert requests and all(r['url'].startswith(base) for r in requests)
    assert all(raw not in r['url'] and raw not in json.dumps(r['headers']) for r in requests)
    assert raw not in (private.parent/'php.log').read_text(encoding='utf-8') and not api.requests


def keyboard_submit_without_page_js(cdp, password='correct'):
    root = cdp('DOM.getDocument')['root']['nodeId']
    for name, value in dict(correo='user@example.invalid', password=password,
                            nombre='Keyboard Applicant', motivo='Review documents').items():
        node = cdp('DOM.querySelector', nodeId=root, selector=f'[name="{name}"]')['nodeId']
        if node:
            cdp('DOM.focus', nodeId=node)
            cdp('Input.dispatchKeyEvent', type='keyDown', key='a', code='KeyA', modifiers=2, windowsVirtualKeyCode=65)
            cdp('Input.dispatchKeyEvent', type='keyUp', key='a', code='KeyA', modifiers=2, windowsVirtualKeyCode=65)
            cdp('Input.insertText', text=value)
    node = cdp('DOM.querySelector', nodeId=root, selector='button[type="submit"]')['nodeId']
    assert evaluate(cdp, "document.querySelector('.auth-form').checkValidity()"), 'Native form fields must be valid'
    cdp('DOM.focus', nodeId=node)
    # CDP instrumentation can inspect/mark a page even with its scripts disabled.
    evaluate(cdp, 'window.__oldNoJsDocument=true')
    cdp('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', text='\r', windowsVirtualKeyCode=13)
    cdp('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    wait_for(cdp, "!window.__oldNoJsDocument && document.readyState === 'complete'")


@pytest.mark.parametrize('page,path,action', FLOWS)
def test_javascript_disabled_challenge_has_explanation_and_cannot_continue(turnstile_frontend, tmp_path, page, path, action):
    client, api, private, _ = turnstile_frontend
    base = str(client.base_url).rstrip('/')
    api.overrides['POST', path] = required(action)
    events = []
    with chromium(tmp_path, offline_widget, events) as cdp:
        cdp('Network.enable')
        cdp('Fetch.enable', patterns=[dict(urlPattern=CHALLENGE+'/*', requestStage='Request')])
        cdp('Emulation.setScriptExecutionDisabled', value=True)
        navigate(cdp, base+'/index.php?pagina='+page)
        for attempt in range(2):
            keyboard_submit_without_page_js(cdp)
            assert evaluate(cdp, "document.body.innerText.includes('La verificación requiere JavaScript')")
            assert evaluate(cdp, "document.body.innerText.includes('Completa la verificación para continuar.')")
            assert evaluate(cdp, 'location.search') == '?pagina='+page
            assert len(api.requests) == attempt + 1
            assert not api.requests[-1]['json'].get('turnstile_token')
            assert not evaluate(cdp, '!!window.turnstile')
            assert evaluate(cdp, "document.querySelector('input[type=password]')?.value || ''") == ''
    assert not any(event['params']['request']['url'].startswith(CHALLENGE)
        for event in events if event.get('method') == 'Network.requestWillBeSent')


def test_javascript_disabled_normal_login_still_works(turnstile_frontend, tmp_path):
    client, api, _, _ = turnstile_frontend
    with chromium(tmp_path) as cdp:
        cdp('Emulation.setScriptExecutionDisabled', value=True)
        navigate(cdp, str(client.base_url).rstrip('/')+'/index.php?pagina=login')
        keyboard_submit_without_page_js(cdp)
        assert evaluate(cdp, 'location.search') == '?pagina=dashboard'
        assert not evaluate(cdp, "!!document.querySelector('[data-turnstile]')")
        login = next(r for r in api.requests if r['path'] == '/api/v1/auth/login')
        assert login['json'] == {'correo': 'user@example.invalid', 'password': 'correct'}
