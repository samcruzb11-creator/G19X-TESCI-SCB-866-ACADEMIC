"""6C contracts, inexpensive admission, fixed URL and SMTP doubles. No database."""
from datetime import datetime
from pathlib import Path
import importlib.util
import secrets
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from app.core.config import settings, Settings
from app.db.session import get_db
from app.main import app
from app.models.entities import Usuario
from app.schemas.account_access import AccessRequestCreate, EmailRequest, PasswordConfirm, ApproveRequest
from app.services import auth_action_protection as protection, auth_mail
from app.services.account_actions import fingerprint


@pytest.fixture
def mail_config(monkeypatch):
    for key, value in dict(smtp_host='smtp.example.invalid', smtp_from_address='noreply@example.invalid',
        smtp_security='starttls', public_frontend_url='https://frontend.example.invalid/trazabilidad',
        app_env='production', smtp_username='test-user').items():
        monkeypatch.setattr(settings, key, value)


@pytest.mark.parametrize('email', ['x', 'a@b', 'a@@b.com', 'a\r\nb@x.com', 'a@x.com\x00',
    'name <a@x.com>', 'a@x.com,b@x.com', 'a@bad_domain.com', 'a@-bad.com', 'a@b..com',
    '.a@x.com', 'a..b@x.com', 'a.@x.com', 'a'*65+'@x.com'])
def test_invalid_email(email):
    with pytest.raises(ValidationError):
        EmailRequest(correo=email)


def test_normalization_and_secret_repr():
    assert EmailRequest(correo='  JOSÉ@Example.Invalid ').correo == 'josé@example.invalid'
    token, password = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    payload = PasswordConfirm(token=token, password=password)
    assert token not in repr(payload) and password not in repr(payload)


@pytest.mark.parametrize('values', [dict(nombre=' a '), dict(motivo=' x '), dict(nombre='a\x00b'),
    dict(rol='ADMIN'), dict(activo=True), dict(password='injected-password'), dict(resolved_by=1)])
def test_access_contract_forbids_privilege_fields_and_trim_bypass(values):
    payload = dict(correo='a@example.invalid', nombre='Applicant', motivo='Access needed') | values
    with pytest.raises(ValidationError):
        AccessRequestCreate(**payload)


@pytest.mark.parametrize('length,valid', [(11, False), (12, True), (1024, True), (1025, False)])
def test_password_character_bounds(length, valid):
    if valid:
        assert len(PasswordConfirm(token='x', password='ñ'*length).password.get_secret_value()) == length
    else:
        with pytest.raises(ValidationError):
            PasswordConfirm(token='x', password='ñ'*length)


@pytest.mark.parametrize('data', [{}, {'rol': None}, {'rol': 'admin'}, {'rol': 'OWNER'}, {'rol': 'ADMIN', 'admin_id': 9}])
def test_explicit_role_only(data):
    with pytest.raises(ValidationError):
        ApproveRequest(**data)


@pytest.mark.parametrize('field,value', [('password_hash','changed'), ('correo','new@example.invalid'),
    ('correo_normalizado','new@example.invalid'), ('activo',False), ('updated_at',datetime(2026, 1, 2))])
def test_credential_fingerprint_changes(field, value):
    user = Usuario(id=9, nombre='Test', correo='old@example.invalid', correo_normalizado='old@example.invalid',
        password_hash='test-hash', activo=True, updated_at=datetime(2026, 1, 1))
    old = fingerprint(user)
    setattr(user, field, value)
    assert len(old) == 32 and fingerprint(user) != old


def test_hash_budget_limit_concurrency_release_and_restart():
    time = [100.0]
    budget = protection.ActionBudget(clock=lambda: time[0])
    budget.take('HASH', 5, hashing=True)
    with pytest.raises(HTTPException) as denied:
        budget.take('HASH', 5, hashing=True)
    assert denied.value.status_code == 429
    budget.release_hash()
    for _ in range(4):
        budget.take('HASH', 5, hashing=True)
        budget.release_hash()
    with pytest.raises(HTTPException):
        budget.take('HASH', 5, hashing=True)
    protection.ActionBudget().take('HASH', 5, hashing=True)  # documented process-local reset
    time[0] += 60
    budget.take('HASH', 5, hashing=True)
    budget.release_hash()
    budget.lock.acquire()
    try:
        with pytest.raises(HTTPException):
            budget.take('RESET_REQUEST', 20)
    finally:
        budget.lock.release()


@pytest.mark.parametrize('key,maximum', [('reset_request_per_hour',3),('reset_request_global_per_minute',20),
    ('access_request_per_day',2),('access_request_global_per_minute',10),('action_confirm_per_minute',5),
    ('action_confirm_global_per_minute',30),('action_hash_per_minute',5),('password_reset_ttl_seconds',1800)])
def test_settings_cannot_weaken_6c_limits(key, maximum):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{key:maximum+1})


@pytest.mark.parametrize('path,maximum', [('/auth/access-requests',10), ('/auth/password-reset/request',20),
    ('/auth/password-reset/confirm',30), ('/auth/initial-password/confirm',30), ('/access-requests/1/resend',20),
    ('/access-requests/0001/approve',20), ('/access-requests/+1/resend',20)])
