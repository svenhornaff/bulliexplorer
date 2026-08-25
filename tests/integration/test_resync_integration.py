"""Integration tests for POST /internal/resync — requires PostGIS container.

Verifies the full path: correct token → sync_posts runs against the real DB
→ a new post becomes visible at GET /posts/{slug} without a restart.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine

REAL_DB_URL = get_settings().database_url
RESYNC_TOKEN = get_settings().resync_token

# Fixture post written into the real content/posts/ directory so the resync
# route (which uses BASE_DIR / "content" / "posts") can find it.
_CONTENT_DIR = Path(__file__).resolve().parents[2] / "content" / "posts"
_FIXTURE_SLUG = "resync-integration-test-post"
_FIXTURE_FILE = _CONTENT_DIR / f"{_FIXTURE_SLUG}.md"
_FIXTURE_CONTENT = """\
---
title: Resync Integration Test Post
slug: resync-integration-test-post
date: 2025-09-01
summary: Written to verify the resync endpoint works end to end.
draft: false
---

Body of the resync integration test post.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def clean_db_and_fixture():
    """Clean posts table and ensure no leftover fixture file before/after."""
    # Remove stale fixture file if a prior test run left it.
    _FIXTURE_FILE.unlink(missing_ok=True)

    db_module._engine = None  # noqa: SLF001
    db_module._async_session_factory = None  # noqa: SLF001
    init_engine(REAL_DB_URL)

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("DELETE FROM points_of_interest"))
        await session.execute(text("DELETE FROM routes"))
        await session.execute(text("DELETE FROM posts"))
        await session.commit()

    yield

    # Clean up fixture file and its DB row.
    _FIXTURE_FILE.unlink(missing_ok=True)
    async with factory() as session:
        await session.execute(text("DELETE FROM points_of_interest"))
        await session.execute(text("DELETE FROM routes"))
        await session.execute(
            text("DELETE FROM posts WHERE slug = :slug"),
            {"slug": _FIXTURE_SLUG},
        )
        await session.commit()

    await dispose_engine()
    db_module._async_session_factory = None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_resync_endpoint_syncs_new_post():
    """New .md in content/posts/ + POST /internal/resync makes it live."""
    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Post should not exist yet (DB was cleared by fixture).
        resp = await client.get(f"/posts/{_FIXTURE_SLUG}")
        assert resp.status_code == 404

        # Write the fixture file into content/posts/.
        _FIXTURE_FILE.write_text(_FIXTURE_CONTENT, encoding="utf-8")

        # Trigger resync — no container restart.
        resync_resp = await client.post(
            "/internal/resync",
            headers={"X-Resync-Token": RESYNC_TOKEN},
        )
        assert resync_resp.status_code == 200
        body = resync_resp.json()
        assert body["status"] == "ok"
        assert body["upserted"] >= 1

        # Post is now live.
        resp2 = await client.get(f"/posts/{_FIXTURE_SLUG}")
        assert resp2.status_code == 200
        assert "Resync Integration Test Post" in resp2.text


@pytest.mark.integration
async def test_resync_wrong_token_rejected():
    """Wrong token returns 401 even when DB is available."""
    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/resync",
            headers={"X-Resync-Token": "definitely-wrong"},
        )
    assert resp.status_code == 401
