"""Real authenticated PHP -> FastAPI -> guarded MySQL, resource -> changed dashboard."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
from threading import Thread
import socket
import time
import os
import base64
import pytest
import uvicorn
from sqlalchemy import select
from tests_unit.test_dashboard_unit import dashboard
from tests_unit.test_aprobacion_unit import approvals
from tests_unit.test_rbac_unit import rbac
from app.main import app
from app.api.dependencies import current_user
from app.db.session import get_db
from app.core.security import hash_password
from app.models.entities import Usuario, Hallazgo

MYSQL_RBAC = True
ROOT = Path(__file__).resolve().parents[2]
PASSWORD = 'Only-temporary-7D-password!42'


def harness(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@contextmanager
def real_stack(fixture,mysql_factory,tmp_path):
    _,db,_,_=fixture
    digest=hash_password(PASSWORD)
    for id in (1,2,3,4,5):db.get(Usuario,id).password_hash=digest
    db.commit();db.rollback()
    def isolated_db():
        with mysql_factory() as session:yield session
    overrides=app.dependency_overrides.copy()
    app.dependency_overrides[get_db]=isolated_db
    app.dependency_overrides.pop(current_user,None)
    php=harness('php_dashboard_harness',ROOT/'frontend/tests/conftest.py')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=Thread(target=server.run,daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started:
            assert thread.is_alive() and time.monotonic()<deadline
            time.sleep(.05)
        with php.php_server(tmp_path/'php_real',f'http://127.0.0.1:{port}') as stack:
            yield stack,php
    finally:
        server.should_exit=True;thread.join(timeout=10)
        app.dependency_overrides.clear();app.dependency_overrides.update(overrides)
        assert not thread.is_alive()


def test_real_login_dashboard_alert_close_finding_refresh_all_roles(dashboard,mysql_factory,tmp_path):
    _,fixture,_,_=dashboard
    with real_stack(dashboard,mysql_factory,tmp_path) as ((php,private,web),helper):
        def login(id):
            page=php.get('/index.php?pagina=login')
            result=php.post('/index.php?pagina=login',data=dict(csrf_token=helper.csrf(page),
                correo=f'{id}@example.invalid',password=PASSWORD))
            assert result.status_code==303,result.text
        login(1)
        page=php.get('/index.php?pagina=dashboard')
        assert page.status_code==200 and 'data-kpi="hallazgos">20' in page.text
        assert '20,00%' in page.text and 'data-kpi="auditorias">4' in page.text
        alerts=php.get('/index.php?pagina=alertas&tipo=HALLAZGO_PENDIENTE')
        assert '12 alertas' in alerts.text
        with mysql_factory() as check:
            finding=check.scalar(select(Hallazgo).where(Hallazgo.auditoria_id==1,Hallazgo.numero==3))
            id=finding.id;stamp=finding.updated_at.isoformat()
        assert f'pagina=hallazgo&amp;id={id}' in alerts.text
        resource=php.get(f'/index.php?pagina=hallazgo&id={id}')
        assert resource.status_code==200
        response=php.post(f'/index.php?pagina=hallazgo&id={id}',data=dict(csrf_token=helper.csrf(resource),
            accion='estado',estado='CLOSED',estado_esperado='PENDING_VERIFICATION',updated_at_esperado=stamp,
            resolucion='<svg onload=window.dashboard_xss=1>Verified</svg>'))
        assert response.status_code==303,response.text
        assert 'Cerrado' in php.get(response.headers['location']).text
        page=php.get('/index.php?pagina=dashboard')
        assert '25,00%' in page.text
        alerts=php.get('/index.php?pagina=alertas&tipo=HALLAZGO_PENDIENTE')
        assert '11 alertas' in alerts.text and f'pagina=hallazgo&amp;id={id}' not in alerts.text
        with mysql_factory() as check:assert check.get(Hallazgo,id).estado=='CLOSED'
        for id,audits,docs in [(2,2,2),(3,1,1),(4,None,3),(5,None,2)]:
            login(id);page=php.get('/index.php?pagina=dashboard')
            assert page.status_code==200 and f'data-kpi="documentos">{docs}' in page.text
            if audits is None:assert 'data-kpi="auditorias"' not in page.text
            else:assert f'data-kpi="auditorias">{audits}' in page.text
            assert 'eyJ' not in page.text and PASSWORD not in page.text
        assert PASSWORD not in (private.parent/'php.log').read_text(encoding='utf-8')


@pytest.mark.skipif(os.environ.get('AUTH_BROWSER_TEST')!='1',reason='Explicit isolated Chrome opt-in required')
def test_chrome_real_php_api_mysql_dashboard_resource_refresh(dashboard,mysql_factory,tmp_path):
    with real_stack(dashboard,mysql_factory,tmp_path) as ((php,_,_),helper):
        browser=harness('chrome_dashboard_harness',ROOT/'frontend/tests/test_auth_browser.py')
        with browser.chromium(tmp_path) as cdp:
            base=str(php.base_url).rstrip('/')
            cdp('Emulation.setDeviceMetricsOverride',width=320,height=800,deviceScaleFactor=1,mobile=False)
            def go(url,condition):
                cdp('Page.navigate',url=url);wait(condition)
            def wait(condition):
                deadline=time.monotonic()+15
                while not browser.evaluate(cdp,"document.readyState==='complete' && ("+condition+")"):
                    assert time.monotonic()<deadline,condition
                    time.sleep(.05)
            go(base+'/index.php?pagina=login',"!!document.getElementById('password')")
            browser.evaluate(cdp,"document.getElementById('correo').value='1@example.invalid';document.getElementById('password').value='"+PASSWORD+"';document.querySelector('.auth-form').requestSubmit()")
            wait("!!document.querySelector('[data-kpi=hallazgos]')")
            assert browser.evaluate(cdp,"document.querySelector('[data-kpi=hallazgos]').textContent")=='20'
            (tmp_path/'dashboard-real-320.png').write_bytes(base64.b64decode(cdp('Page.captureScreenshot',format='png',captureBeyondViewport=True)['data']))
            overflow=browser.evaluate(cdp,"[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.slice(0,120),width:e.getBoundingClientRect().width}))")
            assert not browser.evaluate(cdp,'document.documentElement.scrollWidth>innerWidth'),overflow
            with mysql_factory() as check:
                id=check.scalar(select(Hallazgo.id).where(Hallazgo.auditoria_id==1,Hallazgo.numero==3))
            go(base+'/index.php?pagina=alertas&tipo=HALLAZGO_PENDIENTE',"document.body.textContent.includes('12 alertas')")
            browser.evaluate(cdp,f"document.querySelector('a[href=\"index.php?pagina=hallazgo&id={id}\"]').click()")
            wait("!!document.getElementById('resolucion')")
            browser.evaluate(cdp,"document.getElementById('estado').value='CLOSED';document.getElementById('resolucion').value='<img src=x onerror=window.dashboard_xss=1>';document.querySelector('input[name=accion][value=estado]').form.requestSubmit()")
            wait("document.body.textContent.includes('Hallazgo actualizado correctamente')")
            assert browser.evaluate(cdp,'typeof window.dashboard_xss')=='undefined'
            go(base+'/index.php?pagina=dashboard',"document.body.textContent.includes('25,00%')")
            assert not browser.evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
            assert not browser.evaluate(cdp,"document.documentElement.outerHTML.includes('eyJ')")
            go(base+'/index.php?pagina=alertas&tipo=HALLAZGO_PENDIENTE',"document.body.textContent.includes('11 alertas')")
            assert not browser.evaluate(cdp,f"!!document.querySelector('a[href=\"index.php?pagina=hallazgo&id={id}\"]')")
