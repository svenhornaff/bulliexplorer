"""Smoke tests for Phase 3/4 templates — no DB required.

Uses FastAPI dependency overrides to inject a mock session so DB-backed
routes can be tested without a running database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Result

from app.core.db import get_db_session
from app.main import create_app

# ---------------------------------------------------------------------------
# Helpers — mock session factory
# ---------------------------------------------------------------------------


def _make_mock_session(scalar_result=None, scalars_result=None):
    """Return a mock AsyncSession whose execute() returns controlled results."""
    session = AsyncMock()

    mock_result = MagicMock(spec=Result)
    mock_result.scalar_one_or_none.return_value = scalar_result
    mock_result.scalars.return_value.all.return_value = scalars_result or []

    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


async def _empty_session():
    """Dependency override: session that returns no posts."""
    yield _make_mock_session(scalar_result=None, scalars_result=[])


@pytest.fixture
def app_with_mock_db():
    """App instance with get_db_session overridden to avoid real DB."""
    application = create_app()
    application.dependency_overrides[get_db_session] = _empty_session
    return application


@pytest.fixture
async def mock_client(app_with_mock_db):
    transport = ASGITransport(app=app_with_mock_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Home redirect
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_root_redirects_to_posts(mock_client):
    resp = await mock_client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/posts/"


# ---------------------------------------------------------------------------
# Post list page (/posts/)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_list_returns_200(mock_client):
    resp = await mock_client.get("/posts/")
    assert resp.status_code == 200


@pytest.mark.unit
async def test_post_list_contains_site_name(mock_client):
    resp = await mock_client.get("/posts/")
    assert "BulliExplorer" in resp.text


@pytest.mark.unit
async def test_post_list_has_bootstrap_navbar(mock_client):
    resp = await mock_client.get("/posts/")
    assert 'id="mainNav"' in resp.text
    assert "navbar-brand" in resp.text


@pytest.mark.unit
async def test_post_list_has_masthead(mock_client):
    resp = await mock_client.get("/posts/")
    assert "masthead" in resp.text
    assert "site-heading" in resp.text


@pytest.mark.unit
async def test_post_list_empty_state(mock_client):
    resp = await mock_client.get("/posts/")
    assert "No posts yet" in resp.text


@pytest.mark.unit
async def test_post_list_links_clean_blog_css(mock_client):
    resp = await mock_client.get("/posts/")
    assert "clean-blog.css" in resp.text


@pytest.mark.unit
async def test_post_list_links_clean_blog_js(mock_client):
    resp = await mock_client.get("/posts/")
    assert "clean-blog.js" in resp.text


@pytest.mark.unit
async def test_post_list_has_footer_copyright(mock_client):
    resp = await mock_client.get("/posts/")
    assert "BulliExplorer" in resp.text
    assert ("&copy;" in resp.text) or ("©" in resp.text)


# ---------------------------------------------------------------------------
# Post detail — unknown slug → 404
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_detail_unknown_slug_returns_404(mock_client):
    """slug not in DB → session returns None → 404."""
    resp = await mock_client.get("/posts/no-such-post")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Post detail — renders correctly with a mock post
# ---------------------------------------------------------------------------


class _FakePost:
    slug = "test-post"
    title = "A Gravel Day in the Black Forest"
    summary = "Single-track, mud, and a very questionable coffee stop."
    published_date = __import__("datetime").date(2025, 8, 24)
    cover_image = None
    tags = "gravel,adventure"
    body_html = "<p>Placeholder body.</p>"
    is_draft = False


async def _session_with_post():
    """Dependency override: session that returns a single fake post."""
    yield _make_mock_session(scalar_result=_FakePost(), scalars_result=[_FakePost()])


@pytest.fixture
async def client_with_post():
    application = create_app()
    application.dependency_overrides[get_db_session] = _session_with_post
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.unit
async def test_post_detail_returns_200(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert resp.status_code == 200


@pytest.mark.unit
async def test_post_detail_shows_title(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "A Gravel Day in the Black Forest" in resp.text


@pytest.mark.unit
async def test_post_detail_shows_summary_subheading(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "subheading" in resp.text
    assert "Single-track" in resp.text


@pytest.mark.unit
async def test_post_detail_shows_author(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "Sven" in resp.text


@pytest.mark.unit
async def test_post_detail_renders_body(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "Placeholder body" in resp.text


@pytest.mark.unit
async def test_post_detail_shows_tags(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "gravel" in resp.text
    assert "adventure" in resp.text


@pytest.mark.unit
async def test_post_detail_has_back_link(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "Back to all posts" in resp.text


@pytest.mark.unit
async def test_post_detail_links_clean_blog_css(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "clean-blog.css" in resp.text
