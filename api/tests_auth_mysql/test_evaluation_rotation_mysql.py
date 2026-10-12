"""Rotation contracts on the guarded temporary schema, never on the operational database."""
import secrets
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.main import app
from app.models.entities import Usuario, Area
from app.models.auth import AuthSession
from app.scripts import rotate_evaluation_demo as rotation
from app.scripts import seed_evaluation_demo as demo
from app.scripts.evaluation_credentials import generate_file, load_credentials
from app.services.storage_service import StorageService


@pytest.fixture
def prepared(clean_temporary_schema, mysql_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(demo.settings, 'app_env', 'development')
    with mysql_factory() as db:
        db.add(Usuario(id=1, nombre='Historical test sentinel', correo='history@example.invalid',
            correo_normalizado='history@example.invalid', rol='AUDITOR_INTERNO', activo=False,
            password_hash=hash_password(secrets.token_urlsafe(32))))
        db.commit()
        db.execute(text('ALTER TABLE usuarios AUTO_INCREMENT=3'))
        db.commit()
    old = generate_file(tmp_path / 'previous.private.md')
    new = generate_file(tmp_path / 'next.private.md')
    storage = StorageService(tmp_path / 'storage')
    assert demo.seed(factory=mysql_factory, credentials_file=old, storage=storage, with_dataset=True) == 4
    return {'factory': mysql_factory, 'previous_credentials_file': old, 'credentials_file': new,
            'expected_ids': [3, 4, 5, 6]}, storage


def snapshot(factory):
    with factory() as db:
        return rotation.snapshot(db.connection())


def test_rotation_atomic_preserves_history_revokes_sessions_and_old_passwords(prepared):
    args, storage = prepared
    factory = args['factory']
    files = {p.relative_to(storage.base_path): p.read_bytes() for p in storage.base_path.rglob('*') if p.is_file()}
    def sessions():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = sessions
    try:
        with TestClient(app) as client:
            old_tokens = []
            for account in load_credentials(args['previous_credentials_file']):
                login = client.post('/api/v1/auth/login', json={'correo': account.email, 'password': account.password})
                assert login.status_code == 200
                old_tokens.append({'Authorization': 'Bearer ' + login.json()['access_token']})
            before = snapshot(factory)
            with factory() as db:
                history = tuple(db.execute(text('SELECT * FROM usuarios WHERE id=1')).one())
                hashes = [db.get(Usuario, i).password_hash for i in args['expected_ids']]
            plan = rotation.rotate(**args)
            assert snapshot(factory) == before
            result = rotation.rotate(**args, confirm=True, expected_fingerprint=plan['fingerprint'])
            assert result['sessions_revoked'] == 4 and result['password_hashes_changed'] == 4
            after = snapshot(factory)
            assert {k: v for k, v in before.items() if k not in {'usuarios', 'auth_sessions'}} == {
                k: v for k, v in after.items() if k not in {'usuarios', 'auth_sessions'}}
            for auth in old_tokens:
                assert client.get('/api/v1/auth/me', headers=auth).status_code == 401
            for account in load_credentials(args['previous_credentials_file']):
                assert client.post('/api/v1/auth/login', json={'correo': account.email, 'password': account.password}).status_code == 401
            for i, account in enumerate(load_credentials(args['credentials_file'])):
                login = client.post('/api/v1/auth/login', json={'correo': account.email, 'password': account.password})
                assert login.status_code == 200
                auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
                assert client.get('/api/v1/auth/me', headers=auth).json()['rol'] == account.role
                if account.role == 'RESPONSABLE_AREA':
                    assert client.get('/api/v1/usuarios', headers=auth).status_code == 403
                with factory() as db:
                    row = db.get(Usuario, args['expected_ids'][i])
                    assert row.password_hash != hashes[i] and row.password_hash.startswith('$argon2id$')
                    assert verify_password(account.password, row.password_hash)
                    old = load_credentials(args['previous_credentials_file'])[i]
                    assert not verify_password(old.password, row.password_hash)
                assert client.post('/api/v1/auth/logout', headers=auth).status_code == 204
            with factory() as db:
                assert tuple(db.execute(text('SELECT * FROM usuarios WHERE id=1')).one()) == history
                assert db.get(Usuario, 2) is None
            stable = snapshot(factory)
            assert demo.seed(factory=factory, credentials_file=args['credentials_file'], storage=storage, with_dataset=True) == 0
            assert snapshot(factory) == stable
            assert {p.relative_to(storage.base_path): p.read_bytes() for p in storage.base_path.rglob('*') if p.is_file()} == files
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('case', ['no-fingerprint', 'stale-fingerprint', 'historical-id', 'wrong-role',
                                  'collision', 'reused-password', 'missing-provenance'])
def test_rotation_rejects_unsafe_plan_without_partial_changes(prepared, case):
    args, _ = prepared
    plan = rotation.rotate(**args)
    if case == 'historical-id': args['expected_ids'] = [1, 4, 5, 6]
    if case == 'reused-password': args['credentials_file'] = args['previous_credentials_file']
    with args['factory']() as db:
        if case == 'stale-fingerprint': db.add(Area(codigo='STALE', nombre='Synthetic plan change'))
        if case == 'wrong-role': db.get(Usuario, 4).rol = 'ADMIN'
        if case == 'missing-provenance':
            db.execute(text("UPDATE eventos_auditoria SET entidad_id='unrelated' WHERE entidad_tipo='EVALUACION'"))
        if case == 'collision':
            account = load_credentials(args['credentials_file'])[0]
            db.add(Usuario(nombre='Unrelated sentinel', correo=account.email, correo_normalizado=account.email,
                rol='ADMIN', activo=True, password_hash=hash_password(secrets.token_urlsafe(32))))
        db.commit()
    before = snapshot(args['factory'])
    with pytest.raises(demo.DemoConflict):
        rotation.rotate(**args, confirm=True,
            expected_fingerprint=None if case == 'no-fingerprint' else plan['fingerprint'])
    assert snapshot(args['factory']) == before


def test_rotation_rolls_back_if_hashing_fails_midway(prepared, monkeypatch):
    args, _ = prepared
    plan = rotation.rotate(**args)
    before = snapshot(args['factory'])
    original = rotation.hash_password
    calls = 0
    def fail_third(password):
        nonlocal calls
        calls += 1
        if calls == 3: raise RuntimeError('Synthetic failure')
        return original(password)
    monkeypatch.setattr(rotation, 'hash_password', fail_third)
    with pytest.raises(RuntimeError):
        rotation.rotate(**args, confirm=True, expected_fingerprint=plan['fingerprint'])
    assert snapshot(args['factory']) == before
