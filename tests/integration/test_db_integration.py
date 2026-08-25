"""Integration tests for app/core/db.py — requires the PostGIS container.

Run with: docker compose up -d && uv run pytest tests/integration/

Verifies:
- The engine can open a real connection to the DB.
- A SELECT 1 executes successfully via get_db_session().
- The app starts and shuts down cleanly with the real DB (lifespan test).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_db_session, init_engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REAL_DB_URL = get_settings().database_url


@pytest.fixture(autouse=True)
async def reset_engine():
    """Ensure singletons are clean before and after each integration test."""
    db_module._engine = None  # noqa: SLF001
    db_module._async_session_factory = None  # noqa: SLF001
    yield
    await dispose_engine()
    db_module._async_session_factory = None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_select_one_via_session(request):
    """A SELECT 1 via get_db_session() returns 1 against the real DB."""
    init_engine(REAL_DB_URL)
    async for session in get_db_session():
        result = await session.execute(text("SELECT 1"))
        value = result.scalar()
        assert value == 1


@pytest.mark.integration
async def test_app_lifespan_starts_and_stops():
    """The FastAPI lifespan wires DB correctly — app starts and /health responds."""
    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
    # After the async context exits, lifespan shutdown has run — engine disposed.
    assert db_module._engine is None  # noqa: SLF001
