"""Config tests — canonical env key, alias, missing key."""

from __future__ import annotations

from pathlib import Path

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
def test_missing_secret_key_raises(monkeypatch):
    """secret_key has no default — missing it must raise ValidationError."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    with pytest.raises(PydanticValidationError):
        Settings(resync_token="tok", _env_file=None)  # type: ignore[call-arg]  # noqa: S106 — test sentinel


@pytest.mark.unit
def test_missing_resync_token_raises(monkeypatch):
    """resync_token has no default — missing it must raise ValidationError."""
    monkeypatch.delenv("RESYNC_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    with pytest.raises(PydanticValidationError):
        Settings(secret_key="sec", _env_file=None)  # type: ignore[call-arg]  # noqa: S106 — test sentinel


@pytest.mark.unit
def test_resync_token_readable():
    settings = Settings(**_REQUIRED)
    # Compare to the dict value, not a hardcoded literal.
    assert settings.resync_token == _REQUIRED["resync_token"]


@pytest.mark.unit
def test_docker_compose_prod_passes_through_every_legal_setting():
    """Every LEGAL_* Settings field must reach the container via
    docker-compose.prod.yml's app.environment block.

    Regression guard for the exact bug this test was added for: commit
    9980066 added `legal_classification` to app/core/config.py but never
    added a matching `LEGAL_CLASSIFICATION=${LEGAL_CLASSIFICATION:-}`
    passthrough line to docker-compose.prod.yml, so the setting silently
    stayed unset (None) inside the production container even though the
    server's .env had it correctly set — /impressum and /datenschutz both
    503'd in production despite a deliberate, correctly-applied config
    change. A config field with no corresponding compose passthrough is a
    silent deployment gap, not a code bug pytest would otherwise catch.
    """
    import yaml

    from app.core.config import Settings

    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    env_lines = compose["services"]["app"]["environment"]
    passed_through = {line.split("=", 1)[0] for line in env_lines}

    legal_fields = [name for name in Settings.model_fields if name.startswith("legal_")]
    assert legal_fields, "expected at least one legal_* Settings field"
    missing = [name for name in legal_fields if name.upper() not in passed_through]
    assert not missing, (
        f"docker-compose.prod.yml is missing passthrough for: {missing} "
        "— add a `KEY=${KEY:-}` line to the app service's environment block."
    )
