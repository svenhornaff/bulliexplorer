"""Integration tests for app/main.py's lifespan — requires PostGIS container.

Covers docs/dev/fix_startup_blocking_amenity_sync.md Phase 2's "done when"
criteria: startup must complete (and the app must be usable) without
waiting for amenity discovery, even when that discovery is arbitrarily
slow, and shutdown must cleanly cancel any still-running background task
rather than let it race a disposed DB engine.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy import text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.main import lifespan

REAL_DB_URL = get_settings().database_url

_CONTENT_DIR = Path(__file__).resolve().parents[2] / "content" / "posts"
_FIXTURE_SLUG = "lifespan-amenity-test-post"
_FIXTURE_FILE = _CONTENT_DIR / f"{_FIXTURE_SLUG}.md"


_FIXTURE_MD = """\
---
title: Lifespan Amenity Test Post
slug: lifespan-amenity-test-post
date: 2025-09-01
summary: Written to verify startup doesn't block on amenity discovery.
draft: false
---

Body of the lifespan amenity test post.
"""


@pytest.fixture(autouse=True)
async def clean_db_and_fixture():
    _FIXTURE_FILE.unlink(missing_ok=True)

    db_module._engine = None  # noqa: SLF001
    db_module._async_session_factory = None  # noqa: SLF001
    init_engine(REAL_DB_URL)

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("DELETE FROM nearby_amenities"))
        await session.execute(text("DELETE FROM points_of_interest"))
        await session.execute(text("DELETE FROM routes"))
        await session.execute(text("DELETE FROM posts"))
        await session.commit()

    yield

    _FIXTURE_FILE.unlink(missing_ok=True)
    async with factory() as session:
        await session.execute(text("DELETE FROM nearby_amenities"))
        await session.execute(text("DELETE FROM points_of_interest"))
        await session.execute(text("DELETE FROM routes"))
        await session.execute(
            text("DELETE FROM posts WHERE slug = :slug"),
            {"slug": _FIXTURE_SLUG},
        )
        await session.commit()

    await dispose_engine()
    db_module._async_session_factory = None  # noqa: SLF001


@pytest.mark.integration
async def test_lifespan_completes_without_waiting_for_amenity_discovery():
    """Startup (the lifespan's pre-yield phase) must complete quickly
    even when amenity discovery for a synced route would take
    arbitrarily long \u2014 it must run as a background task, not inline.

    A post with no route (this fixture) doesn't schedule any amenity
    task at all, so instead this test forces enable_amenity_discovery on
    and confirms the lifespan doesn't hang even though there is nothing
    to discover for \u2014 the more meaningful assertion is
    test_lifespan_background_task_is_cancelled_on_shutdown below, which
    proves an in-flight task is actually tracked and interruptible.
    """
    _FIXTURE_FILE.write_text(_FIXTURE_MD, encoding="utf-8")

    settings = get_settings()
    settings.enable_amenity_discovery = True
    try:
        app = FastAPI()
        async with asyncio.timeout(10):
            async with lifespan(app):
                # Startup (pre-yield) completed within the timeout —
                # the actual proof that it didn't block on anything slow.
                pass
    finally:
        settings.enable_amenity_discovery = False


@pytest.mark.integration
async def test_lifespan_background_task_is_cancelled_on_shutdown():
    """A still-running background amenity-sync task must be cancelled
    cleanly on shutdown, before the DB engine is disposed \u2014 not left to
    race a disposed engine or raise an unhandled exception.
    """
    _FIXTURE_FILE.write_text(_FIXTURE_MD, encoding="utf-8")

    settings = get_settings()
    settings.enable_amenity_discovery = True

    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_sync_amenities_for_routes(session_factory, route_ids):
        started.set()
        await release.wait()

    try:
        app = FastAPI()
        with patch(
            "app.services.background_sync.sync_amenities_for_routes",
            side_effect=_slow_sync_amenities_for_routes,
        ):
            # No route in this fixture post means amenity_route_ids is
            # empty and schedule_amenity_sync() schedules nothing — patch
            # sync_posts's result directly so this test exercises the
            # shutdown-cancellation path regardless of fixture content.
            from app.services.post_sync import SyncResult

            with patch(
                "app.main.sync_posts",
                new=AsyncMock(return_value=SyncResult(upserted=1, amenity_route_ids=[1])),
            ):
                async with lifespan(app):
                    await asyncio.wait_for(started.wait(), timeout=5)
                    task = next(iter(app.state.amenity_sync_tasks))
                    assert not task.done()
                # Lifespan shutdown (the code after `yield`) has now run —
                # cancel_amenity_sync_tasks() should have cancelled and
                # awaited the task to completion.
                assert task.done()
                assert task.cancelled()
    finally:
        settings.enable_amenity_discovery = False
        release.set()
