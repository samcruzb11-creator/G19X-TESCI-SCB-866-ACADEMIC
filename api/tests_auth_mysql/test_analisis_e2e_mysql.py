"""Real PHP -> authenticated FastAPI -> ephemeral MySQL/storage, no API mocks."""
from urllib.parse import parse_qs, urlsplit
import re
import os
import pytest
import httpx
from sqlalchemy import select, event
from tests_unit.test_analisis_unit import analysis, get, stable
from tests_unit.test_aprobacion_unit import approvals
from tests_unit.test_rbac_unit import rbac
from tests_auth_mysql.test_dashboard_e2e_mysql import real_stack,harness,ROOT,PASSWORD
from app.models.entities import Usuario, Documento, VersionDocumento, DocumentoAuditoria
from app.core.security import hash_password

MYSQL_RBAC=True


def login(php,helper,uid):
    page=php.get('/index.php?pagina=login')
    response=php.post('/index.php?pagina=login',data=dict(csrf_token=helper.csrf(page),
        correo=f'{uid}@example.invalid',password=PASSWORD))
    assert response.status_code==303,response.text


def token(private,php):
    # JWT remains private to the isolated PHP session. Never print or save it.
    raw=(private/'sistema-trazabilidad-frontend-sessions'/('sess_'+php.cookies.get('PHPSESSID'))).read_text()
    return re.search(r's:12:"access_token";s:\d+:"([^"]+)"',raw)[1]


def test_real_login_create_upload_identical_files_analysis_and_resource_link(analysis,mysql_factory,tmp_path):
    with real_stack(analysis,mysql_factory,tmp_path) as ((php,private,web),helper):
        login(php,helper,1)
        docs=[]
        for code in ('E2E7E_A','E2E7E_B'):
            form=php.get('/index.php?pagina=documento_nuevo')
            response=php.post('/index.php?pagina=documento_nuevo',data=dict(csrf_token=helper.csrf(form),
                codigo=code,titulo='Factura Enero temporal',tipo='TEST',estado='DRAFT',area_id=1,responsable_id=4))
            assert response.status_code==303,response.text
            doc=int(parse_qs(urlsplit(response.headers['location']).query)['id'][0]);docs.append(doc)
            page=php.get(response.headers['location'])
            uploaded=php.post(f'/index.php?pagina=documento&id={doc}',data={'csrf_token':helper.csrf(page)},
                files={'archivo':('Factura Enero.txt',b'7E identical bytes ONLY TEMP','text/plain')})
            assert uploaded.status_code==303,uploaded.text
        page=php.get('/index.php?pagina=analisis&documento_id='+str(docs[0]))
        assert page.status_code==200 and 'Coincidencia binaria entre documentos' in page.text
        assert f'pagina=documento&amp;id={docs[1]}' in page.text
        assert 'Archivo no disponible al consultar' not in page.text and 'JWT' not in page.text and 'eyJ' not in page.text
        resource=php.get(f'/index.php?pagina=documento&id={docs[1]}')
        assert resource.status_code==200 and 'Factura Enero.txt' in resource.text
        with mysql_factory() as db:
            a=db.scalar(select(VersionDocumento).where(VersionDocumento.documento_id==docs[0]))
            b=db.scalar(select(VersionDocumento).where(VersionDocumento.documento_id==docs[1]))
            assert a.sha256==b.sha256 and a.storage_key!=b.storage_key
            assert a.sha256 not in page.text
        assert token(private,php) not in page.text


