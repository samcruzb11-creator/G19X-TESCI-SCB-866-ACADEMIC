"""Existing 6A regressions on the fresh random schema, without legacy conftest."""
import importlib.util
from pathlib import Path
import pytest

for filename in ['test_storage_and_traceability.py', 'test_file_consistency.py']:
    spec = importlib.util.spec_from_file_location('isolated_6a_' + filename[:-3], Path(__file__).resolve().parents[1] / 'tests' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, value in vars(module).items():
        if name.startswith('test_') or hasattr(value, '_pytestfixturefunction') or type(value).__name__ == 'FixtureFunctionDefinition':
            globals()[name] = value

@pytest.fixture
def db_session_factory(mysql_factory):
    return mysql_factory

@pytest.fixture
def clean_test_database(clean_temporary_schema):
    yield
