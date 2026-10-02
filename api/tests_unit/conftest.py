"""Ephemeral JWT configuration for isolated tests, never written to .env."""
import secrets

import pytest


@pytest.fixture(autouse=True)
def isolated_jwt_settings(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "jwt_secret_key", secrets.token_urlsafe(64))
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    from app.services import login_protection
    monkeypatch.setattr(login_protection, "global_budget", login_protection.GlobalLoginBudget())
    from app.services import auth_action_protection
    monkeypatch.setattr(auth_action_protection, 'budget', auth_action_protection.ActionBudget())
    import smtplib
    def no_smtp(*args, **kwargs):
        raise AssertionError('Real SMTP forbidden in tests')
    monkeypatch.setattr(smtplib, 'SMTP', no_smtp)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', no_smtp)
