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

    assert counts.upserted == 1
    assert counts.deleted == 0
    assert counts.skipped == 0

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

    assert counts1.upserted == 1
    assert counts2.upserted == 1  # still counted as processed, but no DB write

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

    assert counts.deleted == 1
    assert counts.upserted == 0

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

    assert counts.upserted == 1
    assert counts.skipped == 1

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

    assert counts.upserted == 2
    assert counts.skipped == 0

    async with factory() as session:
        result = await session.execute(select(Post))
        rows = result.scalars().all()

    slugs = {r.slug for r in rows}
    assert slugs == {"test-ride", "second-ride"}


# ---------------------------------------------------------------------------
# Cover image processing (docs/dev/fix_lcp_image_and_static_cache.md
# Finding 1) — the full sync_posts() → DB round-trip, real Postgres
# columns, not just resolve_cover_image()'s own unit-tested logic in
# isolation. httpx and boto3 are still mocked (AGENTS.md: no real R2 in
# tests) — this test's job is proving the DB columns/wiring are correct
# end to end, not re-proving resolve_cover_image()'s own behaviour.
# ---------------------------------------------------------------------------

COVER_IMAGE_POST = """\
---
title: Cover Image Ride
slug: cover-image-ride
date: 2025-08-01
cover_image: https://pub-example.r2.dev/media/cover.jpg
---

A post with a real cover image.
"""


def _make_jpeg_bytes() -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGB", (2000, 1000), color=(60, 90, 130))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.mark.integration
async def test_sync_posts_processes_cover_image_into_real_db_columns(tmp_path):
    """A post with a cover_image gets it fetched, resized/converted, and
    the real Postgres row ends up with cover_image (the served/processed
    URL), cover_image_source_url (the raw frontmatter value), and real
    width/height — not just what resolve_cover_image() returns in
    isolation (already covered by tests/unit/test_cover_image_sync.py).
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    _write_md(tmp_path, "cover-image-ride.md", COVER_IMAGE_POST)

    fake_response = MagicMock()
    fake_response.content = _make_jpeg_bytes()
    fake_response.raise_for_status = MagicMock()
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.aclose = AsyncMock()

    s3_client = MagicMock()

    factory = get_session_factory()
    async with factory() as session:
        with patch("app.services.cover_image_sync.httpx.AsyncClient", return_value=fake_client):
            counts = await sync_posts(
                tmp_path,
                session,
                r2_public_url="https://pub-example.r2.dev",
                s3_client=s3_client,
                s3_bucket="bulliexplorer",
            )
        await session.commit()

    assert counts.upserted == 1
    s3_client.put_object.assert_called_once()

    async with factory() as session:
        result = await session.execute(select(Post).where(Post.slug == "cover-image-ride"))
        post = result.scalar_one_or_none()

    assert post is not None
    assert post.cover_image_source_url == "https://pub-example.r2.dev/media/cover.jpg"
    assert post.cover_image is not None
    assert post.cover_image.startswith("https://pub-example.r2.dev/media/processed/cover-image-ride-")
    assert post.cover_image_width == 1800  # MAX_COVER_WIDTH
    assert post.cover_image_height == 900


@pytest.mark.integration
async def test_sync_posts_reruns_skip_unchanged_cover_image(tmp_path):
    """Re-running sync_posts with the same file must not re-fetch/re-
    upload the cover image — the idempotency check works through the
    real DB round-trip, not just resolve_cover_image() called once.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    _write_md(tmp_path, "cover-image-ride.md", COVER_IMAGE_POST)

    fake_response = MagicMock()
    fake_response.content = _make_jpeg_bytes()
    fake_response.raise_for_status = MagicMock()
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.aclose = AsyncMock()
    s3_client = MagicMock()

    factory = get_session_factory()
    with patch("app.services.cover_image_sync.httpx.AsyncClient", return_value=fake_client):
        async with factory() as session:
            await sync_posts(tmp_path, session, r2_public_url="https://pub-example.r2.dev", s3_client=s3_client)
            await session.commit()

        # Second sync, same unchanged file — must not fetch/upload again.
        async with factory() as session:
            await sync_posts(tmp_path, session, r2_public_url="https://pub-example.r2.dev", s3_client=s3_client)
            await session.commit()

    assert fake_client.get.await_count == 1, "cover image must only be fetched once across two identical syncs"
    assert s3_client.put_object.call_count == 1
