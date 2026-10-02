"""Durable mail retries, leases, supersession and uncertain delivery with fake SMTP."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import hashlib

import pytest
from sqlalchemy import select, update

from app.models.entities import Usuario
from app.models.account_access import AuthActionToken, AuthMailJob, AccessRequest
from app.services import account_actions as actions, auth_mail as mail
from test_account_access_mysql import (clean, add_user, count, approve, drain, reset_token,
    initial_token, confirm, PASSWORD, NEW_PASSWORD)


def ready_retry(factory, job_id):
    with factory() as db:
        db.get(AuthMailJob, job_id).available_at = actions.now_utc() - timedelta(seconds=1)
        db.commit()


def pending_reset(factory):
    uid = add_user(factory)
    with factory() as db:
        actions.request_reset(db, 'owner@example.invalid')
    mail.process_one(factory, sender=lambda *args: pytest.fail('Lookup cannot send'))
    with factory() as db:
        job_id = db.scalar(select(AuthMailJob.id).where(AuthMailJob.kind == 'PASSWORD_RESET'))
    return uid, job_id


@pytest.mark.parametrize('failure', [TimeoutError, OSError])
@pytest.mark.parametrize('purpose', ['PASSWORD_RESET','INITIAL_PASSWORD'])
def test_bounded_retries_single_valid_token_same_expiry(mysql_factory, failure, purpose, caplog, capsys):
    if purpose == 'PASSWORD_RESET':
        _, job_id = pending_reset(mysql_factory)
    else:
        approve(mysql_factory)
        with mysql_factory() as db:
            job_id = db.scalar(select(AuthMailJob.id))
    sent = []
    def uncertain(recipient, kind, raw):
        sent.append(raw)
        raise failure('private SMTP credential / arbitrary@example.com / ' + raw)
    for attempt in range(3):
        ready_retry(mysql_factory, job_id)
        assert mail.process_one(mysql_factory, sender=uncertain)
        with mysql_factory() as db:
            job = db.get(AuthMailJob, job_id)
            assert job.attempts == attempt + 1
            assert job.status == ('FAILED' if attempt == 2 else 'PENDING')
            tokens = db.scalars(select(AuthActionToken).where(AuthActionToken.mail_job_id == job_id)).all()
            assert len(tokens) == attempt + 1
            assert len({t.expires_at for t in tokens}) == 1
            assert sum(t.consumed_at is None for t in tokens) == 1
            assert all(t.state_fingerprint == job.state_fingerprint for t in tokens)
    assert not mail.process_one(mysql_factory, sender=uncertain)
    assert len(set(sent)) == 3
    for raw in sent[:-1]: assert confirm(mysql_factory, purpose, raw) == 400
    # Last delivery was uncertain: that link can still work until its original TTL.
    assert confirm(mysql_factory, purpose, sent[-1]) == 200
    logs = caplog.text + capsys.readouterr().out
    assert all(raw not in logs for raw in sent)
    assert 'private SMTP' not in logs and 'arbitrary@example.com' not in logs


@pytest.mark.parametrize('purpose', ['PASSWORD_RESET','INITIAL_PASSWORD'])
def test_crash_after_prepare_reclaims_fences_and_replaces_token(mysql_factory, purpose):
    if purpose == 'PASSWORD_RESET':
        _, job_id = pending_reset(mysql_factory)
    else:
        approve(mysql_factory)
        with mysql_factory() as db: job_id = db.scalar(select(AuthMailJob.id))
    first_id, first_lease = mail.claim(mysql_factory)
    assert first_id == job_id
    old = mail.prepare(mysql_factory, job_id, first_lease)[2]
    with mysql_factory() as db:
        db.get(AuthMailJob, job_id).locked_until = actions.now_utc() - timedelta(seconds=1)
        db.commit()
    new_id, new_lease = mail.claim(mysql_factory)
    assert new_id == job_id and new_lease != first_lease
    assert mail.prepare(mysql_factory, job_id, first_lease) is None
    new = mail.prepare(mysql_factory, job_id, new_lease)[2]
    assert new != old
    mail.finish(mysql_factory, job_id, first_lease, True)
    with mysql_factory() as db:
        job = db.get(AuthMailJob, job_id)
        assert job.lease == new_lease and job.status == 'PROCESSING'
    mail.finish(mysql_factory, job_id, new_lease, True)
    assert confirm(mysql_factory, purpose, old) == 400
    assert confirm(mysql_factory, purpose, new) == 200


def test_concurrent_workers_do_not_double_claim(mysql_factory):
    _, job_id = pending_reset(mysql_factory)
    barrier = Barrier(2)
    def claiming(_):
        barrier.wait(timeout=5)
        return mail.claim(mysql_factory)
    with ThreadPoolExecutor(2) as pool: claimed = list(pool.map(claiming, [0,1]))
    assert sum(c is not None for c in claimed) == 1
    claim = next(c for c in claimed if c is not None)
    assert claim[0] == job_id
    assert mail.prepare(mysql_factory, *claim)[1] == 'PASSWORD_RESET'
    mail.finish(mysql_factory, *claim, True)
    assert count(mysql_factory, AuthActionToken) == 1


def test_parallel_queue_processing_one_outbound_operation(mysql_factory):
    uid = add_user(mysql_factory)
    with mysql_factory() as db:
        for _ in range(3): actions.request_reset(db, 'owner@example.invalid')
    for _ in range(3): mail.process_one(mysql_factory, sender=lambda *args: pytest.fail('lookup only'))
    assert count(mysql_factory, AuthMailJob, AuthMailJob.kind == 'PASSWORD_RESET', AuthMailJob.status == 'PENDING') == 1
    barrier = Barrier(3)
    deliveries = []
    def worker(_):
        barrier.wait(timeout=5)
        return mail.process_one(mysql_factory, sender=lambda *args: deliveries.append(args))
    with ThreadPoolExecutor(3) as pool: results = list(pool.map(worker, range(3)))
    assert sum(results) == 1 and len(deliveries) == 1
    assert deliveries[0][:2] == ('Owner@Example.invalid','PASSWORD_RESET')
    assert count(mysql_factory, AuthActionToken, AuthActionToken.usuario_id == uid) == 1


@pytest.mark.parametrize('change', ['password','email','inactive'])
def test_retry_does_not_reauthorize_changed_credentials(mysql_factory, change):
    uid, job_id = pending_reset(mysql_factory)
    def fail(*args): raise TimeoutError('test only')
    assert mail.process_one(mysql_factory, sender=fail)
    with mysql_factory() as db:
        user = db.get(Usuario, uid)
        if change == 'password': user.password_hash = 'changed-outside-reset'
        elif change == 'email': user.correo = 'changed@example.invalid'
        else: user.activo = False
        db.commit()
    ready_retry(mysql_factory, job_id)
    sent = drain(mysql_factory)
    assert sent == [] and count(mysql_factory, AuthActionToken) == 1
    with mysql_factory() as db: assert db.get(AuthMailJob, job_id).status == 'CANCELLED'


def test_new_request_supersedes_older_worker_and_recipient_never_job_input(mysql_factory):
    uid, old_job = pending_reset(mysql_factory)
    _, old_lease = mail.claim(mysql_factory)
    old_raw = mail.prepare(mysql_factory, old_job, old_lease)[2]
    with mysql_factory() as db:
        actions.request_reset(db, 'owner@example.invalid')
    assert mail.process_one(mysql_factory, sender=lambda *args: pytest.fail('lookup only'))
    assert mail.prepare(mysql_factory, old_job, old_lease) is None
    with mysql_factory() as db:
        new_job = db.scalar(select(AuthMailJob).where(AuthMailJob.kind == 'PASSWORD_RESET', AuthMailJob.status == 'PENDING'))
        new_job.recipient = 'attacker-controlled-job@example.com'
        db.commit()
    messages = drain(mysql_factory)
    assert messages[0][0] == 'Owner@Example.invalid'
    assert confirm(mysql_factory, 'PASSWORD_RESET', old_raw) == 400
    assert confirm(mysql_factory, 'PASSWORD_RESET', messages[0][2]) == 200


def test_send_outside_all_transactions_and_tokens_never_plaintext(mysql_factory):
    _, job_id = pending_reset(mysql_factory)
    observed = []
    class TrackedFactory:
        def __init__(self): self.sessions = []
        def __call__(self):
            db = mysql_factory()
            self.sessions.append(db)
            return db
    tracked = TrackedFactory()
    def sender(recipient, kind, raw):
        observed.append((recipient, kind, raw, all(not db.in_transaction() for db in tracked.sessions)))
    assert mail.process_one(tracked, sender=sender)
    assert observed and observed[0][3]
    raw = observed[0][2]
    with mysql_factory() as db:
        row = db.get(AuthActionToken, hashlib.sha256(raw.encode()).digest())
        assert row.mail_job_id == job_id
        # Inspect every field in every 6C row, not only the intended token column.
        for model in [AuthActionToken, AuthMailJob, AccessRequest]:
            for instance in db.scalars(select(model)):
                assert raw not in repr([getattr(instance, c.name) for c in model.__table__.columns])


@pytest.mark.parametrize('case', ['old','max_attempts','expired_token'])
def test_stale_work_never_sends_or_extends_deadline(mysql_factory, case):
    _, job_id = pending_reset(mysql_factory)
    with mysql_factory() as db:
        job = db.get(AuthMailJob, job_id)
        if case == 'old': job.created_at = actions.now_utc() - timedelta(hours=2)
        elif case == 'max_attempts': job.attempts = 3
        else: job.token_expires_at = actions.now_utc() - timedelta(seconds=1)
        db.commit()
    assert drain(mysql_factory) == []
    assert count(mysql_factory, AuthActionToken) == 0
    with mysql_factory() as db: assert db.get(AuthMailJob, job_id).status == 'FAILED'


def test_initial_ttl_is_fixed_even_when_reset_ttl_shortened(mysql_factory, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'password_reset_ttl_seconds', 60)
    token, _, _ = initial_token(mysql_factory)
    with mysql_factory() as db:
        row = db.get(AuthActionToken, hashlib.sha256(token.encode()).digest())
        assert 1790 < (row.expires_at - row.created_at).total_seconds() <= 1800


def test_confirmation_cancels_an_already_prepared_mail(mysql_factory):
    _, job_id = pending_reset(mysql_factory)
    _, lease = mail.claim(mysql_factory)
    token = mail.prepare(mysql_factory, job_id, lease)[2]
    # Delivery may be in flight. Its late completion cannot revive the job/token.
    assert confirm(mysql_factory, 'PASSWORD_RESET', token) == 200
    mail.finish(mysql_factory, job_id, lease, False)
    with mysql_factory() as db:
        assert db.get(AuthMailJob, job_id).status == 'CANCELLED'
    assert confirm(mysql_factory, 'PASSWORD_RESET', token) == 400
