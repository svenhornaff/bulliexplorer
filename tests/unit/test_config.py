"""Config tests — canonical env key, alias, missing key."""

from __future__ import annotations

import pytest

from app.core.config import Settings


@pytest.mark.unit
def test_default_app_env():
    settings = Settings()
    assert settings.app_env == "development"
    assert settings.is_development is True
    assert settings.is_production is False


@pytest.mark.unit
def test_production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    settings = Settings()
    assert settings.is_production is True
    assert settings.is_development is False


@pytest.mark.unit
def test_default_database_url():
    settings = Settings()
    assert "bulliexplorer" in settings.database_url