def test_real_user_cannot_infer_secret_duplicate_api_php_and_revocation(analysis,mysql_factory,tmp_path):
    _,fixture,_,storage=analysis
    # User 3 can read only document 3; remove irrelevant duplicates from visible doc.
    with real_stack(analysis,mysql_factory,tmp_path) as ((php,private,web),helper):
        login(php,helper,3)
        credential=token(private,php)
        config=(web/'config/config.php').read_text(encoding='utf-8')
        base=re.search(r'http://127\.0\.0\.1:[0-9]+',config)[0]
        with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+credential}) as api:
            endpoints=['resumen','anomalias','documentos/3','versiones/4']
            baseline={p:stable(api.get('/api/v1/analisis/'+p).json()) for p in endpoints}
            before=php.get('/index.php?pagina=analisis&documento_id=3')
            with mysql_factory() as db:
                db.add(Documento(id=999,codigo='SECRET_E2E',titulo='SECRET_OTHER_USER',tipo='TEST',estado='ACTIVE',
                    area_id=1,responsable_id=7,created_by_id=1));db.flush()
                from io import BytesIO
                info=storage.save_file(BytesIO(b'fixture'),'SECRET_OTHER_USER.txt')
                db.add(VersionDocumento(id=999,documento_id=999,numero_version=1,storage_key=info.storage_key,
                    nombre_original=info.nombre_original,mime_type=info.mime_type,tamano_bytes=info.tamano_bytes,
                    sha256=info.sha256,subido_por_id=1));db.commit()
            for endpoint in endpoints:
                statements=[]
                def capture(conn,cursor,sql,*args):statements.append(sql.lstrip().upper())
                event.listen(mysql_factory.kw['bind'],'before_cursor_execute',capture)
                try:response=api.get('/api/v1/analisis/'+endpoint)
                finally:event.remove(mysql_factory.kw['bind'],'before_cursor_execute',capture)
                budget=7 if endpoint=='resumen' else 8 if endpoint=='anomalias' else 11
                assert sum(s.startswith(('SELECT','WITH')) and s.strip()!='SELECT DATABASE()' for s in statements)<=budget
                assert not any(s.startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER','DROP')) for s in statements)
                assert response.status_code==200 and stable(response.json())==baseline[endpoint]
                assert 'SECRET_OTHER_USER' not in response.text and '999' not in str(stable(response.json()))
            after=php.get('/index.php?pagina=analisis&documento_id=3')
            assert after.status_code==before.status_code==200
            assert 'SECRET_OTHER_USER' not in after.text and 'id=999' not in after.text
            assert api.get('/api/v1/analisis/documentos/999').status_code==404
            assert 'SECRET_OTHER_USER' not in php.get('/index.php?pagina=analisis&documento_id=999').text
            with mysql_factory() as db:
                db.get(Usuario,3).activo=False;db.commit()
            assert api.get('/api/v1/analisis/resumen').status_code==401
            assert php.get('/index.php?pagina=analisis').status_code==303


@pytest.mark.skipif(os.environ.get('AUTH_BROWSER_TEST')!='1',reason='Explicit isolated Chrome opt-in required')
def test_chrome_real_php_fastapi_mysql_analysis_links(analysis,mysql_factory,tmp_path):
    with real_stack(analysis,mysql_factory,tmp_path) as ((php,_,_),helper):
        browser=harness('chrome_analysis_real',ROOT/'frontend/tests/test_auth_browser.py')
        import time
        with browser.chromium(tmp_path) as cdp:
            base=str(php.base_url).rstrip('/')
            def go(url,condition):
                cdp('Page.navigate',url=url)
                deadline=time.monotonic()+15
                while not browser.evaluate(cdp,"document.readyState==='complete' && ("+condition+")"):
                    assert time.monotonic()<deadline,condition
                    time.sleep(.05)
            cdp('Emulation.setDeviceMetricsOverride',width=320,height=800,deviceScaleFactor=1,mobile=False)
            go(base+'/index.php?pagina=login',"!!document.getElementById('password')")
            browser.evaluate(cdp,"document.getElementById('correo').value='1@example.invalid';document.getElementById('password').value='"+PASSWORD+"';document.querySelector('.auth-form').requestSubmit()")
            deadline=time.monotonic()+15
            while not browser.evaluate(cdp,"document.readyState==='complete' && !!document.querySelector('[data-kpi=documentos]')"):
                assert time.monotonic()<deadline;time.sleep(.05)
            go(base+'/index.php?pagina=analisis',"!!document.querySelector('.analysis-items')")
            assert not browser.evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
            assert not browser.evaluate(cdp,"document.documentElement.outerHTML.includes('eyJ')")
            browser.evaluate(cdp,"document.querySelector('.analysis-actions a[href^=\"index.php?pagina=documento&\"]').click()")
            deadline=time.monotonic()+15
            while not browser.evaluate(cdp,"location.search.includes('pagina=documento&') && document.readyState==='complete'"):
                assert time.monotonic()<deadline;time.sleep(.05)
            assert browser.evaluate(cdp,"document.body.textContent.includes('Historial de versiones')")
