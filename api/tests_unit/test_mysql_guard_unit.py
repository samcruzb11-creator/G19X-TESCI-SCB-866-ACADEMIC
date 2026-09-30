"""Execute the collection guard with engine creation intercepted; no DB access."""
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest
import sqlalchemy
from sqlalchemy.engine import Engine


@pytest.mark.parametrize('database', [None, 'sistema_trazabilidad', 'other_test', 'sistema_trazabilidad_test'])
def test_mysql_guard_before_engine(monkeypatch, database):
    monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
    if database is not None:
        monkeypatch.setenv('TEST_DATABASE_URL', 'mysql+pymysql://test:dummy@127.0.0.1/' + database)
    create = Mock(return_value=sqlalchemy.create_engine('sqlite://'))
    monkeypatch.setattr(sqlalchemy, 'create_engine', create)
    monkeypatch.setattr(Engine, 'connect', Mock(side_effect=AssertionError('Connection forbidden')))
    path = Path(__file__).resolve().parents[1] / 'tests/conftest.py'
    if database == 'sistema_trazabilidad_test':
        runpy.run_path(str(path))
        create.assert_called_once()
    else:
        with pytest.raises(pytest.exit.Exception) as exc:
            runpy.run_path(str(path))
        assert exc.value.returncode == 2
        create.assert_not_called()
