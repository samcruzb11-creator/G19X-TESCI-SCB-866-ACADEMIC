import importlib.util
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock
import pytest

from app.services.storage_integrity import read_references


def load_cli():
    path = Path(__file__).resolve().parents[2] / 'scripts/verificar_integridad.py'
    spec = importlib.util.spec_from_file_location('integrity_cli_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_queries_never_flush_or_commit():
    db = Mock()
    db.no_autoflush = nullcontext()
    db.execute.side_effect = [[(1, 'documents/a.pdf', 'a'*64, 1)], [(2, 'evidence/b.pdf', 'b'*64, 2)]]
    refs = read_references(db)
    assert len(refs) == 2
    assert all(str(call.args[0]).startswith('SELECT ') for call in db.execute.call_args_list)
    db.flush.assert_not_called()
    db.commit.assert_not_called()
    db.add.assert_not_called()


def test_cli_missing_environment_is_sanitized(monkeypatch, capsys, tmp_path):
    cli = load_cli()
    monkeypatch.delenv('MISSING_TEST_DATABASE_URL', raising=False)
    create = Mock(side_effect=AssertionError('Must not connect'))
    monkeypatch.setattr(cli, 'create_engine', create)
    assert cli.main(['--database-url-env', 'MISSING_TEST_DATABASE_URL', '--storage-root', str(tmp_path)]) == 2
    create.assert_not_called()
    assert 'Traceback' not in capsys.readouterr().err


def test_alternative_database_requires_storage_before_engine(monkeypatch, capsys):
    cli = load_cli()
    create = Mock(side_effect=AssertionError('Must not connect'))
    monkeypatch.setattr(cli, 'create_engine', create)
    with pytest.raises(SystemExit) as exc:
        cli.main(['--database-url-env', 'TEST_DATABASE_URL'])
    assert exc.value.code == 2
    create.assert_not_called()
    assert '--storage-root' in capsys.readouterr().err


def test_cli_returns_discrepancies_without_writing(monkeypatch, tmp_path, capsys):
    cli = load_cli()
    folder = tmp_path / 'documents'; folder.mkdir()
    orphan = folder / 'unreferenced.pdf'; orphan.write_bytes(b'unchanged')
    engine = Mock()
    db = Mock()
    monkeypatch.setenv('FAKE_TEST_URL', 'test-only')
    monkeypatch.setattr(cli, 'create_engine', lambda *a, **k: engine)
    monkeypatch.setattr(cli, 'Session', lambda *a, **k: nullcontext(db))
    monkeypatch.setattr(cli, 'read_references', lambda db: [])
    assert cli.main(['--database-url-env', 'FAKE_TEST_URL', '--storage-root', str(tmp_path)]) == 1
    assert orphan.read_bytes() == b'unchanged'
    out = capsys.readouterr().out
    assert 'orphan_candidate' in out and str(tmp_path) not in out
    engine.dispose.assert_called_once()
    db.commit.assert_not_called()
