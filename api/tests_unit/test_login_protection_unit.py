"""Deterministic admission tests, without a database or wall-clock sleeps."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from unittest.mock import Mock

from app.core.config import Settings, settings
from app.main import app
from app.db.session import get_db
from app.services import login_protection as lp


def assert_limited(call, retry=None):
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 429
    assert exc.value.detail == {'code': 'login_rate_limited', 'message': lp.MESSAGE}
    assert int(exc.value.headers['Retry-After']) >= 1
    if retry is not None:
        assert exc.value.headers['Retry-After'] == str(retry)


def test_global_windows_and_restart(monkeypatch):
    clock = [0.0]
    budget = lp.GlobalLoginBudget(lambda: clock[0])
    monkeypatch.setattr(settings, 'rate_limit_login_requests_per_minute', 2)
    budget.request(); budget.request()
    assert_limited(budget.request, 60)
    clock[0] = 59.2
    assert_limited(budget.request, 1)
    clock[0] = 60
    budget.request()
    lp.GlobalLoginBudget(lambda: 60).request()


def test_argon_budget_independent_of_slot(monkeypatch):
    monkeypatch.setattr(settings, 'rate_limit_argon2_per_minute', 2)
    budget = lp.GlobalLoginBudget(lambda: 0)
    for _ in range(2):
        budget.acquire_argon2(); budget.release_argon2()
    assert_limited(budget.acquire_argon2, 60)
    assert budget.active == 0


def test_concurrent_slots_and_nonblocking_lock():
    budget = lp.GlobalLoginBudget()
    budget.acquire_argon2(); budget.acquire_argon2()
    assert_limited(budget.acquire_argon2, 1)
    budget.release_argon2(); budget.acquire_argon2()
    budget.release_argon2(); budget.release_argon2()
    with budget.lock:
        assert_limited(budget.request)
        assert_limited(budget.acquire_argon2)


def test_parallel_admission_never_exceeds_two():
    budget = lp.GlobalLoginBudget()
    barrier = Barrier(8)
    def attempt(_):
        barrier.wait(timeout=5)
        try:
            budget.acquire_argon2()
            return True
        except HTTPException:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(results) == 2 and budget.active == 2
    budget.release_argon2(); budget.release_argon2()


def test_untrusted_proxy_headers():
    assert lp.trusted_client_origin(Mock(headers={'X-Forwarded-For': '1.2.3.4'})) is None


@pytest.mark.parametrize('field,value', [
    ('rate_limit_argon2_concurrency', 0), ('rate_limit_argon2_per_minute', -1),
    ('rate_limit_failure_window_seconds', 1201), ('rate_limit_challenge_failures', 0),
])
def test_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_early_budget_before_parsing_or_database(monkeypatch):
    monkeypatch.setattr(settings, 'rate_limit_login_requests_per_minute', 1)
    forbidden = Mock(side_effect=AssertionError('DB must not run after global rejection'))
    app.dependency_overrides[get_db] = forbidden
    try:
        lp.global_budget.request()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post('/api/v1/auth/login', content=b'not json')
        assert response.status_code == 429
        assert response.headers['cache-control'] == 'no-store'
        forbidden.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('path,method', [('login','post'), ('me','get'), ('logout','post')])
def test_no_store_unhandled_errors(path, method):
    def broken():
        raise RuntimeError('private')
    app.dependency_overrides[get_db] = broken
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = getattr(client, method)('/api/v1/auth/' + path, **(
                {'json': {'correo':'x@example.invalid','password':'x'}} if path == 'login' else {}))
        assert r.status_code in {401, 500}
        assert r.headers['cache-control'] == 'no-store'
        assert 'private' not in r.text
    finally:
        app.dependency_overrides.clear()


def test_validation_and_missing_credentials_no_store():
    app.dependency_overrides[get_db] = lambda: Mock()
    try:
        with TestClient(app) as client:
            responses = [client.post('/api/v1/auth/login', json={}),
                         client.get('/api/v1/auth/me'), client.post('/api/v1/auth/logout')]
        assert [r.status_code for r in responses] == [422, 401, 401]
        assert all(r.headers['cache-control'] == 'no-store' for r in responses)
    finally:
        app.dependency_overrides.clear()


def test_rollback_failure_cannot_leak_argon_slot():
    now = datetime(2026, 10, 1)
    row = Mock(request_window=now, request_count=0, failure_window=now,
               failure_count=0, expires_at=now + timedelta(minutes=20))
    db = Mock()
    db.scalar.side_effect = [now, row, now]
    db.commit.side_effect = RuntimeError('injected commit failure')
    db.rollback.side_effect = RuntimeError('injected rollback failure')
    with pytest.raises(RuntimeError):
        lp.reserve(db, 'isolated@example.invalid')
    assert lp.global_budget.active == 0
