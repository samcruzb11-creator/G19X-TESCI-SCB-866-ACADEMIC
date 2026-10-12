"""Private evaluation contract, safe errors and explicit provisioning only."""
import json
from pathlib import Path
import pytest
from app.scripts import evaluation_credentials as credentials
from app.scripts import seed_evaluation_demo as demo


@pytest.fixture
def accounts():
    return credentials.generate_accounts()


def write_contract(path, data):
    path.write_text('```evaluation-credentials-v1\n' + json.dumps(data) + '\n```\n', encoding='utf-8')
    return path


def data(accounts):
    return {'schema_version': 1, 'accounts': [
        {'role': a.role, 'email': a.email, 'password': a.password} for a in accounts]}


def test_default_only_prints_plan(monkeypatch, capsys):
    monkeypatch.setattr(demo, 'seed', lambda **kwargs: pytest.fail('No default writes'))
    assert demo.main(['--with-dataset']) == 0
    output = capsys.readouterr().out
    assert 'Sin cambios' in output and '--confirm-local-demo' in output


@pytest.mark.parametrize('env,host', [('production', '127.0.0.1'), ('development', 'db.example.invalid')])
def test_seed_rejects_production_or_remote_before_connecting(monkeypatch, env, host):
    monkeypatch.setattr(demo.settings, 'app_env', env)
    monkeypatch.setattr(demo.settings, 'db_host', host)
    with pytest.raises(demo.DemoConflict):
        demo.seed(factory=lambda: pytest.fail('Must reject before database access'))


@pytest.mark.parametrize('kind', ['absent', 'missing', 'invalid', 'no-block', 'two-blocks'])
def test_seed_rejects_bad_or_missing_contract_before_database(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(demo.settings, 'app_env', 'development')
    monkeypatch.setattr(demo.settings, 'db_host', '127.0.0.1')
    p = tmp_path / 'private.md'
    if kind != 'missing':
        p.write_text({'invalid': '```evaluation-credentials-v1\n{\n```',
                      'two-blocks': '```evaluation-credentials-v1\n{}\n```\n'*2}.get(kind, 'No contract'), encoding='utf-8')
    with pytest.raises(credentials.CredentialsError):
        demo.seed(factory=lambda: pytest.fail('Bad contract must not connect'),
                  credentials_file=None if kind == 'absent' else p)


@pytest.mark.parametrize('mutation', ['role', 'duplicate-role', 'extra-user', 'real-email',
    'duplicate-email', 'duplicate-password', 'weak-password', 'extra-key', 'version', 'wrong-type'])
def test_contract_rejects_unexpected_accounts(tmp_path, accounts, mutation):
    obj = data(accounts)
    if mutation == 'role': obj['accounts'][0]['role'] = 'AUDITOR_EXTERNO'
    if mutation == 'duplicate-role': obj['accounts'][1]['role'] = 'ADMIN'
    if mutation == 'extra-user': obj['accounts'].append(obj['accounts'][0])
    if mutation == 'real-email': obj['accounts'][0]['email'] = 'person@example.com'
    if mutation == 'duplicate-email': obj['accounts'][1]['email'] = obj['accounts'][0]['email']
    if mutation == 'duplicate-password': obj['accounts'][1]['password'] = obj['accounts'][0]['password']
    if mutation == 'weak-password': obj['accounts'][0]['password'] = 'short'
    if mutation == 'extra-key': obj['accounts'][0]['id'] = 1
    if mutation == 'version': obj['schema_version'] = 2
    if mutation == 'wrong-type': obj['accounts'][0]['password'] = None
    with pytest.raises(credentials.CredentialsError):
        credentials.load_credentials(write_contract(tmp_path / 'private.md', obj))


def test_duplicate_json_keys_rejected(tmp_path):
    p = tmp_path / 'private.md'
    p.write_text('```evaluation-credentials-v1\n{"schema_version":1,"schema_version":1,"accounts":[]}\n```', encoding='utf-8')
    with pytest.raises(credentials.CredentialsError):
        credentials.load_credentials(p)


def test_generation_roundtrip_distinct_secrets_no_stdout(tmp_path, capsys):
    p = tmp_path / 'private.md'
    assert credentials.main(['--output', str(p), '--confirm-generate']) == 0
    loaded = credentials.load_credentials(p)
    assert len({a.password for a in loaded}) == len({a.email for a in loaded}) == 4
    assert all(len(a.password) >= 43 for a in loaded)
    output = capsys.readouterr().out + repr(loaded)
    assert all(a.password not in output and a.email not in output for a in loaded)


def test_generator_never_overwrites_and_requires_opt_in(tmp_path):
    p = tmp_path / 'private.md'
    assert credentials.main(['--output', str(p)]) == 0
    assert not p.exists()
    credentials.generate_file(p)
    before = p.read_bytes()
    assert credentials.main(['--output', str(p), '--confirm-generate']) == 2
    assert p.read_bytes() == before


def test_generation_permission_failure_writes_no_secret(tmp_path, monkeypatch):
    p = tmp_path / 'private.md'
    def reject(path): raise PermissionError('Synthetic ACL failure')
    monkeypatch.setattr(credentials, 'restrict_permissions', reject)
    with pytest.raises(PermissionError): credentials.generate_file(p)
    assert p.read_bytes() == b''


def test_generator_and_parser_reject_repository_output():
    p = credentials.PROJECT_ROOT / '01_ACCESOS_PRUEBA.md'
    with pytest.raises(credentials.CredentialsError): credentials.generate_file(p)
    with pytest.raises(credentials.CredentialsError): credentials.load_credentials(p)
    assert not p.exists()


def test_cli_missing_credentials_fails_closed_without_echo(monkeypatch, capsys):
    monkeypatch.setattr(demo.settings, 'app_env', 'development')
    assert demo.main(['--confirm-local-demo']) == 2
    assert 'Seed no completado' in capsys.readouterr().out


def test_no_fixed_account_or_password_constants_in_seed():
    import ast
    tree = ast.parse(Path(demo.__file__).read_text(encoding='utf-8'))
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not hasattr(demo, 'ACCOUNTS')
    assert not any('@' in s for s in strings)
