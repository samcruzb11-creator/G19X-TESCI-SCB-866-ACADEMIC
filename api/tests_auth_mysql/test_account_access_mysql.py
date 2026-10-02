"""6C HTTP/transaction adversarial tests, only the fixture-owned random MySQL schema."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, local, Event
import hashlib
import importlib.util
import secrets

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func, update, event, inspect
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.config import settings
from app.core.security import hash_password, verify_password, normalize_email, issue_token, ACCESS_SECONDS
from app.db.session import get_db
from app.main import app
from app.models.entities import Usuario
from app.models.auth import AuthSession
from app.models.account_access import AccessRequest, AuthActionToken, AuthMailJob, AuthActionLimit
from app.schemas.account_access import AccessRequestCreate
from app.services import account_actions as actions, auth_mail as mail, auth_action_protection as protection

PASSWORD = 'test-only-password-6c'
NEW_PASSWORD = 'changed-password-6c'
APPLICANT = 'applicant@example.invalid'


@pytest.fixture(autouse=True)
def clean(clean_temporary_schema, monkeypatch):
    for key, value in dict(smtp_host='smtp.example.invalid', smtp_from_address='noreply@example.invalid',
        public_frontend_url='https://frontend.example.invalid', smtp_security='starttls').items():
        monkeypatch.setattr(settings, key, value)


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


def add_user(factory, email='Owner@Example.invalid', role='ADMIN', active=True):
    with factory() as db:
        user = Usuario(nombre='Test owner', correo=email, correo_normalizado=normalize_email(email),
                       rol=role, activo=active, password_hash=hash_password(PASSWORD))
        db.add(user)
        db.commit()
        return user.id


def authenticate(factory, user_id):
    issued, sid = int(datetime.now(timezone.utc).timestamp()), secrets.token_hex(32)
    with factory() as db:
        db.add(AuthSession(sid=sid, usuario_id=user_id,
            created_at=datetime.fromtimestamp(issued, timezone.utc).replace(tzinfo=None),
            expires_at=datetime.fromtimestamp(issued + ACCESS_SECONDS, timezone.utc).replace(tzinfo=None)))
        db.commit()
    return {'Authorization': 'Bearer ' + issue_token(user_id, sid, issued)}


def count(factory, model, *where):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def create_request(factory, email=APPLICANT):
    with factory() as db:
        actions.submit_access(db, AccessRequestCreate(nombre='Applicant', correo=email, motivo='Document review'))
        return db.scalar(select(AccessRequest.id).where(AccessRequest.identifier == normalize_email(email)))


def approve(factory, request_id=None, admin_id=None):
    admin_id = admin_id or add_user(factory)
    request_id = request_id or create_request(factory)
    with factory() as db:
        actions.resolve_access(db, admin_id, request_id, role='AUDITOR_INTERNO')
    return request_id, admin_id


def drain(factory, sender=None):
    delivered = []
    sender = sender or (lambda *message: delivered.append(message))
    for _ in range(30):
        if not mail.process_one(factory, sender=sender):
            return delivered
    raise AssertionError('Unbounded mail work')


def reset_token(factory, email='owner@example.invalid'):
    with factory() as db:
        actions.request_reset(db, email)
    return [m[2] for m in drain(factory) if m[1] == 'PASSWORD_RESET'][-1]


def initial_token(factory):
    request_id, admin_id = approve(factory)
    return drain(factory)[0][2], request_id, admin_id


def confirm(factory, purpose, token):
    with factory() as db:
        try:
            actions.confirm_password(db, purpose, token, NEW_PASSWORD)
            return 200
        except HTTPException as exc:
            return exc.status_code


def test_migration_model_columns_indexes_and_constraints(mysql_factory):
    inspector = inspect(mysql_factory.kw['bind'])
    for model in [AccessRequest, AuthActionLimit, AuthActionToken, AuthMailJob]:
        table = model.__table__
        assert {c['name'] for c in inspector.get_columns(table.name)} == set(table.columns.keys())
        assert {i['name'] for i in inspector.get_indexes(table.name)} >= {i.name for i in table.indexes}
    assert len(inspector.get_foreign_keys('auth_action_tokens')) == 3
    with mysql_factory() as db:
        db.add(AuthMailJob(kind='LOOKUP_RESET', identifier='relay@example.invalid', recipient='relay@example.invalid'))
        with pytest.raises(OperationalError) as exc:
            db.commit()
        assert exc.value.orig.args[0] == 3819  # MySQL CHECK violation, mapped by PyMySQL.
        assert 'ck_lookup_no_recipient' in str(exc.value.orig)


def test_access_created_no_user_no_role_no_session_and_duplicate_collation(http, mysql_factory):
    payload = dict(nombre='Applicant', correo=' José@Example.invalid ', motivo='Document access')
    first = http.post('/api/v1/auth/access-requests', json=payload)
    second = http.post('/api/v1/auth/access-requests', json=payload | {'correo':'JOSE@example.invalid','nombre':'Overwrite attempt'})
    assert first.status_code == second.status_code == 202 and first.json() == second.json()
    assert count(mysql_factory, AccessRequest) == 1
    assert count(mysql_factory, Usuario) == count(mysql_factory, AuthSession) == count(mysql_factory, AuthMailJob) == 0
    with mysql_factory() as db:
        row = db.scalar(select(AccessRequest))
        assert (row.nombre, row.status, row.approved_role, row.resolved_by) == ('Applicant','PENDING',None,None)


@pytest.mark.parametrize('extra', [{'rol':'ADMIN'},{'resolved_by':1},{'password':PASSWORD},{'usuario_id':1}])
def test_public_role_injection_forbidden(http, mysql_factory, extra):
    r = http.post('/api/v1/auth/access-requests', json=dict(nombre='User', correo=APPLICANT, motivo='Needs access') | extra)
    assert r.status_code == 422
    assert count(mysql_factory, AccessRequest) == count(mysql_factory, Usuario) == 0


@pytest.mark.parametrize('role', ['AUDITOR_INTERNO','AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR'])
@pytest.mark.parametrize('operation', ['list','detail','approve','reject','resend'])
def test_admin_only_api(http, mysql_factory, role, operation):
    uid = add_user(mysql_factory, role=role)
    headers = authenticate(mysql_factory, uid)
    req_id = create_request(mysql_factory)
    path = '/api/v1/access-requests'
    if operation != 'list': path += '/' + str(req_id)
    if operation in {'list','detail'}:
        r = http.get(path, headers=headers)
    else:
        body = {'rol':'ADMIN'} if operation == 'approve' else {}
        r = http.post(path + '/' + operation, json=body, headers=headers)
    assert r.status_code == 403
    assert count(mysql_factory, AuthMailJob) == 0


def test_admin_list_detail_approve_role_required_actor_from_session(http, mysql_factory):
    admin = add_user(mysql_factory)
    headers = authenticate(mysql_factory, admin)
    req_id = create_request(mysql_factory)
    path = f'/api/v1/access-requests/{req_id}'
    assert http.get('/api/v1/access-requests').status_code == 401
    listing = http.get('/api/v1/access-requests', headers=headers)
    assert listing.status_code == 200 and listing.json()[0]['id'] == req_id
    assert listing.headers['cache-control'] == 'no-store'
    assert http.get(path, headers=headers).json()['status'] == 'PENDING'
    assert http.post(path+'/approve', json={}, headers=headers).status_code == 422
    assert http.post(path+'/approve', json={'rol':'ADMIN','admin_id':999}, headers=headers).status_code == 422
    approved = http.post(path+'/approve', json={'rol':'AUDITOR_EXTERNO'}, headers=headers)
    assert approved.status_code == 200 and approved.json()['approved_role'] == 'AUDITOR_EXTERNO'
    assert approved.json()['resolved_by'] == admin and approved.json()['resolved_at']
    assert count(mysql_factory, Usuario) == 1  # Only administrator, no applicant account.
    assert count(mysql_factory, AuthActionToken) == 0  # Generated only by worker before SMTP.
    assert count(mysql_factory, AuthMailJob, AuthMailJob.kind == 'INITIAL_PASSWORD') == 1
    assert http.post(path+'/approve', json={'rol':'ADMIN'}, headers=headers).status_code == 409
    assert http.post(path+'/reject', json={}, headers=headers).status_code == 409
    assert http.get('/api/v1/access-requests/999999', headers=headers).status_code == 404


def test_reject_is_audited_and_no_mail_or_account(http, mysql_factory):
    admin = add_user(mysql_factory)
    headers = authenticate(mysql_factory, admin)
    req_id = create_request(mysql_factory)
    r = http.post(f'/api/v1/access-requests/{req_id}/reject', json={'motivo':'No procede'}, headers=headers)
    assert r.status_code == 200
    assert (r.json()['status'], r.json()['resolved_by'], r.json()['approved_role']) == ('REJECTED',admin,None)
    assert r.json()['admin_reason'] == 'No procede' and r.json()['resolved_at']
    assert count(mysql_factory, AuthMailJob) == count(mysql_factory, AuthActionToken) == 0


def test_existing_account_cannot_be_approved_collation(http, mysql_factory):
    uid = add_user(mysql_factory, email='Jose@Example.invalid')
    rid = create_request(mysql_factory, email='josé@example.invalid')
    r = http.post(f'/api/v1/access-requests/{rid}/approve', json={'rol':'ADMIN'}, headers=authenticate(mysql_factory, uid))
    assert r.status_code == 409 and count(mysql_factory, AuthMailJob) == 0


@pytest.mark.parametrize('second', ['approve','reject'])
def test_concurrent_administrators_one_resolution(mysql_factory, second):
    admins = [add_user(mysql_factory, email=f'admin{i}@example.invalid') for i in range(2)]
    rid = create_request(mysql_factory)
    barrier = Barrier(2)
    def resolve(index):
        with mysql_factory() as db:
            barrier.wait(timeout=5)
            try:
                actions.resolve_access(db, admins[index], rid, role='ADMIN' if index == 0 or second == 'approve' else None)
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(resolve, [0,1])) == [200,409]
    assert count(mysql_factory, Usuario) == 2
    assert count(mysql_factory, AuthMailJob) <= 1


def test_initial_password_atomic_creation_no_autologin(mysql_factory, http):
    token, rid, admin = initial_token(mysql_factory)
    with mysql_factory() as db:
        row = db.get(AuthActionToken, hashlib.sha256(token.encode()).digest())
        assert row.purpose == 'INITIAL_PASSWORD' and row.usuario_id is None and row.access_request_id == rid
        assert 1790 < (row.expires_at - row.created_at).total_seconds() <= 1800
    assert count(mysql_factory, Usuario) == 1
    r = http.post('/api/v1/auth/initial-password/confirm', json={'token':token, 'password':NEW_PASSWORD})
    assert r.status_code == 200 and 'access_token' not in r.text and 'set-cookie' not in r.headers
    with mysql_factory() as db:
        req = db.get(AccessRequest, rid)
        user = db.get(Usuario, req.usuario_id)
        assert req.status == 'FULFILLED' and req.resolved_by == admin
        assert (user.nombre, user.correo, user.rol) == ('Applicant',APPLICANT,'AUDITOR_INTERNO')
        assert user.password_hash.startswith('$argon2id$') and verify_password(NEW_PASSWORD, user.password_hash)
    assert count(mysql_factory, AuthSession) == 0
    assert confirm(mysql_factory, 'INITIAL_PASSWORD', token) == 400
    assert count(mysql_factory, Usuario) == 2


@pytest.mark.parametrize('purpose', ['PASSWORD_RESET','INITIAL_PASSWORD'])
@pytest.mark.parametrize('case', ['expired','used','invalid','wrong_purpose'])
def test_token_rejections(mysql_factory, purpose, case):
    if purpose == 'PASSWORD_RESET':
        add_user(mysql_factory)
        token = reset_token(mysql_factory)
    else:
        token, _, _ = initial_token(mysql_factory)
    with mysql_factory() as db:
        row = db.get(AuthActionToken, hashlib.sha256(token.encode()).digest())
        if case == 'expired': row.expires_at = actions.now_utc() - timedelta(seconds=1)
        if case == 'used': row.consumed_at = actions.now_utc()
        db.commit()
    if case == 'invalid': token = secrets.token_urlsafe(32)
    if case == 'wrong_purpose': purpose = 'INITIAL_PASSWORD' if purpose == 'PASSWORD_RESET' else 'PASSWORD_RESET'
    assert confirm(mysql_factory, purpose, token) == 400
    assert count(mysql_factory, Usuario) == 1


@pytest.mark.parametrize('purpose', ['PASSWORD_RESET','INITIAL_PASSWORD'])
def test_concurrent_token_consumption_database_invariant(mysql_factory, monkeypatch, purpose):
    if purpose == 'PASSWORD_RESET':
        add_user(mysql_factory)
        token = reset_token(mysql_factory)
    else:
        token, _, _ = initial_token(mysql_factory)
    # Simulate two independent API processes to prove the DB invariant even without
    # the production single-process Argon2 concurrency gate (tested separately).
    per_thread = local()
    class IndependentProcesses:
        def take(self, *args, **kwargs):
            if not hasattr(per_thread, 'budget'): per_thread.budget = protection.ActionBudget()
            per_thread.budget.take(*args, **kwargs)
        def release_hash(self): per_thread.budget.release_hash()
    monkeypatch.setattr(protection, 'budget', IndependentProcesses())
    barrier = Barrier(2)
    def synchronized_hash(password):
        hashed = hash_password(password)
        barrier.wait(timeout=10)
        return hashed
    monkeypatch.setattr(actions, 'hash_password', synchronized_hash)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: confirm(mysql_factory, purpose, token), [0,1]))
    assert sorted(results) == [200,400]
    assert count(mysql_factory, Usuario) == (2 if purpose == 'INITIAL_PASSWORD' else 1)
    assert count(mysql_factory, AuthSession) == 0


@pytest.mark.parametrize('case', ['active','missing','inactive','collation'])
def test_reset_uniform_deferred_canonical_and_zero_relay(http, mysql_factory, case):
    email = 'correo-no-registrado@example.com'
    if case != 'missing':
        email = 'jOsÉ@example.invalid' if case == 'collation' else 'canonical@example.invalid'
        canonical = 'Jose@Example.invalid' if case == 'collation' else 'Canonical@Example.invalid'
        add_user(mysql_factory, email=canonical, active=case != 'inactive')
    statements = []
    engine = mysql_factory.kw['bind']
    def observe(conn, cursor, statement, params, context, executemany): statements.append(statement)
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        r = http.post('/api/v1/auth/password-reset/request', json={'correo':email},
            headers={'Host':'poison.example.invalid','X-Forwarded-Host':'poison.example.invalid'})
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert r.status_code == 202 and r.json() == {'message':actions.RESET_MESSAGE}
    assert not any('usuarios' in s for s in statements)
    assert count(mysql_factory, AuthActionToken) == 0
    assert count(mysql_factory, AuthMailJob, AuthMailJob.recipient.is_not(None)) == 0
    deliveries = drain(mysql_factory)
    if case in {'missing','inactive'}:
        assert deliveries == []
        assert count(mysql_factory, AuthActionToken) == 0
        assert count(mysql_factory, AuthMailJob, AuthMailJob.recipient.is_not(None)) == 0
        assert count(mysql_factory, AuthMailJob, AuthMailJob.kind != 'LOOKUP_RESET') == 0
    else:
        assert len(deliveries) == 1 and deliveries[0][:2] == (canonical,'PASSWORD_RESET')
        assert count(mysql_factory, AuthActionToken) == 1
        with mysql_factory() as db:
            assert db.scalar(select(AuthMailJob.recipient).where(AuthMailJob.kind == 'PASSWORD_RESET')) == canonical


def test_reset_revokes_all_sessions_invalidates_tokens_and_no_autologin(mysql_factory, http):
    uid = add_user(mysql_factory)
    headers = [authenticate(mysql_factory, uid) for _ in range(3)]
    first = reset_token(mysql_factory)
    second = reset_token(mysql_factory)
    assert confirm(mysql_factory, 'PASSWORD_RESET', first) == 400
    response = http.post('/api/v1/auth/password-reset/confirm', json={'token':second,'password':NEW_PASSWORD})
    assert response.status_code == 200 and 'access_token' not in response.text and 'set-cookie' not in response.headers
    for h in headers:
        assert http.get('/api/v1/auth/me', headers=h).status_code == 401
    assert count(mysql_factory, AuthSession, AuthSession.revoked_at.is_(None)) == 0
    assert count(mysql_factory, AuthActionToken, AuthActionToken.consumed_at.is_(None)) == 0
    with mysql_factory() as db:
        user = db.get(Usuario, uid)
        assert verify_password(NEW_PASSWORD, user.password_hash) and not verify_password(PASSWORD, user.password_hash)
    messages = drain(mysql_factory)
    assert [m[:2] for m in messages] == [('Owner@Example.invalid','PASSWORD_CHANGED')]


@pytest.mark.parametrize('change', ['password','correo','inactive','reactivate'])
def test_external_credential_changes_invalidate_pending_token(mysql_factory, change):
    uid = add_user(mysql_factory)
    token = reset_token(mysql_factory)
    with mysql_factory() as db:
        user = db.get(Usuario, uid)
        if change == 'password': user.password_hash = hash_password('external-password')
        elif change == 'correo': user.correo = 'changed@example.invalid'
        else: user.activo = False
        db.commit()
        if change == 'reactivate':
            user.activo = True
            db.commit()
    assert confirm(mysql_factory, 'PASSWORD_RESET', token) == 400


def test_real_cli_password_change_invalidates_token(mysql_factory, monkeypatch, capsys):
    uid = add_user(mysql_factory)
    token = reset_token(mysql_factory)
    source = Path(__file__).resolve().parents[2] / 'scripts/gestionar_usuario.py'
    spec = importlib.util.spec_from_file_location('isolated_6c_cli', source)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    from app.db import session
    monkeypatch.setattr(session, 'SessionLocal', mysql_factory)
    monkeypatch.setattr(cli.sys, 'argv', ['gestionar_usuario.py','--usuario-id',str(uid),'--correo','owner@example.invalid'])
    monkeypatch.setattr(cli, 'getpass', lambda _: 'changed-through-cli')
    monkeypatch.setattr('builtins.input', lambda _: f'CAMBIAR {uid}')
    assert cli.main() == 0
    assert confirm(mysql_factory, 'PASSWORD_RESET', token) == 400
    assert token not in capsys.readouterr().out


@pytest.mark.parametrize('purpose', ['PASSWORD_RESET','INITIAL_PASSWORD'])
def test_hash_outside_transaction_and_final_revalidation(mysql_factory, monkeypatch, purpose):
    if purpose == 'PASSWORD_RESET':
        uid = add_user(mysql_factory)
        token = reset_token(mysql_factory)
    else:
        token, rid, _ = initial_token(mysql_factory)
    with mysql_factory() as db:
        def racing_hash(password):
            assert not db.in_transaction()
            with mysql_factory() as other:
                if purpose == 'PASSWORD_RESET':
                    other.get(Usuario, uid).activo = False
                else:
                    other.get(AccessRequest, rid).nombre = 'Changed approval data'
                other.commit()
            return hash_password(password)
        monkeypatch.setattr(actions, 'hash_password', racing_hash)
        with pytest.raises(HTTPException) as exc:
            actions.confirm_password(db, purpose, token, NEW_PASSWORD)
        assert exc.value.status_code == 400 and not db.in_transaction()
    assert not protection.budget.hash_active


@pytest.mark.parametrize('action,limit', [('ACCESS_REQUEST',2),('RESET_REQUEST',3),('PASSWORD_RESET',5),('INITIAL_PASSWORD',5)])
def test_identifier_limits_persist_collation_and_window(mysql_factory, monkeypatch, action, limit):
    with mysql_factory() as db:
        for index in range(limit):
            protection.admit(db, action, 'José@example.invalid' if index % 2 else 'jose@example.invalid')
        row = db.scalar(select(AuthActionLimit).where(AuthActionLimit.action == action))
        expires, start = row.expires_at, row.window_start
        monkeypatch.setattr(protection, 'budget', protection.ActionBudget())  # A restart cannot clear durable limit.
        with pytest.raises(HTTPException) as exc:
            protection.admit(db, action, 'jose@example.invalid')
        assert exc.value.status_code == 429 and int(exc.value.headers['Retry-After']) > 0
        db.refresh(row)
        assert (row.count, row.window_start, row.expires_at) == (limit,start,expires)
        row.window_start -= timedelta(days=2)
        db.commit()
        protection.admit(db, action, 'jose@example.invalid')
        db.refresh(row)
        assert row.count == 1


def test_resend_endpoint_rate_limit_and_old_link_invalidated(http, mysql_factory):
    token, rid, admin = initial_token(mysql_factory)
    headers = authenticate(mysql_factory, admin)
    path = f'/api/v1/access-requests/{rid}/resend'
    assert http.post(path, json={}, headers=headers).status_code == 200
    assert confirm(mysql_factory, 'INITIAL_PASSWORD', token) == 400
    new = drain(mysql_factory)[0][2]
    assert new != token
    assert http.post(path, json={}, headers=headers).status_code == 200
    assert http.post(path, json={}, headers=headers).status_code == 429
    assert count(mysql_factory, Usuario) == 1


def test_rollback_on_user_creation_failure_keeps_approval_token(mysql_factory, monkeypatch):
    token, rid, _ = initial_token(mysql_factory)
    with mysql_factory() as db:
        original_flush = db.flush
        def fail_user_flush(*args, **kwargs):
            if any(isinstance(obj, Usuario) for obj in db.new):
                raise IntegrityError('isolated injected collision', {}, Exception())
            return original_flush(*args, **kwargs)
        monkeypatch.setattr(db, 'flush', fail_user_flush)
        with pytest.raises(HTTPException):
            actions.confirm_password(db, 'INITIAL_PASSWORD', token, NEW_PASSWORD)
    with mysql_factory() as db:
        assert db.get(AccessRequest, rid).status == 'APPROVED'
        assert db.get(AuthActionToken, hashlib.sha256(token.encode()).digest()).consumed_at is None
    assert count(mysql_factory, Usuario) == 1


def test_hash_global_five_per_minute_even_for_admin(mysql_factory, http, monkeypatch):
    tokens = []
    for i in range(6):
        add_user(mysql_factory, email=f'admin{i}@example.invalid', role='ADMIN')
        tokens.append(reset_token(mysql_factory, f'admin{i}@example.invalid'))
    calls = []
    def counted(password):
        calls.append(True)
        return hash_password(password)
    monkeypatch.setattr(actions, 'hash_password', counted)
    responses = [http.post('/api/v1/auth/password-reset/confirm', json={'token':t,'password':NEW_PASSWORD}) for t in tokens]
    assert [r.status_code for r in responses] == [200]*5+[429]
    assert len(calls) == 5 and not protection.budget.hash_active


def test_production_hash_concurrency_is_one(mysql_factory, monkeypatch):
    add_user(mysql_factory)
    token = reset_token(mysql_factory)
    started, release = Event(), Event()
    def slow_hash(password):
        started.set()
        assert release.wait(timeout=10)
        return hash_password(password)
    monkeypatch.setattr(actions, 'hash_password', slow_hash)
    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(confirm, mysql_factory, 'PASSWORD_RESET', token)
        try:
            assert started.wait(timeout=5)
            assert confirm(mysql_factory, 'PASSWORD_RESET', token) == 429
        finally:
            release.set()
        assert first.result(timeout=10) == 200
    assert not protection.budget.hash_active


@pytest.mark.parametrize('operation,limit', [('access-requests',2),('password-reset/request',3)])
def test_public_identifier_limit_response_with_admin_jwt(http, mysql_factory, operation, limit):
    uid = add_user(mysql_factory)
    headers = authenticate(mysql_factory, uid)
    payload = {'correo':'nobody@example.invalid'}
    if operation == 'access-requests': payload |= {'nombre':'Applicant','motivo':'Needs access'}
    responses = [http.post('/api/v1/auth/'+operation, json=payload, headers=headers) for _ in range(limit+1)]
    assert [r.status_code for r in responses] == [202]*limit+[429]
    assert int(responses[-1].headers['Retry-After']) > 0


def test_reset_commit_failure_rolls_back_password_token_and_sessions(mysql_factory, monkeypatch):
    uid = add_user(mysql_factory)
    authenticate(mysql_factory, uid)
    token = reset_token(mysql_factory)
    with mysql_factory() as db:
        real_commit = db.commit
        commits = []
        def fail_final_commit():
            commits.append(True)
            if len(commits) == 2: raise RuntimeError('injected failure before transaction commit')
            real_commit()
        monkeypatch.setattr(db, 'commit', fail_final_commit)
        with pytest.raises(RuntimeError):
            actions.confirm_password(db, 'PASSWORD_RESET', token, NEW_PASSWORD)
    with mysql_factory() as db:
        assert verify_password(PASSWORD, db.get(Usuario, uid).password_hash)
        assert db.get(AuthActionToken, hashlib.sha256(token.encode()).digest()).consumed_at is None
        assert db.scalar(select(AuthSession)).revoked_at is None
    assert not protection.budget.hash_active


def test_login_verified_before_reset_cannot_create_session_after_reset(mysql_factory, monkeypatch):
    from app.routers import auth
    from app.schemas.auth import LoginRequest
    from fastapi import Response
    add_user(mysql_factory)
    token = reset_token(mysql_factory)
    def racing_verification(password, hashed):
        valid = verify_password(password, hashed)
        assert confirm(mysql_factory, 'PASSWORD_RESET', token) == 200
        return valid
    monkeypatch.setattr(auth, 'verify_password', racing_verification)
    with mysql_factory() as db:
        with pytest.raises(HTTPException) as exc:
            auth.login(LoginRequest(correo='owner@example.invalid', password=PASSWORD), Response(), db)
        assert exc.value.status_code == 401
    assert count(mysql_factory, AuthSession) == 0
