"""Unit tests for POST /internal/resync — no DB required.

Uses FastAPI dependency overrides for the DB session and monkeypatching
for the token, so no real database or secrets are needed.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_db_session
from app.main import create_app
from app.services.post_sync import SyncResult

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
async def test_resync_wrong_token_logs_security_warning(resync_client, caplog):
    """A wrong token doesn't just 401 silently — it produces a distinct,
    grep-able warning log line (docs/dev/security_review_owasp.md
    Phase 2). Before this, a brute-force attempt against the resync
    token looked identical to normal traffic in the logs.
    """
    with caplog.at_level(logging.WARNING):
        resp = await resync_client.post(
            "/internal/resync",
            headers={"X-Resync-Token": "wrong-token"},
        )

    assert resp.status_code == 401
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Resync auth failed" in msg for msg in warnings)


@pytest.mark.unit
async def test_resync_missing_token_logs_security_warning(resync_client, caplog):
    """A missing token also produces the same distinct warning, not just
    a wrong one.
    """
    with caplog.at_level(logging.WARNING):
        resp = await resync_client.post("/internal/resync")

    assert resp.status_code == 401
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Resync auth failed" in msg for msg in warnings)


@pytest.mark.unit
async def test_resync_correct_token_returns_200(resync_client):
    """Correct token + mocked sync → 200 with counts."""
    fake_result = SyncResult(upserted=1, deleted=0, skipped=0)
    with patch("app.routes.internal.sync_posts", new=AsyncMock(return_value=fake_result)):
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
    # enable_amenity_discovery defaults to False in Settings — no task
    # scheduled, response says so rather than an unqualified "started".
    assert body["amenity_sync"] == "skipped"


@pytest.mark.unit
async def test_resync_returns_sync_counts(resync_client):
    """Counts returned from sync_posts are forwarded in the response."""
    fake_result = SyncResult(upserted=3, deleted=1, skipped=2)
    with patch("app.routes.internal.sync_posts", new=AsyncMock(return_value=fake_result)):
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
async def test_resync_schedules_amenity_task_without_blocking_response(resync_client, monkeypatch):
    """When enable_amenity_discovery is on and sync_posts reports routes
    needing amenity discovery, the resync response must return
    "amenity_sync": "started" without ever awaiting the actual amenity
    sync itself — the whole point of
    docs/dev/fix_startup_blocking_amenity_sync.md Phase 3.
    """
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "enable_amenity_discovery", True)

    fake_result = SyncResult(upserted=1, amenity_route_ids=[42])

    never_awaited = AsyncMock()

    with (
        patch("app.routes.internal.sync_posts", new=AsyncMock(return_value=fake_result)),
        patch("app.services.background_sync.sync_amenities_for_routes", new=never_awaited),
    ):
        resp = await resync_client.post(
            "/internal/resync",
            headers={"X-Resync-Token": _VALID_TOKEN},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["amenity_sync"] == "started"
    # The response returned already — give the scheduled task a tick to
    # actually run, then confirm it did (proving it was genuinely
    # scheduled, not silently dropped), all *after* the response.
    import asyncio

    await asyncio.sleep(0)
    never_awaited.assert_awaited_once()


@pytest.mark.unit
async def test_resync_get_not_allowed(resync_client):
    """GET /internal/resync → 405 (POST only)."""
    resp = await resync_client.get(
        "/internal/resync",
        headers={"X-Resync-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# GET /internal/sync-status (fix_incremental_amenity_writes.md Phase 2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_sync_status_missing_token_returns_401(resync_client):
    """Same auth as /internal/resync — no header → 401."""
    resp = await resync_client.get("/internal/sync-status")
    assert resp.status_code == 401


@pytest.mark.unit
async def test_sync_status_wrong_token_returns_401(resync_client):
    """Same auth as /internal/resync — wrong token → 401."""
    resp = await resync_client.get(
        "/internal/sync-status",
        headers={"X-Resync-Token": "wrong-token"},
    )
    assert resp.status_code == 401


@pytest.mark.unit
async def test_sync_status_reflects_live_in_memory_state(resync_client):
    """The endpoint must reflect whatever's currently tracked in
    geo_sync's in-memory status dict — not a cached/stale snapshot —
    confirmed by mutating the tracker directly (as a running sync would)
    and observing the exact same values through the endpoint.
    """
    import datetime

    from app.services.geo_sync import AmenitySyncStatus, _amenity_sync_status

    _amenity_sync_status.clear()
    now = datetime.datetime.now(datetime.UTC)
    _amenity_sync_status[3] = AmenitySyncStatus(
        chunks_succeeded=5, chunks_failed=1, chunks_total=30, in_progress=True, last_attempt_at=now
    )

    resp = await resync_client.get(
        "/internal/sync-status",
        headers={"X-Resync-Token": _VALID_TOKEN},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["routes"]["3"]["chunks_succeeded"] == 5
    assert body["routes"]["3"]["chunks_failed"] == 1
    assert body["routes"]["3"]["chunks_total"] == 30
    assert body["routes"]["3"]["in_progress"] is True
    assert body["routes"]["3"]["last_attempt_at"] == now.isoformat()

    _amenity_sync_status.clear()


@pytest.mark.unit
async def test_sync_status_empty_when_nothing_ever_synced(resync_client):
    """A route never attempted in this process's lifetime is simply
    absent, not listed with zeroed-out fields.
    """
    from app.services.geo_sync import _amenity_sync_status

    _amenity_sync_status.clear()

    resp = await resync_client.get(
        "/internal/sync-status",
        headers={"X-Resync-Token": _VALID_TOKEN},
    )

    assert resp.status_code == 200
    assert resp.json() == {"routes": {}}
