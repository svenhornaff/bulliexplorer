"""Home route tests — / redirects to /posts/."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Result

from app.core.db import get_db_session
from app.main import create_app

# ---------------------------------------------------------------------------
# Mock DB helpers (same pattern as test_templates.py)
# ---------------------------------------------------------------------------


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


@pytest.fixture
async def home_client():
    """App with DB overridden to empty — no real DB needed."""
    application = create_app()
    application.dependency_overrides[get_db_session] = _empty_db
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_home_redirects_to_posts(home_client):
    """GET / returns a 302 redirect to /posts/."""
    resp = await home_client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/posts/"


@pytest.mark.unit
async def test_home_followed_returns_200(home_client):
    """Following the redirect delivers a 200 post-list page."""
    resp = await home_client.get("/", follow_redirects=True)
    assert resp.status_code == 200


@pytest.mark.unit
async def test_home_followed_contains_title(home_client):
    resp = await home_client.get("/", follow_redirects=True)
    assert "BulliExplorer" in resp.text


@pytest.mark.unit
async def test_home_followed_empty_state(home_client):
    resp = await home_client.get("/", follow_redirects=True)
    assert "No posts yet" in resp.text
