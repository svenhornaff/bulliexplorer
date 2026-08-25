"""Config tests — canonical env key, alias, missing key."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config import Settings

# Minimal required secrets for constructing Settings in tests.
# noqa: S105, S106 — these are test sentinel values, not real credentials.
_REQUIRED = {
    "secret_key": "test-secret",  # noqa: S106 — test sentinel
    "resync_token": "test-resync-token",  # noqa: S106 — test sentinel
}


@pytest.mark.unit
def test_default_app_env():
    settings = Settings(**_REQUIRED)
    assert settings.app_env == "development"
    assert settings.is_development is True
    assert settings.is_production is False


@pytest.mark.unit
def test_production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    settings = Settings(**_REQUIRED)
    assert settings.is_production is True
    assert settings.is_development is False


@pytest.mark.unit
def test_default_database_url():
    settings = Settings(**_REQUIRED)
    assert "bulliexplorer" in settings.database_url


@pytest.mark.unit
def test_missing_secret_key_raises():
    """secret_key has no default — missing it must raise ValidationError."""
    with pytest.raises(PydanticValidationError):
        # _env_file=None prevents pydantic-settings from reading .env,
        # so only explicitly passed kwargs are available.
        Settings(resync_token="tok", _env_file=None)  # type: ignore[call-arg]  # noqa: S106 — test sentinel


@pytest.mark.unit
def test_missing_resync_token_raises():
    """resync_token has no default — missing it must raise ValidationError."""
    with pytest.raises(PydanticValidationError):
        Settings(secret_key="sec", _env_file=None)  # type: ignore[call-arg]  # noqa: S106 — test sentinel


@pytest.mark.unit
def test_resync_token_readable():
    settings = Settings(**_REQUIRED)
    # Compare to the dict value, not a hardcoded literal.
    assert settings.resync_token == _REQUIRED["resync_token"]
