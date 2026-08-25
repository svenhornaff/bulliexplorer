"""Unit tests for POST /internal/webhook/github — no DB, no network.

Covers:
- Signature verification: valid, missing, wrong secret.
- Payload parsing: non-develop pushes are ignored (200, no sync).
- Happy path: develop push → fetch_and_write + sync_posts called,
  counts returned correctly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Result

from app.core.db import get_db_session
from app.main import create_app

_WEBHOOK_SECRET = "test-webhook-secret"  # noqa: S105 — test sentinel
_VALID_TOKEN = "test-resync-token"  # noqa: S105 — test sentinel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _push_payload(ref: str = "refs/heads/develop") -> bytes:
    return json.dumps({"ref": ref, "commits": []}).encode()


async def _empty_db():
    session = AsyncMock()
    mock_result = MagicMock(spec=Result)
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    yield session


@pytest.fixture
async def webhook_client(monkeypatch):
    """App with env vars set and DB overridden — no real DB or network."""
    monkeypatch.setenv("WEBHOOK_SECRET", _WEBHOOK_SECRET)
    monkeypatch.setenv("RESYNC_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")

    from app.core.config import get_settings

    get_settings.cache_clear()

    application = create_app()
    application.dependency_overrides[get_db_session] = _empty_db

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_webhook_missing_signature_returns_401(webhook_client):
    """No X-Hub-Signature-256 header → 401, nothing executed."""
    body = _push_payload()
    resp = await webhook_client.post(
        "/internal/webhook/github",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.unit
async def test_webhook_wrong_secret_returns_401(webhook_client):
    """Wrong HMAC secret → 401."""
    body = _push_payload()
    resp = await webhook_client.post(
        "/internal/webhook/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body, secret="wrong-secret"),  # noqa: S106 — test sentinel,
        },
    )
    assert resp.status_code == 401


@pytest.mark.unit
async def test_webhook_malformed_signature_header_returns_401(webhook_client):
    """Signature header without 'sha256=' prefix → 401."""
    body = _push_payload()
    resp = await webhook_client.post(
        "/internal/webhook/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "notsha256=abc",
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Payload parsing — non-develop pushes ignored
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_webhook_push_to_main_ignored(webhook_client):
    """Push to refs/heads/main → 200 with status=ignored."""
    body = _push_payload(ref="refs/heads/main")
    resp = await webhook_client.post(
        "/internal/webhook/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ignored"
    assert "main" in data["reason"]


@pytest.mark.unit
async def test_webhook_push_to_feature_branch_ignored(webhook_client):
    """Push to a feature branch → 200 with status=ignored, no sync."""
    body = _push_payload(ref="refs/heads/feature/my-branch")
    resp = await webhook_client.post(
        "/internal/webhook/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


# ---------------------------------------------------------------------------
# Happy path — develop push triggers fetch + sync
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_webhook_develop_push_calls_fetch_and_sync(webhook_client):
    """Valid develop push → fetch_and_write + sync_posts called, counts returned."""
    body = _push_payload(ref="refs/heads/develop")
    fake_fetch = {"fetched": 2, "deleted": 0}
    fake_sync = {"upserted": 2, "deleted": 0, "skipped": 0}

    with (
        patch("app.routes.internal.fetch_and_write", new=AsyncMock(return_value=fake_fetch)),
        patch("app.routes.internal.sync_posts", new=AsyncMock(return_value=fake_sync)),
    ):
        resp = await webhook_client.post(
            "/internal/webhook/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body),
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["fetch"] == fake_fetch
    assert data["sync"] == fake_sync


@pytest.mark.unit
async def test_webhook_wrong_signature_does_not_call_fetch(webhook_client):
    """Wrong signature → 401, fetch_and_write never called."""
    body = _push_payload()
    with patch("app.routes.internal.fetch_and_write", new=AsyncMock()) as mock_fetch:
        resp = await webhook_client.post(
            "/internal/webhook/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, secret="wrong"),  # noqa: S106 — test sentinel,
            },
        )
    assert resp.status_code == 401
    mock_fetch.assert_not_called()
