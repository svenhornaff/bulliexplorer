"""Integration tests for app/services/post_sync.py — requires PostGIS container.

Run with: docker compose up -d && uv run pytest tests/integration/

Verifies:
- A fixture post round-trips from Markdown → DB → query correctly.
- Re-running sync with unchanged files is a no-op (no extra rows, counts).
- Deleting a file and re-running sync removes the corresponding DB row.
- A directory containing one valid and one invalid file skips the bad one
  but still upserts the good one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.models.post import Post
from app.services.post_sync import sync_posts

REAL_DB_URL = get_settings().database_url

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def clean_db_engine():
    """Fresh engine + clean posts table for every integration test."""
    db_module._engine = None  # noqa: SLF001
    db_module._async_session_factory = None  # noqa: SLF001
    init_engine(REAL_DB_URL)

    # Wipe posts table before each test so tests are independent.
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


VALID_POST = """\
---
title: Test Ride
slug: test-ride
date: 2025-06-01
summary: A test summary.
tags:
  - gravel
  - test
draft: false
---

# Test Ride

Some **bold** content.
"""

VALID_POST_2 = """\
---
title: Second Ride
slug: second-ride
date: 2025-07-01
---

Second post body.
"""

INVALID_POST = """\
---
slug: missing-title
date: 2025-01-01
---

No title here.
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_round_trips_into_db(tmp_path):
    """A valid Markdown file is upserted correctly and queryable from the DB."""
    _write_md(tmp_path, "test-ride.md", VALID_POST)

    factory = get_session_factory()
    async with factory() as session:
        counts = await sync_posts(tmp_path, session)
        await session.commit()

    assert counts["upserted"] == 1
    assert counts["deleted"] == 0
    assert counts["skipped"] == 0

    # Verify the row in DB.
    async with factory() as session:
        result = await session.execute(select(Post).where(Post.slug == "test-ride"))
        post = result.scalar_one_or_none()

    assert post is not None
    assert post.title == "Test Ride"
    assert post.summary == "A test summary."
    assert post.published_date.isoformat() == "2025-06-01"
    assert post.tags == "gravel,test"
    assert post.is_draft is False
    # body_html removed in Phase 5 — verify raw Markdown is preserved instead.
    assert "# Test Ride" in post.body_markdown
    assert "**bold**" in post.body_markdown


@pytest.mark.integration
async def test_sync_is_idempotent(tmp_path):
    """Running sync twice with the same files produces no extra rows."""
    _write_md(tmp_path, "test-ride.md", VALID_POST)

    factory = get_session_factory()

    # First sync.
    async with factory() as session:
        counts1 = await sync_posts(tmp_path, session)
        await session.commit()

    # Second sync — identical files.
    async with factory() as session:
        counts2 = await sync_posts(tmp_path, session)
        await session.commit()

    assert counts1["upserted"] == 1
    assert counts2["upserted"] == 1  # still counted as processed, but no DB write

    # Only one row must exist.
    async with factory() as session:
        result = await session.execute(select(Post))
        rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].slug == "test-ride"


@pytest.mark.integration
async def test_deleted_file_removes_db_row(tmp_path):
    """Removing a Markdown file and re-syncing deletes the DB row."""
    md_file = _write_md(tmp_path, "test-ride.md", VALID_POST)

    factory = get_session_factory()

    # Sync to insert.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    # Confirm it's there.
    async with factory() as session:
        result = await session.execute(select(Post).where(Post.slug == "test-ride"))
        assert result.scalar_one_or_none() is not None

    # Delete the file.
    md_file.unlink()

    # Re-sync — should delete the row.
    async with factory() as session:
        counts = await sync_posts(tmp_path, session)
        await session.commit()

    assert counts["deleted"] == 1
    assert counts["upserted"] == 0

    async with factory() as session:
        result = await session.execute(select(Post).where(Post.slug == "test-ride"))
        assert result.scalar_one_or_none() is None


@pytest.mark.integration
async def test_invalid_file_skipped_valid_file_upserted(tmp_path):
    """One broken file is skipped; the valid file is still upserted."""
    _write_md(tmp_path, "good.md", VALID_POST)
    _write_md(tmp_path, "bad.md", INVALID_POST)

    factory = get_session_factory()
    async with factory() as session:
        counts = await sync_posts(tmp_path, session)
        await session.commit()

    assert counts["upserted"] == 1
    assert counts["skipped"] == 1

    async with factory() as session:
        result = await session.execute(select(Post))
        rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].slug == "test-ride"


@pytest.mark.integration
async def test_updated_post_is_written_to_db(tmp_path):
    """Modifying a post's title in the file causes a DB update on next sync."""
    md_file = _write_md(tmp_path, "test-ride.md", VALID_POST)

    factory = get_session_factory()

    # Initial sync.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    # Modify the title in the file.
    updated = VALID_POST.replace("title: Test Ride", "title: Updated Ride")
    md_file.write_text(updated, encoding="utf-8")

    # Re-sync.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(Post).where(Post.slug == "test-ride"))
        post = result.scalar_one_or_none()

    assert post is not None
    assert post.title == "Updated Ride"


@pytest.mark.integration
async def test_multiple_posts_all_upserted(tmp_path):
    """Multiple valid files are all inserted in one sync run."""
    _write_md(tmp_path, "test-ride.md", VALID_POST)
    _write_md(tmp_path, "second-ride.md", VALID_POST_2)

    factory = get_session_factory()
    async with factory() as session:
        counts = await sync_posts(tmp_path, session)
        await session.commit()

    assert counts["upserted"] == 2
    assert counts["skipped"] == 0

    async with factory() as session:
        result = await session.execute(select(Post))
        rows = result.scalars().all()

    slugs = {r.slug for r in rows}
    assert slugs == {"test-ride", "second-ride"}
