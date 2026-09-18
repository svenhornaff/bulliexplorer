"""Google Search Console verification meta tag —
docs/dev/seo_search_console_registration.md Phase 1.

Same real-Settings + monkeypatch + get_settings.cache_clear() pattern
as tests/unit/test_editor.py's R2-config tests — GOOGLE_SITE_VERIFICATION
is environment-dependent (a real token exists in this project's own
local/server .env per the doc), so these tests explicitly control the
env var rather than depending on whatever happens to be in .env, which
would make the "unset" case untestable in this developer's own
environment.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Result

from app.core.config import get_settings
from app.core.db import get_db_session
from app.main import create_app


def _make_empty_session():
    session = AsyncMock()
    mock_result = MagicMock(spec=Result)
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


async def _empty_db():
    yield _make_empty_session()


def _required_env(monkeypatch):
    """Settings with no default (SECRET_KEY, RESYNC_TOKEN, GITHUB_TOKEN,
    WEBHOOK_SECRET) must be set for create_app() to not crash on
    startup — unrelated to what these tests are actually checking."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("RESYNC_TOKEN", "test-resync-token")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-webhook-secret")


@pytest.mark.unit
async def test_google_site_verification_meta_tag_renders_when_configured(monkeypatch):
    """When GOOGLE_SITE_VERIFICATION is set, every page's <head> carries
    the verification meta tag with that exact token."""
    _required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_SITE_VERIFICATION", "test-verification-token-abc123")

    get_settings.cache_clear()
    application = create_app()
    application.dependency_overrides[get_db_session] = _empty_db
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/posts/")
    get_settings.cache_clear()

    assert resp.status_code == 200
    # djlint wraps a <meta> tag with two attributes onto two lines
    # (`name="..."`, then `content="..."` indented on the next line) —
    # check the two attributes independently rather than one exact
    # single-line string, so this test doesn't depend on djlint's
    # current wrapping width.
    assert 'name="google-site-verification"' in resp.text
    assert 'content="test-verification-token-abc123"' in resp.text


@pytest.mark.unit
async def test_google_site_verification_meta_tag_absent_when_unconfigured(monkeypatch):
    """With GOOGLE_SITE_VERIFICATION unset (empty string, the Settings
    default), no verification meta tag is rendered at all — an empty
    token isn't a valid one, and Google's own docs warn against an
    empty/placeholder verification tag.
    """
    _required_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_SITE_VERIFICATION", "")

    get_settings.cache_clear()
    application = create_app()
    application.dependency_overrides[get_db_session] = _empty_db
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/posts/")
    get_settings.cache_clear()

    assert resp.status_code == 200
    assert "google-site-verification" not in resp.text
