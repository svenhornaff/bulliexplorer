"""Integration tests for Phase 4 routes — requires PostGIS container.

Covers every "Done when" criterion from the spec:
- Synced fixture post appears in GET /posts/ list
- GET /posts/{slug} returns 200 with the title in the body
- Unknown slug returns 404
- Draft post returns 404 when APP_ENV=production
- Draft post returns 200 when APP_ENV=development
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.services.post_sync import sync_posts

REAL_DB_URL = get_settings().database_url

PUBLISHED_POST = """\
---
title: The Kinzig Valley Loop
slug: kinzig-valley-loop
date: 2025-08-10
summary: A perfect gravel day in the Black Forest.
tags:
  - gravel
  - black-forest
draft: false
---

# The Kinzig Valley Loop

Sixty kilometres of singletrack and forest road.
"""

DRAFT_POST = """\
---
title: Unreleased Adventure
slug: unreleased-adventure
date: 2025-09-01
draft: true
---

Draft content not yet published.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def clean_db():
    """Fresh engine + clean posts table before every integration test."""
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

    await dispose_engine()
    db_module._async_session_factory = None  # noqa: SLF001


def _write_md(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


async def _sync(content_dir: Path) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await sync_posts(content_dir, session)
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_published_post_appears_in_list(tmp_path):
    """Synced published post is visible in GET /posts/."""
    _write_md(tmp_path, "kinzig.md", PUBLISHED_POST)
    await _sync(tmp_path)

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/")

    assert resp.status_code == 200
    assert "The Kinzig Valley Loop" in resp.text


@pytest.mark.integration
async def test_post_detail_returns_200_with_title(tmp_path):
    """GET /posts/{slug} returns 200 and the post title in the body."""
    _write_md(tmp_path, "kinzig.md", PUBLISHED_POST)
    await _sync(tmp_path)

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/kinzig-valley-loop")

    assert resp.status_code == 200
    assert "The Kinzig Valley Loop" in resp.text
    assert "A perfect gravel day" in resp.text


@pytest.mark.integration
async def test_unknown_slug_returns_404(tmp_path):
    """An unrecognised slug always returns 404."""
    _write_md(tmp_path, "kinzig.md", PUBLISHED_POST)
    await _sync(tmp_path)

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/does-not-exist")

    assert resp.status_code == 404


@pytest.mark.integration
async def test_draft_post_404_in_production(tmp_path, monkeypatch):
    """Draft post returns 404 when APP_ENV=production."""
    monkeypatch.setenv("APP_ENV", "production")

    _write_md(tmp_path, "draft.md", DRAFT_POST)
    await _sync(tmp_path)

    # Re-create app after monkeypatching env so Settings picks up the change.
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/unreleased-adventure")

    assert resp.status_code == 404

    # Restore settings cache
    get_settings.cache_clear()


@pytest.mark.integration
async def test_draft_post_visible_in_development(tmp_path, monkeypatch):
    """Draft post returns 200 when APP_ENV=development."""
    monkeypatch.setenv("APP_ENV", "development")

    _write_md(tmp_path, "draft.md", DRAFT_POST)
    await _sync(tmp_path)

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/unreleased-adventure")

    assert resp.status_code == 200
    assert "Unreleased Adventure" in resp.text

    get_settings.cache_clear()


@pytest.mark.integration
async def test_post_list_excludes_drafts(tmp_path):
    """Draft posts do not appear in the public list."""
    _write_md(tmp_path, "kinzig.md", PUBLISHED_POST)
    _write_md(tmp_path, "draft.md", DRAFT_POST)
    await _sync(tmp_path)

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/")

    assert resp.status_code == 200
    assert "The Kinzig Valley Loop" in resp.text
    assert "Unreleased Adventure" not in resp.text


@pytest.mark.integration
async def test_lifespan_runs_without_error_on_empty_content_dir():
    """App starts and serves /health even when content/posts/ is empty.

    This verifies the lifespan sync path completes without raising —
    the sync service gracefully handles a directory with no .md files.
    """
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
