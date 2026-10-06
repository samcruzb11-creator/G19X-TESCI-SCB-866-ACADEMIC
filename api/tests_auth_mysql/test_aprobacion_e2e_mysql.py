"""Real PHP -> authenticated FastAPI -> temporary MySQL; no API double."""
import importlib.util
from pathlib import Path
from threading import Thread
import socket
import time
import pytest
import uvicorn
from sqlalchemy import select,func
from tests_unit.test_aprobacion_unit import approvals
from tests_unit.test_rbac_unit import rbac
from app.main import app
from app.api.dependencies import current_user
from app.db.session import get_db
from app.core.security import hash_password
from app.models.entities import Usuario,RondaAprobacion,DecisionAprobacion,EventoAuditoria

MYSQL_RBAC=True


def test_real_php_api_mysql_create_start_decide_history(approvals,mysql_factory,tmp_path):
    _,fixture,_,_=approvals
    password='Only-temporary-test-password!42'
    for i in (1,5):fixture.get(Usuario,i).password_hash=hash_password(password)
    fixture.commit();fixture.rollback()
    def isolated_db():
        with mysql_factory() as db:yield db
    overrides=app.dependency_overrides.copy()
    app.dependency_overrides[get_db]=isolated_db
    app.dependency_overrides.pop(current_user,None)
    harness_path=Path(__file__).resolve().parents[2]/'frontend/tests/conftest.py'
    spec=importlib.util.spec_from_file_location('php_approval_e2e_harness',harness_path)
    harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=Thread(target=server.run,daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started:
            assert thread.is_alive() and time.monotonic()<deadline
            time.sleep(.05)
        with harness.php_server(tmp_path/'php_real',f'http://127.0.0.1:{port}') as (php,private,web):
            def login(id):
                page=php.get('/index.php?pagina=login')
                response=php.post('/index.php?pagina=login',data={'csrf_token':harness.csrf(page),
                    'correo':f'{id}@example.invalid','password':password})
                assert response.status_code==303,response.text
            login(1)
            form=php.get('/index.php?pagina=aprobacion_nueva&documento_id=1')
            assert form.status_code==200,form.text
            response=php.post('/index.php?pagina=aprobacion_nueva&documento_id=1',data={
                'csrf_token':harness.csrf(form),'version_documento_id':'2','aprobadores_ids[]':'5'})
            assert response.status_code==303,response.text
            location=response.headers['location'];page=php.get(location)
            assert 'Ronda creada correctamente' in page.text
            with mysql_factory() as check:
                row=check.scalar(select(RondaAprobacion).where(RondaAprobacion.version_documento_id==2))
                id=row.id;stamp=row.updated_at.isoformat()
            response=php.post(location,data={'csrf_token':harness.csrf(page),'accion':'iniciar',
                'estado_esperado':'PENDING','updated_at_esperado':stamp})
            assert response.status_code==303,response.text
            login(5)
            page=php.get(location)
            assert page.status_code==200 and 'Registrar mi decisión' in page.text
            with mysql_factory() as check:
                decision=check.scalar(select(DecisionAprobacion).where(DecisionAprobacion.ronda_aprobacion_id==id))
                stamp=decision.updated_at.isoformat()
            response=php.post(location,data={'csrf_token':harness.csrf(page),'accion':'decision','estado':'APPROVED',
                'updated_at_esperado':stamp,'comentario':'<script>window.xss=1</script>','aprobador_id':'1'})
            assert response.status_code==303,response.text
            page=php.get(location)
            assert page.status_code==200 and 'Aprobada' in page.text and 'Registrar mi decisión' not in page.text
            assert '<script>window.xss=1</script>' not in page.text and '&lt;script&gt;' in page.text
            assert 'eyJ' not in page.text
            with mysql_factory() as check:
                assert check.get(RondaAprobacion,id).estado=='APPROVED'
                decision=check.scalar(select(DecisionAprobacion).where(DecisionAprobacion.ronda_aprobacion_id==id))
                assert decision.aprobador_id==5 and decision.estado=='APPROVED'
                events=list(check.scalars(select(EventoAuditoria).where(EventoAuditoria.entidad_id==str(id))))
                assert len(events)==4 and [e.actor_id for e in events]==[1,1,5,5]
            assert 'Cierre de ronda' in page.text and 'Decisión confirmada' in page.text
    finally:
        server.should_exit=True;thread.join(timeout=10)
        app.dependency_overrides.clear();app.dependency_overrides.update(overrides)
        assert not thread.is_alive()
