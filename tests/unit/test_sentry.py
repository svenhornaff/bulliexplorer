"""Sentry integration tests — before_send filter + graceful disable."""

from __future__ import annotations

import pytest
from starlette.exceptions import HTTPException

from app.main import _sentry_before_send

# ── before_send filter ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_before_send_drops_404():
    """Expected 404s (unknown slug, missing page) should not reach Sentry."""
    exc = HTTPException(status_code=404, detail="Not Found")
    hint: dict = {"exc_info": (type(exc), exc, None)}  # type: ignore[dict-item]
    event: dict = {"exception": {"values": []}}  # type: ignore[dict-item]

    result = _sentry_before_send(event, hint)
    assert result is None


@pytest.mark.unit
def test_before_send_passes_500():
    """Unexpected server errors must still be reported."""
    exc = RuntimeError("boom")
    hint: dict = {"exc_info": (type(exc), exc, None)}  # type: ignore[dict-item]
    event: dict = {"exception": {"values": []}}  # type: ignore[dict-item]

    result = _sentry_before_send(event, hint)
    assert result is event


@pytest.mark.unit
def test_before_send_passes_422():
    """Validation errors (422) are real bugs worth tracking."""
    exc = HTTPException(status_code=422, detail="Validation Error")
    hint: dict = {"exc_info": (type(exc), exc, None)}  # type: ignore[dict-item]
    event: dict = {"exception": {"values": []}}  # type: ignore[dict-item]

    result = _sentry_before_send(event, hint)
    assert result is event


@pytest.mark.unit
def test_before_send_passes_event_without_exc_info():
    """Events without exc_info (e.g. message captures) pass through."""
    event: dict = {"message": "something happened"}  # type: ignore[dict-item]
    hint: dict = {}  # type: ignore[dict-item]

    result = _sentry_before_send(event, hint)
    assert result is event


# ── Sentry init gating ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_app_starts_without_sentry_dsn(client):
    """App must start and serve requests when SENTRY_DSN is empty."""
    # The default conftest sets no SENTRY_DSN, so it's empty-string.
    # If the app is serving, Sentry-disable path worked.
    pass  # client fixture already proves create_app() succeeded


@pytest.mark.unit
async def test_health_ok_without_sentry(client):
    """Health endpoint works with Sentry disabled."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.unit
def test_sentry_dsn_picked_up_from_env(monkeypatch):
    """When SENTRY_DSN is set, Settings reads it correctly."""
    monkeypatch.setenv("SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")

    from app.core.config import Settings

    s = Settings()
    assert s.sentry_dsn == "https://examplePublicKey@o0.ingest.sentry.io/0"


@pytest.mark.unit
def test_sentry_dsn_defaults_to_empty():
    """SENTRY_DSN defaults to empty string — Sentry stays disabled."""
    from app.core.config import Settings

    s = Settings()
    assert s.sentry_dsn == ""
