"""Complete 6C browser-facing PHP -> real FastAPI -> isolated MySQL -> fake mail flow."""
import re

import httpx
from sqlalchemy import select

from app.models.entities import Usuario
from app.models.auth import AuthSession
from app.models.account_access import AccessRequest
from test_php_auth_mysql import php_mysql, php_login, support
from test_account_access_mysql import clean, drain, count


def test_full_access_resend_initial_login_reset_and_revocation(php_mysql, mysql_factory):
    c, private, admin_password, users, _, _, _, port = php_mysql
    email, password, new_password = 'applicant6c@example.invalid', 'initial-password-6c', 'reset-password-6c'
    form = c.get('/index.php?pagina=solicitar_acceso')
    response = c.post('/index.php?pagina=solicitar_acceso', data=dict(csrf_token=support.csrf(form),
        nombre='PHP applicant', correo=email, motivo='Audit documents', rol='ADMIN'))
    assert response.status_code == 202
    with mysql_factory() as db:
        req_id = db.scalar(select(AccessRequest.id))
        assert db.scalar(select(Usuario.id).where(Usuario.correo_normalizado == email)) is None
        db.get(Usuario, users[0]).rol = 'ADMIN'
        db.commit()
    assert php_login(c, admin_password).status_code == 303
    path = f'/index.php?pagina=solicitud_acceso&id={req_id}'
    form = c.get(path)
    assert form.status_code == 200
    approved = c.post(path, data=dict(csrf_token=support.csrf(form), accion='approve', rol='AUDITOR_INTERNO', admin_id=users[1]))
    assert approved.status_code == 303
    form = c.get(path)
    resent = c.post(path, data=dict(csrf_token=support.csrf(form), accion='resend'))
    assert resent.status_code == 303  # Empty JSON object must reach FastAPI, not [].
    messages = drain(mysql_factory)
    assert len(messages) == 1 and messages[0][:2] == (email,'INITIAL_PASSWORD')
    token = messages[0][2]
    with mysql_factory() as db:
        assert db.get(AccessRequest, req_id).resolved_by == users[0]
        assert db.scalar(select(Usuario.id).where(Usuario.correo_normalizado == email)) is None
    form = c.get('/index.php?pagina=establecer_password')
    saved = c.post('/index.php?pagina=establecer_password', data=dict(csrf_token=support.csrf(form), token=token,
        password=password, confirmation=password))
    assert saved.status_code == 303 and 'pagina=login' in saved.headers['location']
    assert c.get('/index.php?pagina=dashboard').status_code == 303
    with mysql_factory() as db:
        uid = db.scalar(select(Usuario.id).where(Usuario.correo_normalizado == email))
        assert db.get(Usuario, uid).rol == 'AUDITOR_INTERNO'
    assert count(mysql_factory, AuthSession, AuthSession.usuario_id == uid) == 0
    form = c.get('/index.php?pagina=login')
    assert c.post('/index.php?pagina=login', data=dict(csrf_token=support.csrf(form), correo=email, password=password)).status_code == 303
    stored = (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+c.cookies.get('PHPSESSID'))).read_text()
    jwt = re.search(r's:12:"access_token";s:\d+:"([^"]+)"', stored)[1]
    form = c.get('/index.php?pagina=recuperar_password')
    assert c.post('/index.php?pagina=recuperar_password', data=dict(csrf_token=support.csrf(form), correo=email)).status_code == 202
    reset = next(m[2] for m in drain(mysql_factory) if m[1] == 'PASSWORD_RESET')
    form = c.get('/index.php?pagina=restablecer_password')
    assert c.post('/index.php?pagina=restablecer_password', data=dict(csrf_token=support.csrf(form), token=reset,
        password=new_password, confirmation=new_password)).status_code == 303
    assert c.get('/index.php?pagina=dashboard').status_code == 303
    with httpx.Client(base_url=f'http://127.0.0.1:{port}') as api:
        assert api.get('/api/v1/auth/me', headers={'Authorization':'Bearer '+jwt}).status_code == 401
    log = (private.parent/'php.log').read_text(encoding='utf-8')
    assert all(secret not in log for secret in [token, reset, jwt, password, new_password])
