"""Unit tests for POST /internal/resync — no DB required.

Uses FastAPI dependency overrides for the DB session and monkeypatching
for the token, so no real database or secrets are needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_db_session
from app.main import create_app

_VALID_TOKEN = "test-resync-token"  # noqa: S105 — test sentinel, not a real secret


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=lambda: None, scalars=MagicMock(return_value=MagicMock(all=lambda: []))
        )
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


async def _mock_db():
    yield _make_mock_session()


@pytest.fixture
async def resync_client(monkeypatch):
    """App with DB overridden and RESYNC_TOKEN set in environment."""
    monkeypatch.setenv("RESYNC_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")

    from app.core.config import get_settings

    get_settings.cache_clear()

    application = create_app()
    application.dependency_overrides[get_db_session] = _mock_db

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Token authentication tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_resync_missing_token_returns_401(resync_client):
    """No X-Resync-Token header → 401."""
    resp = await resync_client.post("/internal/resync")
    assert resp.status_code == 401


@pytest.mark.unit
async def test_resync_wrong_token_returns_401(resync_client):
    """Wrong token → 401."""
    resp = await resync_client.post(
        "/internal/resync",
        headers={"X-Resync-Token": "wrong-token"},
    )
    assert resp.status_code == 401


@pytest.mark.unit
async def test_resync_correct_token_returns_200(resync_client):
    """Correct token + mocked sync → 200 with counts."""
    fake_counts = {"upserted": 1, "deleted": 0, "skipped": 0}
    with patch("app.routes.internal.sync_posts", new=AsyncMock(return_value=fake_counts)):
        resp = await resync_client.post(
            "/internal/resync",
            headers={"X-Resync-Token": _VALID_TOKEN},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["upserted"] == 1
    assert body["deleted"] == 0
    assert body["skipped"] == 0


@pytest.mark.unit
async def test_resync_returns_sync_counts(resync_client):
    """Counts returned from sync_posts are forwarded in the response."""
    fake_counts = {"upserted": 3, "deleted": 1, "skipped": 2}
    with patch("app.routes.internal.sync_posts", new=AsyncMock(return_value=fake_counts)):
        resp = await resync_client.post(
            "/internal/resync",
            headers={"X-Resync-Token": _VALID_TOKEN},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["upserted"] == 3
    assert body["deleted"] == 1
    assert body["skipped"] == 2


@pytest.mark.unit
async def test_resync_get_not_allowed(resync_client):
    """GET /internal/resync → 405 (POST only)."""
    resp = await resync_client.get(
        "/internal/resync",
        headers={"X-Resync-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 405
