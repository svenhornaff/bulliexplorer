"""Shared fixtures for unit + integration tests."""

from __future__ import annotations

import os

# Set required secrets BEFORE any app import so Settings() never crashes.
# These are dummy values — tests must never hit real services.
os.environ.setdefault("SECRET_KEY", "test-secret-not-for-production")
os.environ.setdefault("RESYNC_TOKEN", "test-resync-token")
os.environ.setdefault("GITHUB_TOKEN", "test-github-token")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Clear the lru_cache so each test gets fresh Settings."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app():
    """Fresh FastAPI app instance per test."""
    return create_app()


@pytest.fixture
async def client(app):
    """Async test client — no real server needed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
