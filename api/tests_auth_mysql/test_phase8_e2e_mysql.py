"""Whole-system regression through actual PHP, FastAPI, MySQL and storage."""
import os
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.models.entities import (Auditoria, Area, Usuario, DocumentoAuditoria, VersionDocumento,
    Hallazgo, HallazgoEvidencia, RondaAprobacion, DecisionAprobacion, EventoAuditoria)
from tests_unit.test_rbac_unit import rbac
from tests_auth_mysql.test_dashboard_e2e_mysql import real_stack, harness, ROOT, PASSWORD

MYSQL_RBAC = True
XSS = '<img src=x onerror=window.phase8_xss=1>'


def resource_id(response):
    assert response.status_code == 303, response.text
    return int(parse_qs(urlsplit(response.headers['location']).query)['id'][0])


def test_full_php_audit_upload_finding_evidence_approval_analysis_logout(rbac, mysql_factory, tmp_path):
    _, fixture, _, storage = rbac
    fixture.get(Area,1).nombre = XSS
    for uid in range(1,6):
        fixture.get(Usuario,uid).nombre = XSS
    fixture.commit(); fixture.rollback()
    with real_stack(rbac, mysql_factory, tmp_path) as ((php, private, web), helper):
        def login(uid):
            page = php.get('/index.php?pagina=login')
            result = php.post('/index.php?pagina=login',data=dict(csrf_token=helper.csrf(page),
                correo=f'{uid}@example.invalid',password=PASSWORD))
            assert result.status_code == 303, result.text
        login(1)
        page = php.get('/index.php?pagina=auditoria_nueva')
        audit_id = resource_id(php.post('/index.php?pagina=auditoria_nueva',data=dict(csrf_token=helper.csrf(page),
            codigo='PHASE8_E2E',nombre=XSS,alcance='Synthetic full flow',responsable_id='2')))
        location=f'/index.php?pagina=auditoria&id={audit_id}'
        page=php.get(location)
        with mysql_factory() as db:
            stamp=db.get(Auditoria,audit_id).updated_at.isoformat()
        assert php.post(location,data=dict(csrf_token=helper.csrf(page),estado='IN_PROGRESS',
            estado_esperado='PLANNED',updated_at_esperado=stamp)).status_code==303
        page=php.get('/index.php?pagina=documento_nuevo')
        document_id=resource_id(php.post('/index.php?pagina=documento_nuevo',data=dict(csrf_token=helper.csrf(page),
            codigo='PHASE8_E2E',titulo=XSS,tipo='TEST',estado='DRAFT',area_id='1',responsable_id='4')))
        location=f'/index.php?pagina=documento&id={document_id}'
        page=php.get(location)
        uploaded=php.post(location,data=dict(csrf_token=helper.csrf(page)),
            files={'archivo':('phase8.txt',b'Synthetic phase8 full flow','text/plain')})
        assert uploaded.status_code==303,uploaded.text
        with mysql_factory() as db:
            version=db.scalar(select(VersionDocumento).where(VersionDocumento.documento_id==document_id))
            version_id=version.id
            assert storage.get_absolute_path(version.storage_key).read_bytes()==b'Synthetic phase8 full flow'
            # The approved API has no document/audit linking command. Seed just this
            # scope association in the guarded fixture; every tested action uses HTTP.
            assert db.connection().exec_driver_sql('SELECT DATABASE()').scalar_one()!='sistema_trazabilidad'
            db.add(DocumentoAuditoria(auditoria_id=audit_id,documento_id=document_id,
                version_documento_id=version_id,proposito='TEST',asociado_por_id=1));db.commit()
        page=php.get(f'/index.php?pagina=hallazgo_nuevo&auditoria_id={audit_id}')
        finding_id=resource_id(php.post(f'/index.php?pagina=hallazgo_nuevo&auditoria_id={audit_id}',
            data=dict(csrf_token=helper.csrf(page),auditoria_id=str(audit_id),titulo=XSS,
                descripcion=XSS,categoria='Control',severidad='HIGH',responsable_id='2')))
        location=f'/index.php?pagina=evidencia_logica&hallazgo_id={finding_id}'
        page=php.get(location)
        evidence=php.post(location,data=dict(csrf_token=helper.csrf(page),auditoria_id=str(audit_id),
            titulo=XSS,descripcion=XSS,tipo='NOTE'))
        assert evidence.status_code==303,evidence.text
        with mysql_factory() as db:
            assert db.scalar(select(HallazgoEvidencia).where(HallazgoEvidencia.hallazgo_id==finding_id)) is not None
        location=f'/index.php?pagina=aprobacion_nueva&documento_id={document_id}'
        page=php.get(location)
        round_id=resource_id(php.post(location,data={'csrf_token':helper.csrf(page),
            'version_documento_id':str(version_id),'aprobadores_ids[]':'5'}))
        location=f'/index.php?pagina=aprobacion&id={round_id}'
        page=php.get(location)
        with mysql_factory() as db:
            stamp=db.get(RondaAprobacion,round_id).updated_at.isoformat()
        assert php.post(location,data=dict(csrf_token=helper.csrf(page),accion='iniciar',
            estado_esperado='PENDING',updated_at_esperado=stamp)).status_code==303
        login(5)
        page=php.get(location)
        with mysql_factory() as db:
            stamp=db.scalar(select(DecisionAprobacion).where(DecisionAprobacion.ronda_aprobacion_id==round_id)).updated_at.isoformat()
        result=php.post(location,data=dict(csrf_token=helper.csrf(page),accion='decision',estado='APPROVED',
            updated_at_esperado=stamp,comentario=XSS))
        assert result.status_code==303,result.text
        login(1)
        for page_name in ('dashboard','alertas',f'analisis&documento_id={document_id}',f'documento&id={document_id}',
                          f'hallazgo&id={finding_id}',f'aprobacion&id={round_id}'):
            response=php.get('/index.php?pagina='+page_name)
            assert response.status_code==200,response.text
            assert XSS not in response.text and 'eyJ' not in response.text and PASSWORD not in response.text
            assert 'no-store' in response.headers['cache-control'].split(', ')
        with mysql_factory() as db:
            assert db.get(RondaAprobacion,round_id).estado=='APPROVED'
            events=list(db.scalars(select(EventoAuditoria).where(EventoAuditoria.accion=='CREACION_VERSION',
                EventoAuditoria.entidad_id==str(document_id))))
            assert len(events)==1 and events[0].actor_id==1
        if os.environ.get('AUTH_BROWSER_TEST')=='1':
            browser=harness('phase8_chrome',ROOT/'frontend/tests/test_auth_browser.py')
            base=str(php.base_url).rstrip('/')
            with browser.chromium(tmp_path) as cdp:
                def wait(expression):
                    deadline=time.monotonic()+15
                    while not browser.evaluate(cdp,"document.readyState==='complete' && ("+expression+")"):
                        assert time.monotonic()<deadline;time.sleep(.05)
                for uid in range(1,6):
                    for width in (1440,390,320):
                        cdp('Emulation.setDeviceMetricsOverride',width=width,height=900,deviceScaleFactor=1,mobile=False)
                        cdp('Page.navigate',url=base+'/index.php?pagina=login');wait("!!document.getElementById('password')")
                        browser.evaluate(cdp,f"document.getElementById('correo').value='{uid}@example.invalid';document.getElementById('password').value='{PASSWORD}';document.querySelector('.auth-form').requestSubmit()")
                        wait("!!document.querySelector('[data-kpi=documentos]')")
                        for page_name in ('dashboard','analisis',f'documento&id={document_id}',f'aprobacion&id={round_id}'):
                            cdp('Page.navigate',url=base+'/index.php?pagina='+page_name);wait("!!document.querySelector('h1')")
                            assert browser.evaluate(cdp,'typeof window.phase8_xss')=='undefined'
                            assert not browser.evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
                            assert not browser.evaluate(cdp,"document.documentElement.outerHTML.includes('eyJ')")
        page=php.get('/index.php?pagina=dashboard')
        result=php.post('/index.php?pagina=logout',data=dict(csrf_token=helper.csrf(page)))
        assert result.status_code==303
        assert php.get('/index.php?pagina=dashboard').status_code==303
