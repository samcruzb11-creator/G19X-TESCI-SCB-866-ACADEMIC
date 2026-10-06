"""6B.4B admission/TOCTOU tests on the fixture-owned random MySQL schema.

Siteverify is always replaced by an offline double. No application database,
network request or SMTP delivery is permitted by this suite.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock
from unittest.mock import Mock
import json

import pytest
import httpx
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event, func, select, text

from app.core.config import settings
from app.core.security import hash_password, normalize_email
from app.db.session import get_db
from app.main import app
from app.models.account_access import AccessRequest, AuthActionLimit, AuthActionToken, AuthMailJob
from app.models.auth import AuthLoginLimit, AuthSession
from app.models.entities import Usuario
from app.routers import auth
from app.schemas.auth import LoginRequest
from app.schemas.account_access import AccessRequestCreate
from app.services import account_actions as actions, auth_action_protection as ap
from app.services import auth_mail as mail, login_protection as lp, turnstile
from test_php_auth_mysql import php_mysql, support

EMAIL = 'owner@example.invalid'
PASSWORD = 'test-only-password-6b4b'
CHALLENGE_MESSAGE = 'Se requiere verificación adicional.'
REAL_VERIFY = turnstile.verify
FLOWS = [
    ('access-requests', 'ACCESS_REQUEST', 'access_request', 2),
    ('password-reset/request', 'RESET_REQUEST', 'password_reset_request', 3),
]


@pytest.fixture(autouse=True)
def adaptive_config(clean_temporary_schema, auth_config, monkeypatch):
    for key, value in dict(
        turnstile_mode='test',
        turnstile_secret_key=SecretStr('1x0000000000000000000000000000000AA'),
        turnstile_expected_hostnames='localhost',
        app_env='development',
        smtp_host='smtp.example.invalid',
        smtp_from_address='noreply@example.invalid',
        public_frontend_url='https://frontend.example.invalid',
        smtp_security='starttls',
    ).items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(turnstile, 'verify_budget', turnstile.VerifyBudget())
    monkeypatch.setattr(turnstile, '_post', Mock(side_effect=AssertionError('Network forbidden')))


@pytest.fixture
def siteverify(monkeypatch):
    """Only this Cloudflare double remembers tokens, never production code."""
    used, lock, calls = set(), Lock(), []

    def verify(token, action):
        with lock:
            calls.append((token, action))
            if not isinstance(token, str) or not token.startswith('valid-') or token in used:
                raise turnstile.challenge(action)
            used.add(token)

    monkeypatch.setattr(turnstile, 'verify', verify)
    return calls


@pytest.fixture
def http(mysql_factory, siteverify):
    def db():
        with mysql_factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def add_user(factory, email=EMAIL, *, active=True, role='ADMIN'):
    with factory() as db:
        user = Usuario(nombre='Turnstile isolated account', correo=email,
            correo_normalizado=normalize_email(email), activo=active, rol=role,
            password_hash=hash_password(PASSWORD))
        db.add(user)
        db.commit()
        return user.id


def count(factory, model, *where):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def login_state(factory, email=EMAIL):
    with factory() as db:
        row = db.get(AuthLoginLimit, normalize_email(email))
        if row is None:
            return None
        return tuple(getattr(row, name) for name in (
            'request_count', 'failure_count', 'request_window', 'failure_window', 'expires_at'))


def action_state(factory, action, email=EMAIL):
    with factory() as db:
        row = db.scalar(select(AuthActionLimit).where(AuthActionLimit.action == action,
            AuthActionLimit.identifier == normalize_email(email)))
        if row is None:
            return None
        return row.count, row.window_start, row.expires_at


def attempt(http, email=EMAIL, password='incorrect', token=None, headers=None):
    payload = {'correo': email, 'password': password}
    if token is not None:
        payload['turnstile_token'] = token
    return http.post('/api/v1/auth/login', json=payload, headers=headers)


def direct_login(factory, *, email=EMAIL, password='incorrect', token=None):
    with factory() as db:
        try:
            auth.login(LoginRequest(correo=email, password=password, turnstile_token=token), Response(), db)
            return 200
        except HTTPException as exc:
            assert not db.in_transaction()
            return exc.status_code


def public_request(http, route, *, email=EMAIL, token=None, extra=None):
    payload = {'correo': email}
    if route == 'access-requests':
        payload.update(nombre='Original applicant', motivo='Audit document access')
    if token is not None:
        payload['turnstile_token'] = token
    payload.update(extra or {})
    return http.post('/api/v1/auth/' + route, json=payload)


def direct_public(factory, route, *, email=EMAIL, token=None):
    with factory() as db:
        try:
            if route == 'access-requests':
                actions.submit_access(db, AccessRequestCreate(correo=email, nombre='Original applicant',
                    motivo='Audit document access', turnstile_token=token))
            else:
                actions.request_reset(db, email, turnstile_token=SecretStr(token) if token is not None else None)
            return 202
        except HTTPException as exc:
            assert not db.in_transaction()
            return exc.status_code


def assert_challenge(response, action):
    assert response.status_code == 428
    assert response.json() == {'detail': CHALLENGE_MESSAGE, 'challenge_required': True,
        'challenge_action': action}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert 'retry-after' not in response.headers


def seed_login_failures(factory, number=3, email=EMAIL):
    for _ in range(number):
        assert direct_login(factory, email=email) == 401


@pytest.mark.parametrize('case', ['missing', 'inactive', 'admin', 'active'])
def test_login_soft_policy_is_independent_of_account(http, mysql_factory, monkeypatch, siteverify, case):
    if case != 'missing':
        add_user(mysql_factory, active=case != 'inactive', role='ADMIN' if case == 'admin' else 'AUDITOR_INTERNO')
    hashed = Mock(wraps=auth.verify_password)
    monkeypatch.setattr(auth, 'verify_password', hashed)
    for failures in range(3):
        response = attempt(http)
        assert response.status_code == 401
        assert login_state(mysql_factory)[:2] == (failures + 1, failures + 1)
        assert siteverify == []
    before = login_state(mysql_factory)
    assert_challenge(attempt(http), 'login')
    assert_challenge(attempt(http, token='invalid-token'), 'login')
    assert login_state(mysql_factory) == before
    assert hashed.call_count == 3
    assert lp.global_budget.active == 0
    assert count(mysql_factory, AuthSession) == 0


@pytest.mark.parametrize('success', [False, True])
def test_verified_login_preserves_previous_failures(http, mysql_factory, siteverify, success):
    add_user(mysql_factory)
    seed_login_failures(mysql_factory)
    response = attempt(http, password=PASSWORD if success else 'incorrect', token='valid-login-1')
    assert response.status_code == (200 if success else 401)
    assert login_state(mysql_factory)[:2] == (4, 3 if success else 4)
    assert siteverify == [('valid-login-1', 'login')]
    assert count(mysql_factory, AuthSession) == int(success)
    # A successful attempt releases only its own reservation; historical failures stay.
    assert_challenge(attempt(http), 'login')


def test_valid_challenge_never_overrides_hard_lock_or_refreshes_window(http, mysql_factory, siteverify):
    seed_login_failures(mysql_factory)
    for i in range(2):
        assert attempt(http, token=f'valid-login-{i}').status_code == 401
    before = login_state(mysql_factory)
    assert before[:2] == (5, 5)
    calls = len(siteverify)
    for token in [None, 'invalid-hard', 'valid-cannot-bypass']:
        response = attempt(http, token=token)
        assert response.status_code == 429
        assert 590 <= int(response.headers['Retry-After']) <= 600
        assert login_state(mysql_factory) == before
        assert len(siteverify) == calls


def test_collation_casing_space_and_unicode_share_adaptive_state(http, mysql_factory):
    variants = [' Caf\u00e9@Example.invalid ', 'CAFE@EXAMPLE.INVALID', 'cafe\u0301@example.invalid']
    for email in variants:
        assert attempt(http, email=email).status_code == 401
    assert_challenge(attempt(http, email='caf\u00e9@example.invalid'), 'login')
    assert_challenge(attempt(http, email='CAFE@example.invalid'), 'login')
    assert count(mysql_factory, AuthLoginLimit) == 1
    assert login_state(mysql_factory, 'cafe@example.invalid')[:2] == (3, 3)


def test_adaptive_rejection_never_queries_users(http, mysql_factory):
    seed_login_failures(mysql_factory)
    statements = []
    engine = mysql_factory.kw['bind']

    def observe(conn, cursor, statement, params, context, executemany):
        statements.append(statement.lower())

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        assert_challenge(attempt(http), 'login')
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert not any('usuarios' in sql for sql in statements)


def test_unsolicited_turnstile_token_does_not_trigger_external_validation(http, mysql_factory, siteverify):
    assert attempt(http, token='valid-unused').status_code == 401
    assert public_request(http, 'access-requests', token='valid-unused').status_code == 202
    assert public_request(http, 'password-reset/request', token='valid-unused').status_code == 202
    assert siteverify == []


def test_login_global_pressure_and_spoofed_proxy_do_not_override_hard_limit(http, mysql_factory, monkeypatch, siteverify):
    monkeypatch.setattr(settings, 'rate_limit_login_requests_per_minute', 8)
    for i in range(3):
        assert attempt(http, email=f'{i}@example.invalid').status_code == 401
    assert_challenge(attempt(http, email='fresh@example.invalid'), 'login')
    assert login_state(mysql_factory, 'fresh@example.invalid') is None
    for i in range(4):
        assert attempt(http, email=f'approved{i}@example.invalid', token=f'valid-global-{i}').status_code == 401
    before = list(lp.global_budget.requests)
    response = attempt(http, email='another@example.invalid', token='valid-global-overflow', headers={
        'X-Forwarded-For': '192.0.2.1', 'X-Real-IP': '192.0.2.2',
        'CF-Connecting-IP': '192.0.2.3', 'Forwarded': 'for=192.0.2.4'})
    assert response.status_code == 429
    assert list(lp.global_budget.requests) == before
    assert not any(token == 'valid-global-overflow' for token, _ in siteverify)
    assert login_state(mysql_factory, 'another@example.invalid') is None


@pytest.mark.parametrize('route,action,challenge_action,limit', FLOWS)
def test_public_action_repetition_requires_challenge_preserves_hard_limit(
        http, mysql_factory, siteverify, route, action, challenge_action, limit):
    assert public_request(http, route).status_code == 202
    assert siteverify == []
    before = action_state(mysql_factory, action)
    assert_challenge(public_request(http, route), challenge_action)
    assert_challenge(public_request(http, route, token='invalid-action'), challenge_action)
    assert action_state(mysql_factory, action) == before
    for i in range(1, limit):
        assert public_request(http, route, token=f'valid-action-{i}').status_code == 202
    before = action_state(mysql_factory, action)
    calls = len(siteverify)
    response = public_request(http, route, token='valid-action-overflow')
    assert response.status_code == 429 and int(response.headers['retry-after']) > 0
    assert action_state(mysql_factory, action) == before
    assert len(siteverify) == calls
    assert count(mysql_factory, Usuario) == count(mysql_factory, AuthSession) == 0


@pytest.mark.parametrize('route,action,challenge_action,limit', FLOWS)
@pytest.mark.parametrize('case', ['missing', 'inactive', 'admin', 'active'])
def test_public_action_account_independent_and_collation_equivalent(
        http, mysql_factory, route, action, challenge_action, limit, case):
    if case != 'missing':
        add_user(mysql_factory, email='Cafe@Example.invalid', active=case != 'inactive',
            role='ADMIN' if case == 'admin' else 'AUDITOR_INTERNO')
    assert public_request(http, route, email='Caf\u00e9@example.invalid').status_code == 202
    assert_challenge(public_request(http, route, email=' CAFE@EXAMPLE.INVALID '), challenge_action)
    assert_challenge(public_request(http, route, email='cafe\u0301@example.invalid'), challenge_action)
    assert count(mysql_factory, AuthActionLimit, AuthActionLimit.action == action) == 1
    assert action_state(mysql_factory, action, 'cafe@example.invalid')[0] == 1


@pytest.mark.parametrize('route,action,challenge_action,limit', FLOWS)
def test_public_action_global_pressure_is_separate_and_hard_authoritative(
        http, mysql_factory, siteverify, route, action, challenge_action, limit):
    maximum = settings.access_request_global_per_minute if action == 'ACCESS_REQUEST' else settings.reset_request_global_per_minute
    for i in range(maximum // 2 - 1):
        assert public_request(http, route, email=f'first{i}@example.invalid').status_code == 202
    assert_challenge(public_request(http, route, email='fresh@example.invalid'), challenge_action)
    assert action_state(mysql_factory, action, 'fresh@example.invalid') is None
    for i in range(maximum // 2):
        assert public_request(http, route, email=f'approved{i}@example.invalid', token=f'valid-pressure-{i}').status_code == 202
    before, calls = list(ap.budget.windows[action]), len(siteverify)
    assert public_request(http, route, email='over@example.invalid', token='valid-over').status_code == 429
    assert list(ap.budget.windows[action]) == before and len(siteverify) == calls
    # Pressure on one route does not impose a challenge on the other route.
    other = 'password-reset/request' if route == 'access-requests' else 'access-requests'
    assert public_request(http, other, email='separate@example.invalid').status_code == 202


@pytest.mark.parametrize('token', [None, 'invalid-action'])
def test_rejected_access_cannot_mutate_existing_request(http, mysql_factory, token):
    assert public_request(http, 'access-requests').status_code == 202
    before = action_state(mysql_factory, 'ACCESS_REQUEST')
    response = public_request(http, 'access-requests', token=token,
        extra={'nombre': 'Attacker changed name', 'motivo': 'Attacker changed details'})
    assert_challenge(response, 'access_request')
    assert action_state(mysql_factory, 'ACCESS_REQUEST') == before
    with mysql_factory() as db:
        row = db.scalar(select(AccessRequest))
        assert (row.nombre, row.motivo, row.status, row.approved_role, row.resolved_by, row.usuario_id) == (
            'Original applicant', 'Audit document access', 'PENDING', None, None, None)
    assert count(mysql_factory, Usuario) == count(mysql_factory, AuthMailJob) == 0


@pytest.mark.parametrize('extra', [{'rol': 'ADMIN'}, {'usuario_id': 1}, {'recipient': 'relay@example.invalid'}, {'resolved_by': 1}])
def test_solved_challenge_cannot_inject_privileged_access_fields(http, mysql_factory, siteverify, extra):
    assert public_request(http, 'access-requests').status_code == 202
    before = action_state(mysql_factory, 'ACCESS_REQUEST')
    response = public_request(http, 'access-requests', token='valid-injection', extra=extra)
    assert response.status_code == 422
    assert action_state(mysql_factory, 'ACCESS_REQUEST') == before
    assert count(mysql_factory, Usuario) == 0 and siteverify == []


@pytest.mark.parametrize('case', ['missing', 'inactive', 'active'])
def test_challenged_reset_retains_blind_lookup_and_anti_email_relay(http, mysql_factory, case):
    email = 'correo-no-registrado@example.com'
    if case != 'missing':
        add_user(mysql_factory, email='Canonical@Example.invalid', active=case == 'active')
        email = 'canonical@example.invalid'
    first = public_request(http, 'password-reset/request', email=email)
    assert first.status_code == 202 and first.json() == {'message': actions.RESET_MESSAGE}
    statements = []
    engine = mysql_factory.kw['bind']

    def observe(conn, cursor, statement, params, context, executemany):
        statements.append(statement.lower())

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        assert_challenge(public_request(http, 'password-reset/request', email=email), 'password_reset_request')
        second = public_request(http, 'password-reset/request', email=email, token='valid-reset-lookup')
        assert second.status_code == 202 and second.json() == first.json()
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert not any('usuarios' in sql for sql in statements)
    assert count(mysql_factory, AuthActionToken) == 0
    assert count(mysql_factory, AuthMailJob, AuthMailJob.recipient.is_not(None)) == 0
    sent = []
    for _ in range(8):
        if not mail.process_one(mysql_factory, sender=lambda *args: sent.append(args)):
            break
    else:
        pytest.fail('Unbounded mail work')
    if case != 'active':
        assert sent == []
        assert count(mysql_factory, AuthActionToken) == 0
        assert count(mysql_factory, AuthMailJob, AuthMailJob.recipient.is_not(None)) == 0
        assert count(mysql_factory, AuthMailJob, AuthMailJob.kind != 'LOOKUP_RESET') == 0
    else:
        assert sent and all(message[:2] == ('Canonical@Example.invalid', 'PASSWORD_RESET') for message in sent)


@pytest.mark.parametrize('route,action,challenge_action,limit', FLOWS)
def test_rejected_public_action_never_extends_window(http, mysql_factory, route, action, challenge_action, limit):
    assert public_request(http, route).status_code == 202
    before = action_state(mysql_factory, action)
    for _ in range(2):
        assert_challenge(public_request(http, route), challenge_action)
    assert action_state(mysql_factory, action) == before
    with mysql_factory() as db:
        row = db.scalar(select(AuthActionLimit).where(AuthActionLimit.action == action))
        row.window_start -= timedelta(days=2)
        db.commit()
    assert public_request(http, route).status_code == 202
    assert action_state(mysql_factory, action)[0] == 1


def test_login_failure_window_expiry_removes_individual_challenge(http, mysql_factory, siteverify):
    seed_login_failures(mysql_factory)
    assert_challenge(attempt(http), 'login')
    with mysql_factory() as db:
        row = db.get(AuthLoginLimit, EMAIL)
        row.failure_window -= timedelta(seconds=601)
        row.request_window -= timedelta(seconds=61)
        db.commit()
    calls = len(siteverify)
    assert attempt(http).status_code == 401
    assert login_state(mysql_factory)[:2] == (1, 1)
    assert len(siteverify) == calls


def test_single_use_contract_rejects_replay_without_new_password_failure(http, mysql_factory, siteverify):
    seed_login_failures(mysql_factory)
    assert attempt(http, token='valid-single-use').status_code == 401
    before = login_state(mysql_factory)
    assert_challenge(attempt(http, token='valid-single-use'), 'login')
    assert login_state(mysql_factory) == before
    assert before[:2] == (4, 4)


@pytest.mark.parametrize('route,action,challenge_action,limit', FLOWS)
def test_siteverify_outside_transaction_and_row_lock(mysql_factory, monkeypatch, siteverify,
        route, action, challenge_action, limit):
    assert direct_public(mysql_factory, route) == 202
    with mysql_factory() as db:
        def verify(token, actual_action):
            assert actual_action == challenge_action and not db.in_transaction()
            # A different connection can acquire the exact bucket during HTTP.
            with mysql_factory() as other:
                other.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                assert other.scalar(select(AuthActionLimit).where(AuthActionLimit.action == action)
                    .with_for_update()) is not None
                other.rollback()

        monkeypatch.setattr(turnstile, 'verify', verify)
        if route == 'access-requests':
            actions.submit_access(db, AccessRequestCreate(correo=EMAIL, nombre='Applicant',
                motivo='Audit access', turnstile_token='valid-no-lock'))
        else:
            actions.request_reset(db, EMAIL, turnstile_token=SecretStr('valid-no-lock'))
        assert not db.in_transaction()


def test_login_siteverify_outside_transaction_lock_and_argon_slot(mysql_factory, monkeypatch, siteverify):
    seed_login_failures(mysql_factory)
    with mysql_factory() as db:
        def verify(token, action):
            assert action == 'login' and not db.in_transaction()
            assert lp.global_budget.active == 0
            with mysql_factory() as other:
                other.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                assert other.scalar(select(AuthLoginLimit).with_for_update()) is not None
                other.rollback()

        monkeypatch.setattr(turnstile, 'verify', verify)
        with pytest.raises(HTTPException) as denied:
            auth.login(LoginRequest(correo=EMAIL, password='incorrect', turnstile_token='valid-no-lock'), Response(), db)
        assert denied.value.status_code == 401 and not db.in_transaction()
    assert login_state(mysql_factory)[:2] == (4, 4)


@pytest.mark.parametrize('equivalent_email', [EMAIL, ' OWN\u00c9R@EXAMPLE.INVALID '])
def test_inflight_success_is_not_a_real_failure_for_soft_threshold(mysql_factory, monkeypatch, siteverify, equivalent_email):
    add_user(mysql_factory)
    seed_login_failures(mysql_factory, number=2)
    started, release = Event(), Event()
    original = auth.verify_password

    def hashing(password, hashed):
        if password == PASSWORD:
            started.set()
            assert release.wait(timeout=10)
        return original(password, hashed)

    monkeypatch.setattr(auth, 'verify_password', hashing)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(direct_login, mysql_factory, password=PASSWORD)
        try:
            assert started.wait(timeout=5)
            assert login_state(mysql_factory)[:2] == (3, 3)
            # Two failures plus one pending reservation still means two REAL failures.
            assert direct_login(mysql_factory, email=equivalent_email) == 401
        finally:
            release.set()
        assert pending.result(timeout=10) == 200
    assert login_state(mysql_factory)[:2] == (4, 3)
    assert siteverify == []
    assert direct_login(mysql_factory) == 428


def test_old_pending_success_cannot_decrement_new_failure_window(mysql_factory, monkeypatch, siteverify):
    add_user(mysql_factory)
    seed_login_failures(mysql_factory, number=2)
    started, release = Event(), Event()
    original = auth.verify_password

    def hashing(password, hashed):
        if password == PASSWORD:
            started.set()
            assert release.wait(timeout=10)
        return original(password, hashed)

    monkeypatch.setattr(auth, 'verify_password', hashing)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(direct_login, mysql_factory, password=PASSWORD)
        try:
            assert started.wait(timeout=5)
            with mysql_factory() as db:
                row = db.get(AuthLoginLimit, EMAIL)
                row.failure_window -= timedelta(seconds=601)
                row.request_window -= timedelta(seconds=61)
                db.commit()
            assert direct_login(mysql_factory) == 401
            assert login_state(mysql_factory)[:2] == (1, 1)
        finally:
            release.set()
        assert pending.result(timeout=10) == 200
    assert login_state(mysql_factory)[:2] == (1, 1)
    assert siteverify == []
    assert lp.global_budget.active == 0 and not lp.global_budget.pending


def test_parallel_logins_cross_soft_threshold_and_do_not_lose_failures(mysql_factory, monkeypatch, siteverify):
    seed_login_failures(mysql_factory, number=2)
    hashing = Barrier(2)

    def failed_hash(*args):
        hashing.wait(timeout=5)
        return False

    monkeypatch.setattr(auth, 'verify_password', failed_hash)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: direct_login(mysql_factory), range(2)))
    assert results == [401, 401]
    assert login_state(mysql_factory)[:2] == (4, 4)
    assert siteverify == []
    assert direct_login(mysql_factory) == 428
    assert lp.global_budget.active == 0


def test_valid_and_invalid_challenge_race_counts_only_credentials(mysql_factory, monkeypatch, siteverify):
    seed_login_failures(mysql_factory)
    verifier = turnstile.verify
    meeting = Barrier(2)

    def simultaneous(token, action):
        meeting.wait(timeout=5)
        return verifier(token, action)

    monkeypatch.setattr(turnstile, 'verify', simultaneous)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda token: direct_login(mysql_factory, token=token), ['valid-race', 'invalid-race']))
    assert sorted(results) == [401, 428]
    assert login_state(mysql_factory)[:2] == (4, 4)
    assert lp.global_budget.active == 0


def test_same_token_concurrent_use_admits_only_one_credential_check(mysql_factory, monkeypatch, siteverify):
    seed_login_failures(mysql_factory)
    verifier = turnstile.verify
    meeting = Barrier(2)

    def simultaneous(token, action):
        meeting.wait(timeout=5)
        return verifier(token, action)

    monkeypatch.setattr(turnstile, 'verify', simultaneous)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: direct_login(mysql_factory, token='valid-same-token'), range(2)))
    assert sorted(results) == [401, 428]
    assert login_state(mysql_factory)[:2] == (4, 4)


def test_hard_limit_rechecked_after_siteverify_with_real_concurrent_failures(mysql_factory, monkeypatch, siteverify):
    seed_login_failures(mysql_factory)
    started, release = Event(), Event()
    verifier = turnstile.verify

    def delayed(token, action):
        if token == 'valid-delayed':
            started.set()
            assert release.wait(timeout=10)
        return verifier(token, action)

    monkeypatch.setattr(turnstile, 'verify', delayed)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(direct_login, mysql_factory, token='valid-delayed')
        try:
            assert started.wait(timeout=5)
            assert direct_login(mysql_factory, token='valid-other-1') == 401
            assert direct_login(mysql_factory, token='valid-other-2') == 401
            before = login_state(mysql_factory)
            assert before[:2] == (5, 5)
        finally:
            release.set()
        assert pending.result(timeout=10) == 429
    assert login_state(mysql_factory) == before
    assert lp.global_budget.active == 0


def test_success_during_siteverify_does_not_erase_historical_failures(mysql_factory, monkeypatch, siteverify):
    add_user(mysql_factory)
    seed_login_failures(mysql_factory)
    started, release = Event(), Event()
    verifier = turnstile.verify

    def delayed(token, action):
        if token == 'valid-delayed':
            started.set()
            assert release.wait(timeout=10)
        return verifier(token, action)

    monkeypatch.setattr(turnstile, 'verify', delayed)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(direct_login, mysql_factory, token='valid-delayed')
        try:
            assert started.wait(timeout=5)
            assert direct_login(mysql_factory, token='valid-success', password=PASSWORD) == 200
            assert login_state(mysql_factory)[:2] == (4, 3)
        finally:
            release.set()
        assert pending.result(timeout=10) == 401
    assert login_state(mysql_factory)[:2] == (5, 4)
    assert count(mysql_factory, AuthSession) == 1


@pytest.mark.parametrize('route,action,challenge_action,limit', FLOWS)
def test_public_action_hard_limit_rechecked_after_parallel_siteverify(mysql_factory, monkeypatch, siteverify,
        route, action, challenge_action, limit):
    assert direct_public(mysql_factory, route) == 202
    # Bring reset to one remaining hard admission; access already has one left.
    for i in range(1, limit - 1):
        assert direct_public(mysql_factory, route, token=f'valid-preload-{i}') == 202
    verifier = turnstile.verify
    meeting = Barrier(2)

    def simultaneous(token, actual_action):
        assert actual_action == challenge_action
        meeting.wait(timeout=5)
        return verifier(token, actual_action)

    monkeypatch.setattr(turnstile, 'verify', simultaneous)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda i: direct_public(mysql_factory, route, token=f'valid-race-{i}'), range(2)))
    assert sorted(results) == [202, 429]
    assert action_state(mysql_factory, action)[0] == limit
    assert count(mysql_factory, Usuario) == 0
    if route == 'access-requests':
        assert count(mysql_factory, AccessRequest) == 1
    else:
        assert count(mysql_factory, AuthMailJob) == limit


@pytest.mark.parametrize('flow', ['login', 'access-requests', 'password-reset/request'])
def test_verifier_unavailable_is_closed_and_does_not_mutate_state(http, mysql_factory, monkeypatch, flow):
    if flow == 'login':
        seed_login_failures(mysql_factory)
        before = login_state(mysql_factory)
    else:
        assert public_request(http, flow).status_code == 202
        action = 'ACCESS_REQUEST' if flow == 'access-requests' else 'RESET_REQUEST'
        before = action_state(mysql_factory, action)
    password_checks = Mock(side_effect=AssertionError('Argon2 must not run during outage'))
    monkeypatch.setattr(auth, 'verify_password', password_checks)

    def unavailable(token, action):
        raise HTTPException(503, 'No podemos completar la verificación en este momento. Intenta más tarde.')

    monkeypatch.setattr(turnstile, 'verify', unavailable)
    response = attempt(http, token='valid-outage') if flow == 'login' else public_request(http, flow, token='valid-outage')
    assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
    assert (login_state(mysql_factory) if flow == 'login' else action_state(mysql_factory, action)) == before
    password_checks.assert_not_called()
    assert count(mysql_factory, AuthSession) == count(mysql_factory, AuthActionToken) == 0
    assert count(mysql_factory, AuthMailJob) == int(flow == 'password-reset/request')


def test_concurrent_verifier_timeouts_do_not_consume_password_budget(mysql_factory, monkeypatch, siteverify):
    seed_login_failures(mysql_factory)
    before = login_state(mysql_factory)
    meeting = Barrier(2)

    def unavailable(token, action):
        meeting.wait(timeout=5)
        raise HTTPException(503, 'No podemos completar la verificación en este momento. Intenta más tarde.')

    monkeypatch.setattr(turnstile, 'verify', unavailable)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda i: direct_login(mysql_factory, token=f'valid-timeout-{i}'), range(2)))
    assert results == [503, 503]
    assert login_state(mysql_factory) == before
    assert lp.global_budget.active == 0


@pytest.mark.parametrize('flow', ['login', 'access-requests', 'password-reset/request'])
@pytest.mark.parametrize('case,status', [
    ('invalid', 428), ('duplicate', 428), ('action', 428), ('hostname', 428),
    ('expired', 428), ('malformed', 503), ('timeout', 503), ('internal', 503),
    ('deep-json', 503), ('duplicate-json', 503), ('huge-body', 503),
    ('timestamp-unicode', 503), ('reset-connection', 503),
])
def test_real_verifier_rejections_stop_before_any_sensitive_operation(
        http, mysql_factory, monkeypatch, flow, case, status, caplog):
    if flow == 'login':
        seed_login_failures(mysql_factory)
        expected_action = 'login'
        before = login_state(mysql_factory)
    else:
        assert public_request(http, flow).status_code == 202
        action = 'ACCESS_REQUEST' if flow == 'access-requests' else 'RESET_REQUEST'
        expected_action = 'access_request' if action == 'ACCESS_REQUEST' else 'password_reset_request'
        before = action_state(mysql_factory, action)
    body = {'success': True, 'action': expected_action, 'hostname': 'localhost',
        'challenge_ts': datetime.now(timezone.utc).isoformat()}
    if case == 'invalid':
        body = {'success': False, 'error-codes': ['invalid-input-response']}
    elif case == 'duplicate':
        body = {'success': False, 'error-codes': ['timeout-or-duplicate']}
    elif case == 'action':
        body['action'] = 'login' if expected_action != 'login' else 'access_request'
    elif case == 'hostname':
        body['hostname'] = 'localhost.attacker.invalid'
    elif case == 'expired':
        body['challenge_ts'] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
    elif case == 'malformed':
        body = {'success': 'true', 'sensitive': 'do-not-log-upstream-body'}
    elif case == 'internal':
        body = {'success': False, 'error-codes': ['internal-error']}
    elif case == 'timestamp-unicode':
        body['challenge_ts'] = body['challenge_ts'].replace('T', '\u2028')
    outbound = Mock(return_value=httpx.Response(200, json=body))
    if case == 'timeout':
        outbound.side_effect = httpx.ReadTimeout('do-not-log-upstream-body')
    elif case == 'reset-connection':
        outbound.side_effect = httpx.ReadError('do-not-log-upstream-body')
    elif case == 'deep-json':
        outbound.return_value = httpx.Response(200, content=b'['*4000+b']'*4000)
    elif case == 'duplicate-json':
        outbound.return_value = httpx.Response(200, content=('{"success":false,'+json.dumps(body)[1:]).encode())
    elif case == 'huge-body':
        outbound.return_value = httpx.Response(200, content=b'x'*16385)
    monkeypatch.setattr(turnstile, '_post', outbound)
    monkeypatch.setattr(turnstile, 'verify', REAL_VERIFY)
    hashes = Mock(side_effect=AssertionError('Forbidden password verification after challenge rejection'))
    monkeypatch.setattr(auth, 'verify_password', hashes)
    token = 'opaque-token-never-log-this'
    response = attempt(http, token=token) if flow == 'login' else public_request(http, flow, token=token)
    assert response.status_code == status
    if status == 428:
        assert_challenge(response, expected_action)
    assert (login_state(mysql_factory) if flow == 'login' else action_state(mysql_factory, action)) == before
    hashes.assert_not_called()
    assert count(mysql_factory, AuthSession) == count(mysql_factory, AuthActionToken) == 0
    assert count(mysql_factory, AuthMailJob) == int(flow == 'password-reset/request')
    assert outbound.call_count == (2 if case in {'timeout', 'internal', 'reset-connection'} else 1)
    for call in outbound.call_args_list:
        assert set(call.args[0]) == {'secret', 'response', 'idempotency_key'}
    if outbound.call_count == 2:
        assert outbound.call_args_list[0].args[0]['idempotency_key'] == outbound.call_args_list[1].args[0]['idempotency_key']
    assert token not in response.text + caplog.text
    assert 'do-not-log-upstream-body' not in response.text + caplog.text
    assert turnstile.verify_budget.active == lp.global_budget.active == 0


@pytest.mark.parametrize('flow', ['login', 'access-requests', 'password-reset/request'])
def test_siteverify_external_hard_budget_is_authoritative_at_http_boundary(http, mysql_factory, monkeypatch, flow):
    if flow == 'login':
        seed_login_failures(mysql_factory)
        before = login_state(mysql_factory)
    else:
        assert public_request(http, flow).status_code == 202
        action = 'ACCESS_REQUEST' if flow == 'access-requests' else 'RESET_REQUEST'
        before = action_state(mysql_factory, action)
    monkeypatch.setattr(turnstile, 'verify', REAL_VERIFY)
    monkeypatch.setattr(settings, 'turnstile_verify_global_per_minute', 1)
    turnstile.verify_budget.acquire()
    turnstile.verify_budget.release()
    outbound = turnstile._post
    response = attempt(http, token='opaque-budget-token') if flow == 'login' else public_request(http, flow, token='opaque-budget-token')
    assert response.status_code == 503
    assert (login_state(mysql_factory) if flow == 'login' else action_state(mysql_factory, action)) == before
    outbound.assert_not_called()
    assert turnstile.verify_budget.active == lp.global_budget.active == 0


@pytest.mark.parametrize('pressure', ['argon-window', 'argon-slots'])
def test_readmission_rechecks_argon_budget_consumed_during_siteverify(mysql_factory, monkeypatch, pressure):
    seed_login_failures(mysql_factory)
    before = login_state(mysql_factory)
    if pressure == 'argon-window':
        monkeypatch.setattr(settings, 'rate_limit_argon2_per_minute', 4)

    def verify(token, action):
        lp.global_budget.acquire_argon2()
        if pressure == 'argon-window':
            lp.global_budget.release_argon2()
        else:
            lp.global_budget.acquire_argon2()

    monkeypatch.setattr(turnstile, 'verify', verify)
    try:
        assert direct_login(mysql_factory, token='valid-concurrent-pressure') == 429
        assert login_state(mysql_factory) == before and not lp.global_budget.pending
    finally:
        if pressure == 'argon-slots':
            lp.global_budget.release_argon2()
            lp.global_budget.release_argon2()
    assert lp.global_budget.active == 0


def test_account_deactivated_during_siteverify_cannot_create_session(mysql_factory, monkeypatch):
    uid = add_user(mysql_factory)
    seed_login_failures(mysql_factory)

    def verify(token, action):
        with mysql_factory() as other:
            other.get(Usuario, uid).activo = False
            other.commit()

    monkeypatch.setattr(turnstile, 'verify', verify)
    assert direct_login(mysql_factory, token='valid-before-deactivation', password=PASSWORD) == 401
    assert count(mysql_factory, AuthSession) == 0
    assert login_state(mysql_factory)[:2] == (4, 4)
    assert not lp.global_budget.pending and lp.global_budget.active == 0


@pytest.mark.parametrize('flow', ['login', 'access-requests', 'password-reset/request'])
def test_challenge_status_body_all_headers_and_query_path_do_not_enumerate(http, mysql_factory, flow):
    identifiers = [f'case{i}@example.invalid' for i in range(4)]
    for i, email in enumerate(identifiers):
        if i:
            add_user(mysql_factory, email=email, active=i != 2, role='ADMIN' if i == 3 else 'AUDITOR_INTERNO')
        if flow == 'login':
            seed_login_failures(mysql_factory, email=email)
        else:
            assert public_request(http, flow, email=email).status_code == 202
    queries, responses, paths = [], [], []
    engine = mysql_factory.kw['bind']

    def observe(conn, cursor, statement, params, context, executemany):
        queries.append(statement.lower())

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        for email in identifiers:
            queries.clear()
            response = attempt(http, email=email) if flow == 'login' else public_request(http, flow, email=email)
            assert response.status_code == 428
            responses.append((response.status_code, response.content, dict(response.headers)))
            paths.append(tuple(queries))
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert all(response == responses[0] for response in responses)
    assert paths[0] and all(path == paths[0] for path in paths)
    assert not any('usuarios' in query for path in paths for query in path)


@pytest.mark.parametrize('flow,page,expected_action', [
    ('login', 'login', 'login'), ('access-requests', 'solicitar_acceso', 'access_request'),
    ('password-reset/request', 'recuperar_password', 'password_reset_request'),
])
def test_real_php_fastapi_mysql_adaptive_roundtrip(request, mysql_factory, monkeypatch, flow, page, expected_action):
    monkeypatch.setenv('TURNSTILE_SITE_KEY', '1x00000000000000000000AA')
    used, calls = set(), []

    def provider(payload):
        calls.append(payload)
        token = payload['response']
        if token != 'valid-php-once' or token in used:
            return httpx.Response(200, json={'success': False, 'error-codes': ['timeout-or-duplicate']})
        used.add(token)
        return httpx.Response(200, json={'success': True, 'action': expected_action, 'hostname': 'localhost',
            'challenge_ts': datetime.now(timezone.utc).isoformat()})

    monkeypatch.setattr(turnstile, '_post', provider)
    c, private, password, users, *_ = request.getfixturevalue('php_mysql')
    email = EMAIL if flow == 'login' else 'unknown-php@example.invalid'
    path = '/index.php?pagina='+page
    form = c.get(path)
    assert 'challenges.cloudflare.com' not in form.text
    data = dict(csrf_token=support.csrf(form), correo=email, password='incorrect', nombre='PHP applicant', motivo='Audit access')
    for _ in range(3 if flow == 'login' else 1):
        assert c.post(path, data=data).status_code == (401 if flow == 'login' else 202)
    challenged = c.post(path, data=data)
    assert challenged.status_code == 428 and f'data-action="{expected_action}"' in challenged.text
    assert 'value="incorrect"' not in challenged.text and calls == []
    data['turnstile_token'] = 'invalid-php-token'
    assert c.post(path, data=data).status_code == 428
    data.update(turnstile_token='valid-php-once', password=password)
    done = c.post(path, data=data)
    assert done.status_code == (303 if flow == 'login' else 202)
    assert len(calls) == 2 and turnstile.verify_budget.active == 0
    assert count(mysql_factory, Usuario) == len(users)
    if flow == 'login':
        assert login_state(mysql_factory)[:2] == (4, 3)
        assert count(mysql_factory, AuthSession) == 1
    else:
        assert count(mysql_factory, AuthSession) == count(mysql_factory, AuthActionToken) == 0
        if flow == 'access-requests':
            assert count(mysql_factory, AccessRequest) == 1
        else:
            assert count(mysql_factory, AuthMailJob) == 2
            assert count(mysql_factory, AuthMailJob, AuthMailJob.recipient.is_not(None)) == 0
            sent = []
            for _ in range(10):
                if not mail.process_one(mysql_factory, sender=lambda *args: sent.append(args)):
                    break
            else:
                pytest.fail('Unbounded mail work')
            assert sent == [] and count(mysql_factory, AuthActionToken) == 0
    session = (private/'sistema-trazabilidad-frontend-sessions'/('sess_'+c.cookies.get('PHPSESSID'))).read_text()
    log = (private.parent/'php.log').read_text(encoding='utf-8')
    for secret in ('valid-php-once', 'invalid-php-token', password):
        assert secret not in session + log + done.text + challenged.text
