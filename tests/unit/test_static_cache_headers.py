"""Cache-Control on /static/* — no-cache, not browser heuristic caching.

Regression test: StaticFiles only sets ETag/Last-Modified on its own, so
without an explicit Cache-Control header browsers fall back to heuristic
caching, which can hold a stale CSS/JS file indefinitely with no
revalidation (notably in Safari) — exactly what made a CSS fix look like
it hadn't deployed, when the live file was actually already correct.

Extended for docs/dev/fix_lcp_image_and_static_cache.md Finding 2 —
no-cache alone meant *every* request revalidated via a conditional GET,
the single largest "potential savings" finding on a real PageSpeed
Insights run. A request carrying a ?v= query parameter is safe to cache
aggressively/immutably instead: a changed asset gets a new URL the
instant its content changes, so the original no-cache safety net stays
as the fallback for anything requested *without* one, not the primary
mechanism.
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
    """A real static asset (theme.css) gets Cache-Control: no-cache when
    requested without a ?v= query parameter — the fallback path, not the
    primary mechanism after Finding 2 (see module docstring)."""
    resp = await app_client.get("/static/theme.css")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.unit
async def test_static_asset_still_has_etag_for_conditional_gets(app_client):
    """no-cache forces revalidation, not re-download — ETag must survive
    so that revalidation is a cheap 304, not a full re-fetch."""
    resp = await app_client.get("/static/theme.css")
    assert "etag" in resp.headers


@pytest.mark.unit
async def test_non_static_route_has_no_cache_control_override(app_client):
    """The middleware only touches /static/* — confirms it doesn't leak
    onto dynamic routes that have their own caching semantics (or none)."""
    resp = await app_client.get("/health")
    assert resp.status_code == 200
    assert "cache-control" not in resp.headers


# ---------------------------------------------------------------------------
# ?v= — long-lived, immutable caching (docs/dev/fix_lcp_image_and_static_
# cache.md Finding 2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_static_asset_with_version_param_gets_long_lived_immutable_cache(app_client):
    """A request carrying ?v= (any value — the app always appends the
    real asset_version, but the middleware's own job is just "does a v
    param exist", not validating its value) gets the aggressive,
    structurally-safe cache header: a new deploy means a new URL, so
    nothing stale can ever be served under an old one.
    """
    resp = await app_client.get("/static/theme.css?v=abc123")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.unit
async def test_static_asset_without_version_param_still_falls_back_to_no_cache(app_client):
    """The exact regression this whole feature must never reintroduce:
    a request with no ?v= at all (the old URL shape, or a browser that
    somehow still has one cached) must keep getting the safe no-cache
    fallback, not the aggressive long-lived header — defense in depth,
    not a mechanism that could itself go stale.
    """
    resp = await app_client.get("/static/theme.css")
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.unit
async def test_home_page_renders_theme_css_with_a_real_version_suffix(app_client):
    resp = await app_client.get("/posts/")
    assert resp.status_code == 200
    assert "/static/theme.css?v=" in resp.text
    # The suffix itself must be a real, non-empty token, not a literal
    # unrendered "{{ asset_version }}" (a template-global wiring bug
    # would produce exactly that).
    marker = "/static/theme.css?v="
    start = resp.text.index(marker) + len(marker)
    version_value = resp.text[start : start + 10]
    assert version_value.strip() and "{{" not in version_value
