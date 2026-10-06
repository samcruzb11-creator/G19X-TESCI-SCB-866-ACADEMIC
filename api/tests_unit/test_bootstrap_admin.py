"""CLI boundaries: no passwords in arguments, fallback input or output."""
import importlib.util
from getpass import GetPassWarning
from pathlib import Path
import warnings

import pytest


@pytest.fixture
def tool(monkeypatch):
    spec = importlib.util.spec_from_file_location("bootstrap_unit",
        Path(__file__).resolve().parents[2] / "scripts/bootstrap_admin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "validate_local_target", lambda factory: None)
    return module


@pytest.mark.parametrize("address", ["Mixed@EXAMPLE.INVALID", " mixed@example.invalid "])
def test_identity_uses_official_normalization(tool, address):
    assert tool.validate_identity(" Local Admin ", address) == ("Local Admin", "mixed@example.invalid")


@pytest.mark.parametrize("address", ["not-email", "a@localhost", "a\n@example.invalid", ".a@example.invalid", "a..b@example.invalid", "a@-bad.invalid"])
def test_invalid_address_sanitized(tool, address):
    with pytest.raises(tool.BootstrapError, match="Formato de correo invalido") as exc:
        tool.validate_identity("Local Admin", address)
    assert address not in str(exc.value)


@pytest.mark.parametrize("name", ["", "x", "x" * 161, "Bad\nName", "Bad\x7fName"])
def test_invalid_name(tool, name):
    with pytest.raises(tool.BootstrapError, match="Nombre invalido"):
        tool.validate_identity(name, "admin@example.invalid")


def prompts(monkeypatch, tool, *, password="unit-private-password", confirmation=None, approve=True):
    values = iter(["Local Admin", "ADMIN@EXAMPLE.INVALID", "CREAR ADMIN LOCAL" if approve else "cancel"])
    monkeypatch.setattr("builtins.input", lambda _: next(values))
    passwords = iter([password, password if confirmation is None else confirmation])
    monkeypatch.setattr(tool, "getpass", lambda _: next(passwords))


def test_cli_creates_once_and_never_prints_password(tool, monkeypatch, capsys):
    calls = []
    prompts(monkeypatch, tool)
    monkeypatch.setattr(tool, "create_first_admin", lambda *a, **kw: calls.append((a, kw)) or 123)
    assert tool.main([]) == 0
    assert len(calls) == 1 and calls[0][0] == ("Local Admin", "admin@example.invalid", "unit-private-password")
    output = capsys.readouterr()
    assert "usuario-id 123" in output.out
    assert "unit-private-password" not in output.out + output.err


@pytest.mark.parametrize("approve,confirmation", [(False, None), (True, "different-private-password")])
def test_cancel_or_mismatch_cannot_create(tool, monkeypatch, capsys, approve, confirmation):
    prompts(monkeypatch, tool, approve=approve, confirmation=confirmation)
    monkeypatch.setattr(tool, "create_first_admin", lambda *a, **kw: pytest.fail("must not write"))
    assert tool.main([]) == 1
    assert "private-password" not in capsys.readouterr().out


def test_existing_admin_aborts_before_prompts(tool, monkeypatch, capsys):
    def deny(_):
        raise tool.BootstrapError("Ya existe un ADMIN activo. Bootstrap deshabilitado.")
    monkeypatch.setattr(tool, "validate_local_target", deny)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("must not prompt"))
    monkeypatch.setattr(tool, "getpass", lambda _: pytest.fail("must not request password"))
    assert tool.main([]) == 1
    assert "deshabilitado" in capsys.readouterr().out


def test_getpass_never_falls_back_to_echo(tool, monkeypatch, capsys):
    prompts(monkeypatch, tool)
    def unsupported(_):
        warnings.warn("private-warning-input", GetPassWarning)
        pytest.fail("fallback reached")
    monkeypatch.setattr(tool, "getpass", unsupported)
    assert tool.main([]) == 1
    output = capsys.readouterr()
    assert "private-warning-input" not in output.out + output.err


@pytest.mark.parametrize("args", [["--password", "private-cli-password"], ["--rol", "AUDITOR_INTERNO"]])
def test_cli_rejects_arguments_without_echo(tool, capsys, args):
    with pytest.raises(SystemExit) as exc:
        tool.main(args)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert args[-1] not in output.out + output.err


@pytest.mark.parametrize("password", ["short", "x" * 1025])
def test_invalid_password_before_connection(tool, password):
    def forbidden():
        pytest.fail("invalid password must not connect")
    with pytest.raises(tool.BootstrapError, match="12 y 1024"):
        tool.create_first_admin("Local Admin", "admin@example.invalid", password, factory=forbidden)


def test_driver_exception_is_not_logged(tool, monkeypatch, capsys):
    prompts(monkeypatch, tool)
    def fail(*args, **kw):
        raise RuntimeError("private-password private-hash mysql://private-driver-details")
    monkeypatch.setattr(tool, "create_first_admin", fail)
    assert tool.main([]) == 2
    output = capsys.readouterr()
    assert "private-" not in output.out + output.err
    assert "Inspeccione" in output.out


@pytest.mark.parametrize("attribute,value", [("db_host", "remote.invalid"), ("db_port", 3307), ("db_name", "other_schema"), ("app_env", "production")])
def test_cli_target_guard_before_connection(tool, monkeypatch, attribute, value):
    # Use the original guard rather than the CLI fixture stub.
    spec = importlib.util.spec_from_file_location("bootstrap_guard",
        Path(__file__).resolve().parents[2] / "scripts/bootstrap_admin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from app.core.config import settings
    monkeypatch.setattr(settings, attribute, value)
    with pytest.raises(module.BootstrapError, match="solo"):
        module.validate_local_target(lambda: pytest.fail("unsafe target must not connect"))
