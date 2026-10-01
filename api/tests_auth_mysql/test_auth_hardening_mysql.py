"""6B.4A against the fixture-owned random MySQL schema, never the app DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from unittest.mock import Mock
import secrets

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text, inspect

from app.core.config import settings
from app.core.security import DUMMY_HASH, hash_password
from app.db.session import get_db
from app.main import app
from app.models.auth import AuthLoginLimit, AuthSession
from app.models.entities import Usuario
from app.routers import auth
from app.schemas.auth import LoginRequest
from app.services import login_protection as lp
from app.services.auth_pruning import prune, maintenance_main


@pytest.fixture(autouse=True)
def clean(clean_temporary_schema):
    pass


@pytest.fixture
def http(mysql_factory):
    def db():
        with mysql_factory() as session:
            yield session
    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def attempt(http, email='nobody@example.invalid', password='incorrect'):
    return http.post('/api/v1/auth/login', json={'correo': email, 'password': password})


def add_user(factory, active=True, role='ADMIN'):
    with factory() as db:
        user = Usuario(nombre='Isolated', correo='owner@example.invalid', correo_normalizado='owner@example.invalid',
                       password_hash=hash_password('test-only-password'), activo=active, rol=role)
        db.add(user); db.commit()
        return user.id


def state(factory, identifier='nobody@example.invalid'):
    with factory() as db:
        row = db.get(AuthLoginLimit, identifier)
        return (row.request_count, row.failure_count, row.request_window, row.failure_window, row.expires_at)


def reserve(factory, identifier, success=False):
    with factory() as db:
        reservation = lp.reserve(db, identifier)
        assert not db.in_transaction()
        lp.global_budget.release_argon2()
        if success:
            lp.release_reservation(db, reservation)
        return reservation


def test_schema(mysql_factory):
    with mysql_factory() as db:
        ddl = db.execute(text('SHOW CREATE TABLE auth_login_limits')).one()[1]
        assert 'utf8mb4_unicode_ci' in ddl
        inspector = inspect(db.bind)
        assert inspector.get_pk_constraint('auth_login_limits')['constrained_columns'] == ['identifier']
        assert len(inspector.get_columns('auth_login_limits')) == 6
        assert {i['name'] for i in inspector.get_indexes('auth_login_limits')} == {'ix_auth_login_limits_expires_at'}


@pytest.mark.parametrize('case', ['missing', 'inactive', 'wrong_admin'])
def test_five_failures_same_policy_no_hash_after_rejection(http, mysql_factory, monkeypatch, case):
    email = 'nobody@example.invalid'
    if case != 'missing':
        add_user(mysql_factory, active=case != 'inactive')
        email = 'owner@example.invalid'
    verifier = Mock(wraps=auth.verify_password)
    monkeypatch.setattr(auth, 'verify_password', verifier)
    failures = [attempt(http, email) for _ in range(5)]
    assert all(r.status_code == 401 for r in failures)
    assert len({r.text for r in failures}) == 1
    before = state(mysql_factory, email)
    denied = attempt(http, email)
    assert denied.status_code == 429
    assert denied.json() == {'detail': {'code':'login_rate_limited', 'message': lp.MESSAGE}}
    assert 590 <= int(denied.headers['Retry-After']) <= 600
    assert denied.headers['cache-control'] == 'no-store'
    assert state(mysql_factory, email) == before
    assert verifier.call_count == 5
    if case == 'missing':
        assert all(c.args[1] == DUMMY_HASH for c in verifier.call_args_list)
    assert attempt(http, 'other@example.invalid').status_code == 401


def test_success_preserves_history_and_request_limit(http, mysql_factory):
    add_user(mysql_factory)
    email = 'owner@example.invalid'
    assert attempt(http, email).status_code == 401
    for _ in range(9):
        response = attempt(http, email, 'test-only-password')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
    assert state(mysql_factory, email)[:2] == (10, 1)
    response = attempt(http, email, 'test-only-password')
    assert response.status_code == 429 and 1 <= int(response.headers['Retry-After']) <= 60


def test_collation_variants_share_one_bucket(http, mysql_factory):
    variants = [' Café@example.invalid ', 'CAFÉ@EXAMPLE.INVALID', 'cafe@example.invalid',
                'cafe\u0301@example.invalid', 'café@example.invalid']
    assert all(attempt(http, value).status_code == 401 for value in variants)
    assert attempt(http, variants[0]).status_code == 429
    with mysql_factory() as db:
        assert db.scalar(select(func.count()).select_from(AuthLoginLimit)) == 1


def test_expiry_and_old_reservation_cannot_decrement_new_window(mysql_factory):
    old = reserve(mysql_factory, 'nobody@example.invalid')
    with mysql_factory() as db:
        row = db.get(AuthLoginLimit, old.identifier)
        row.request_window -= timedelta(minutes=2)
        row.failure_window -= timedelta(minutes=11)
        db.commit()
    newer = reserve(mysql_factory, old.identifier)
    with mysql_factory() as db:
        lp.release_reservation(db, old)
    assert state(mysql_factory)[:2] == (1, 1)
    with mysql_factory() as db:
        lp.release_reservation(db, newer)
    assert state(mysql_factory)[:2] == (1, 0)


def test_global_spraying_and_restart(http, mysql_factory, monkeypatch):
    monkeypatch.setattr(settings, 'rate_limit_login_requests_per_minute', 3)
    assert all(attempt(http, f'{i}@example.invalid').status_code == 401 for i in range(3))
    before = state(mysql_factory, '0@example.invalid')
    verifier = Mock(side_effect=AssertionError('Hash forbidden'))
    monkeypatch.setattr(auth, 'verify_password', verifier)
    assert attempt(http, 'new@example.invalid').status_code == 429
    verifier.assert_not_called()
    with mysql_factory() as db:
        assert db.get(AuthLoginLimit, 'new@example.invalid') is None
    monkeypatch.setattr(lp, 'global_budget', lp.GlobalLoginBudget())
    assert state(mysql_factory, '0@example.invalid') == before
    reserve(mysql_factory, '0@example.invalid')
    assert state(mysql_factory, '0@example.invalid')[:2] == (2, 2)


def test_argon_global_rejection_rolls_back_bucket(http, mysql_factory, monkeypatch):
    monkeypatch.setattr(settings, 'rate_limit_argon2_per_minute', 1)
    assert attempt(http).status_code == 401
    before = state(mysql_factory)
    assert attempt(http).status_code == 429
    assert state(mysql_factory) == before
    assert attempt(http, 'new@example.invalid').status_code == 429
    with mysql_factory() as db:
        assert db.get(AuthLoginLimit, 'new@example.invalid') is None


def test_creation_race_and_atomic_count(mysql_factory):
    barrier = Barrier(2)
    def concurrent(_):
        barrier.wait(timeout=5)
        return reserve(mysql_factory, 'race@example.invalid')
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(concurrent, range(2)))
    assert state(mysql_factory, 'race@example.invalid')[:2] == (2, 2)


def test_concurrent_last_reservation_cannot_bypass_threshold(mysql_factory):
    for _ in range(4):
        reserve(mysql_factory, 'race@example.invalid')
    barrier = Barrier(2)
    def concurrent(_):
        barrier.wait(timeout=5)
        try:
            reserve(mysql_factory, 'race@example.invalid')
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(concurrent, range(2)))
    assert sorted(results) == [200, 429]
    assert state(mysql_factory, 'race@example.invalid')[:2] == (5, 5)


def test_limited_window_expires_and_rejection_does_not_extend(http, mysql_factory):
    for _ in range(5):
        reserve(mysql_factory, 'nobody@example.invalid')
    before = state(mysql_factory)
    for _ in range(3):
        assert attempt(http).status_code == 429
    assert state(mysql_factory) == before
    with mysql_factory() as db:
        row = db.get(AuthLoginLimit, 'nobody@example.invalid')
        row.failure_window -= timedelta(seconds=601)
        row.request_window -= timedelta(seconds=61)
        db.commit()
    assert attempt(http).status_code == 401
    assert state(mysql_factory)[:2] == (1, 1)


def test_proxy_headers_cannot_reset_bucket(http):
    for _ in range(5):
        assert attempt(http).status_code == 401
    response = http.post('/api/v1/auth/login', json={'correo':'nobody@example.invalid','password':'wrong'},
        headers={'X-Forwarded-For':'203.0.113.1','X-Real-IP':'203.0.113.2','CF-Connecting-IP':'203.0.113.3'})
    assert response.status_code == 429


def test_failed_commit_rolls_back_and_releases_slot(mysql_factory, monkeypatch):
    with mysql_factory() as db:
        monkeypatch.setattr(db, 'commit', Mock(side_effect=RuntimeError('injected')))
        with pytest.raises(RuntimeError):
            lp.reserve(db, 'rollback@example.invalid')
        assert not db.in_transaction()
    assert lp.global_budget.active == 0
    with mysql_factory() as db:
        assert db.get(AuthLoginLimit, 'rollback@example.invalid') is None


def test_no_transaction_or_bucket_lock_during_argon(mysql_factory, monkeypatch):
    original = auth.verify_password
    with mysql_factory() as db:
        def verify(password, hashed):
            assert not db.in_transaction()
            # A second connection can lock the same bucket while the hash runs.
            with mysql_factory() as second:
                second.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                row = second.scalar(select(AuthLoginLimit).with_for_update())
                assert row is not None
                second.rollback()
            return original(password, hashed)
        monkeypatch.setattr(auth, 'verify_password', verify)
        with pytest.raises(HTTPException) as exc:
            auth.login(LoginRequest(correo='nobody@example.invalid', password='wrong'), Response(), db)
        assert exc.value.status_code == 401


def test_two_hashes_and_third_rejected_without_hash(mysql_factory, monkeypatch):
    entered = Barrier(3)
    release = Event()
    def verify(*args):
        entered.wait(timeout=5)
        assert release.wait(timeout=5)
        return False
    monkeypatch.setattr(auth, 'verify_password', verify)
    def run(email):
        with mysql_factory() as db:
            try:
                auth.login(LoginRequest(correo=email, password='wrong'), Response(), db)
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, f'{i}@example.invalid') for i in range(2)]
        try:
            entered.wait(timeout=5)
            assert run('third@example.invalid') == 429
        finally:
            release.set()
        assert [f.result(timeout=5) for f in futures] == [401, 401]
    assert lp.global_budget.active == 0


def test_auth_success_and_errors_no_store(http, mysql_factory):
    add_user(mysql_factory)
    success = attempt(http, 'owner@example.invalid', 'test-only-password')
    headers = {'Authorization': 'Bearer ' + success.json()['access_token']}
    responses = [success, http.get('/api/v1/auth/me', headers=headers),
                 http.post('/api/v1/auth/logout', headers=headers),
                 http.get('/api/v1/auth/me', headers=headers),
                 http.post('/api/v1/auth/logout', headers=headers),
                 attempt(http), http.post('/api/v1/auth/login', json={})]
    assert [r.status_code for r in responses] == [200, 200, 204, 401, 401, 401, 422]
    assert all(r.headers['cache-control'] == 'no-store' for r in responses)


@pytest.mark.parametrize('kind', ['sessions','limits'])
def test_pruning_batches_dry_run_idempotence(mysql_factory, kind, capsys, monkeypatch):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user_id = add_user(mysql_factory)
    with mysql_factory() as db:
        for i in range(7):
            expiry = now - timedelta(days=2) if i < 5 else now + timedelta(minutes=15)
            if kind == 'sessions':
                db.add(AuthSession(sid=secrets.token_hex(32), usuario_id=user_id,
                                  created_at=expiry-timedelta(minutes=15), expires_at=expiry,
                                  revoked_at=expiry-timedelta(minutes=2) if i == 0 else None))
            else:
                db.add(AuthLoginLimit(identifier=f'private-{i}@example.invalid', request_window=now,
                    request_count=1, failure_window=now, failure_count=1, expires_at=expiry))
        # Recently expired session remains within the 24-hour retention.
        if kind == 'sessions':
            db.add(AuthSession(sid=secrets.token_hex(32), usuario_id=user_id,
                created_at=now-timedelta(hours=2), expires_at=now-timedelta(hours=1)))
        db.commit()
        model = AuthSession if kind == 'sessions' else AuthLoginLimit
        initial = db.scalar(select(func.count()).select_from(model))
        assert prune(db, kind, dry_run=True, batch_size=2, max_batches=2, now=now) == 4
        assert db.scalar(select(func.count()).select_from(model)) == initial
        db.rollback()
        commits = Mock(wraps=db.commit)
        monkeypatch.setattr(db, 'commit', commits)
        assert prune(db, kind, batch_size=2, max_batches=2, now=now) == 4
        assert commits.call_count == 2
        assert prune(db, kind, batch_size=2, max_batches=2, now=now) == 1
        assert prune(db, kind, now=now) == 0
        assert db.scalar(select(func.count()).select_from(model)) == initial - 5
    assert maintenance_main(kind, ['--dry-run'], factory=mysql_factory) == 0
    assert '@' not in capsys.readouterr().out


@pytest.mark.parametrize('kind', ['sessions', 'limits'])
def test_pruning_exact_cutoff(mysql_factory, kind):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=24) if kind == 'sessions' else now
    user_id = add_user(mysql_factory)
    model = AuthSession if kind == 'sessions' else AuthLoginLimit
    with mysql_factory() as db:
        for i, expiry in enumerate([cutoff, cutoff + timedelta(microseconds=1)]):
            if kind == 'sessions':
                db.add(AuthSession(sid=secrets.token_hex(32), usuario_id=user_id,
                    created_at=expiry-timedelta(minutes=15), expires_at=expiry))
            else:
                db.add(AuthLoginLimit(identifier=f'{i}@example.invalid', request_window=now,
                    request_count=1, failure_window=now, failure_count=1, expires_at=expiry))
        db.commit()
        assert prune(db, kind, now=now) == 1
        assert db.scalar(select(func.count()).select_from(model)) == 1


def test_pruning_rollback(mysql_factory, monkeypatch):
    reserve(mysql_factory, 'keep@example.invalid')
    with mysql_factory() as db:
        db.get(AuthLoginLimit, 'keep@example.invalid').expires_at = datetime(2000, 1, 1)
        db.commit()
        monkeypatch.setattr(db, 'commit', Mock(side_effect=RuntimeError('injected')))
        with pytest.raises(RuntimeError):
            prune(db, 'limits')
        assert not db.in_transaction()
    with mysql_factory() as db:
        assert db.get(AuthLoginLimit, 'keep@example.invalid') is not None
