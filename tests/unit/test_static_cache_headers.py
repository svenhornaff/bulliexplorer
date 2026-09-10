"""Cache-Control on /static/* — no-cache, not browser heuristic caching.

Regression test: StaticFiles only sets ETag/Last-Modified on its own, so
without an explicit Cache-Control header browsers fall back to heuristic
caching, which can hold a stale CSS/JS file indefinitely with no
revalidation (notably in Safari) — exactly what made a CSS fix look like
it hadn't deployed, when the live file was actually already correct.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def app_client():
    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.unit
async def test_static_asset_has_no_cache_header(app_client):
    """A real static asset (theme.css) gets Cache-Control: no-cache."""
    resp = await app_client.get("/static/theme.css")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.unit
async def test_static_asset_still_has_etag_for_conditional_gets(app_client):
    """no-cache forces revalidation, not re-download \u2014 ETag must survive
    so that revalidation is a cheap 304, not a full re-fetch."""
    resp = await app_client.get("/static/theme.css")
    assert "etag" in resp.headers


@pytest.mark.unit
async def test_non_static_route_has_no_cache_control_override(app_client):
    """The middleware only touches /static/* \u2014 confirms it doesn't leak
    onto dynamic routes that have their own caching semantics (or none)."""
    resp = await app_client.get("/health")
    assert resp.status_code == 200
    assert "cache-control" not in resp.headers
