"""Integration tests for the startup-sync advisory lock (F5,
docs/dev/review_17SEP2026.md) — requires the PostGIS container.

Dockerfile runs `uvicorn --workers 2`; FastAPI's lifespan runs once per
worker process, not once per deploy, so without a lock, content sync would
run twice on every deploy. `try_acquire_advisory_lock`/`release_advisory_lock`
(app/core/db.py) wrap that sync in a non-blocking `pg_try_advisory_lock` so
only one worker's lifespan actually performs it.

Covers:
- The low-level lock helpers' actual Postgres semantics (acquire/blocked/
  release/reacquire).
- The lifespan's use of them: sync_posts is skipped entirely when the lock
  is already held elsewhere, and the lock is released (not leaked) after a
  successful sync so a later acquire attempt succeeds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import (
    dispose_engine,
    get_session_factory,
    init_engine,
    release_advisory_lock,
    try_acquire_advisory_lock,
)
from app.main import _STARTUP_SYNC_LOCK_KEY, lifespan
from app.services.post_sync import SyncResult

REAL_DB_URL = get_settings().database_url


@pytest.fixture(autouse=True)
async def reset_engine():
    """Ensure singletons are clean before and after each integration test."""
    db_module._engine = None  # noqa: SLF001
    db_module._async_session_factory = None  # noqa: SLF001
    init_engine(REAL_DB_URL)
    yield
    await dispose_engine()
    db_module._async_session_factory = None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Low-level lock helpers — real Postgres advisory-lock semantics
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_advisory_lock_blocks_second_session_until_released():
    """A session-scoped advisory lock held by one connection is reported
    as unavailable (not blocking/hanging — pg_try_advisory_lock is
    non-blocking) to a second connection, then becomes available again
    once the first releases it.
    """
    factory = get_session_factory()
    key = _STARTUP_SYNC_LOCK_KEY + 1  # distinct key, avoids clashing with other tests

    async with factory() as session_a, factory() as session_b:
        acquired_a = await try_acquire_advisory_lock(session_a, key)
        assert acquired_a is True

        # Second session, second underlying connection — sees the lock
        # already held and gets False back immediately, not a hang.
        acquired_b = await try_acquire_advisory_lock(session_b, key)
        assert acquired_b is False

        await release_advisory_lock(session_a, key)

        acquired_b_after_release = await try_acquire_advisory_lock(session_b, key)
        assert acquired_b_after_release is True

        await release_advisory_lock(session_b, key)


# ---------------------------------------------------------------------------
# Lifespan-level behaviour
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_lifespan_skips_sync_posts_when_lock_already_held():
    """When the startup-sync lock is already held by another connection
    (simulating a second uvicorn worker whose lifespan got there first),
    this lifespan's own sync_posts call must be skipped entirely — not
    run a second time racing the first worker's upserts.
    """
    factory = get_session_factory()
    async with factory() as holder_session:
        acquired = await try_acquire_advisory_lock(holder_session, _STARTUP_SYNC_LOCK_KEY)
        assert acquired is True
        try:
            with patch("app.main.sync_posts", new=AsyncMock()) as mock_sync_posts:
                app = FastAPI()
                async with lifespan(app):
                    pass
                mock_sync_posts.assert_not_called()
        finally:
            await release_advisory_lock(holder_session, _STARTUP_SYNC_LOCK_KEY)


@pytest.mark.integration
async def test_lifespan_releases_lock_after_sync_completes():
    """After a lifespan that won the lock finishes its startup sync, the
    lock must be released — not leaked — so the next deploy's (or the
    next worker's) attempt to acquire it succeeds.
    """
    with patch("app.main.sync_posts", new=AsyncMock(return_value=SyncResult())):
        app = FastAPI()
        async with lifespan(app):
            pass

    factory = get_session_factory()
    async with factory() as session:
        acquired = await try_acquire_advisory_lock(session, _STARTUP_SYNC_LOCK_KEY)
        assert acquired is True  # not leaked by the previous lifespan run
        await release_advisory_lock(session, _STARTUP_SYNC_LOCK_KEY)