def test_admission_before_body_no_proxy_bypass(monkeypatch, path, maximum):
    monkeypatch.setattr(Engine, 'connect', Mock(side_effect=AssertionError('Database forbidden')))
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as client:
            for i in range(maximum):
                response = client.post('/api/v1' + path, content='{', headers={'X-Forwarded-For':f'192.0.2.{i}',
                    'X-Real-IP':f'192.0.2.{i}', 'CF-Connecting-IP':f'192.0.2.{i}'})
                assert response.status_code != 429
            response = client.post('/api/v1' + path + '/', content='{')
            assert response.status_code == 429 and int(response.headers['Retry-After']) > 0
            assert response.headers['cache-control'] == 'no-store'
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('endpoint', ['password-reset/confirm','initial-password/confirm'])
def test_validation_does_not_echo_token_or_password(monkeypatch, endpoint):
    monkeypatch.setattr(Engine, 'connect', Mock(side_effect=AssertionError('Database forbidden')))
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post('/api/v1/auth/' + endpoint, json={'token':'secret-action-token', 'password':'secret'})
        assert response.status_code == 422
        assert 'secret' not in response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['referrer-policy'] == 'no-referrer'
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('url', ['https://evil.invalid/?x=1','https://evil.invalid/#token=x',
    'https://user:pass@host.invalid','http://frontend.invalid','javascript:alert(1)',
    '//frontend.invalid','https://host.invalid\\@evil.invalid','https://host.invalid/\npath',
    'https://host.invalid:abc','https://host.invalid:0','https://host.invalid:99999',
    'https://host%2finvalid', 'https://host.invalid/a b', 'https://@host.invalid',
    'https://:@host.invalid', 'https://host.invalid/?', 'https://host.invalid/#'])
def test_fixed_frontend_url_rejects_unsafe_values(monkeypatch, mail_config, url):
    monkeypatch.setattr(settings, 'public_frontend_url', url)
    with pytest.raises(HTTPException) as exc:
        auth_mail.validate_mail_config()
    assert exc.value.status_code == 503 and url not in str(exc.value)


def test_local_http_only_in_development(monkeypatch, mail_config):
    monkeypatch.setattr(settings, 'public_frontend_url', 'http://127.0.0.1:8080/frontend')
    with pytest.raises(HTTPException):
        auth_mail.validate_mail_config()
    monkeypatch.setattr(settings, 'app_env', 'development')
    auth_mail.validate_mail_config()


@pytest.mark.parametrize('security', ['starttls','ssl'])
@pytest.mark.parametrize('kind', ['INITIAL_PASSWORD','PASSWORD_RESET','PASSWORD_CHANGED'])
def test_smtp_envelope_tls_and_fragment(monkeypatch, mail_config, security, kind, caplog):
    import smtplib
    monkeypatch.setattr(settings, 'smtp_security', security)
    server = Mock()
    server.__enter__ = Mock(return_value=server)
    server.__exit__ = Mock(return_value=False)
    factory = Mock(return_value=server)
    monkeypatch.setattr(smtplib, 'SMTP' if security == 'starttls' else 'SMTP_SSL', factory)
    token = secrets.token_urlsafe(32)
    auth_mail.send_smtp('Canonical@Example.invalid', kind, None if kind == 'PASSWORD_CHANGED' else token)
    message = server.send_message.call_args.args[0]
    assert str(message['To']) == 'Canonical@Example.invalid'
    assert factory.call_args.kwargs['timeout'] <= 10
    if security == 'starttls':
        server.starttls.assert_called_once()
    else:
        assert factory.call_args.kwargs['context'].check_hostname
    server.login.assert_called_once()
    body = message.get_content()
    if kind == 'PASSWORD_CHANGED':
        assert '#token' not in body and token not in body
    else:
        assert 'https://frontend.example.invalid/trazabilidad/index.php?pagina=' in body
        assert '#token=' + token in body and '?token=' not in body
    assert token not in caplog.text and 'Canonical' not in caplog.text


def test_cli_sanitizes_private_exception(monkeypatch, capsys):
    source = Path(__file__).resolve().parents[2] / 'scripts/procesar_correo_auth.py'
    spec = importlib.util.spec_from_file_location('isolated_mail_cli', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'validate_mail_config', Mock(side_effect=RuntimeError('SMTP_PASSWORD=private-token')))
    assert module.main([]) == 2
    assert 'private-token' not in capsys.readouterr().out


def test_public_reset_is_queued_even_without_smtp_configuration(monkeypatch):
    from app.services import account_actions
    queued = Mock()
    monkeypatch.setattr(account_actions, 'request_reset', queued)
    monkeypatch.setattr(settings, 'smtp_host', '')
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post('/api/v1/auth/password-reset/request', json={'correo':'absent@example.invalid'})
        assert response.status_code == 202
        queued.assert_called_once_with(None, 'absent@example.invalid')
    finally:
        app.dependency_overrides.clear()


def test_private_route_does_not_propagate_secrets_to_server_logger(monkeypatch, caplog):
    from app.services import account_actions
    monkeypatch.setattr(account_actions, 'request_reset', Mock(side_effect=RuntimeError('secret password/token/SQL params')))
    app.dependency_overrides[get_db] = lambda: None
    try:
        # raise_server_exceptions=True proves the driver exception cannot reach Uvicorn.
        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.post('/api/v1/auth/password-reset/request', json={'correo':'absent@example.invalid'})
        assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
        assert 'secret' not in response.text + caplog.text
    finally:
        app.dependency_overrides.clear()
