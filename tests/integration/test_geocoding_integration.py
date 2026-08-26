"""Integration tests for Phase 3 geocoding — requires PostGIS container.

Covers all three Phase 3 "Done when" criteria:

1. A fixture POI with only ``place_query`` set resolves to correct coordinates
   in the DB (Nominatim mocked — real network not needed to verify the path).
2. A fixture POI with manual ``lat``/``lng`` is *not* geocoded — the network
   call never happens (verified by asserting the mock is never awaited).
3. A deliberately bad ``place_query`` fails gracefully — the POI is skipped,
   the rest of the sync continues unaffected.

Run with: docker compose up -d && uv run pytest tests/integration/ -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from geoalchemy2.shape import to_shape
from sqlalchemy import select, text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.services.post_sync import sync_posts

REAL_DB_URL = get_settings().database_url

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_md(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# DB cleanup fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def clean_db():
    """Fresh engine + clean tables before every integration test."""
    db_module._engine = None  # noqa: SLF001 — reset singleton for test isolation
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


# ---------------------------------------------------------------------------
# Done-when criterion 1:
# A fixture POI with only place_query resolves to correct coordinates.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_place_query_poi_geocodes_to_correct_coordinates(tmp_path):
    """A POI with only place_query set resolves to the geocoded coordinates.

    ``_geocode`` is mocked to return a known (lat, lon) pair.  The test
    verifies that those coordinates land in the DB correctly (correct
    lon/lat ordering for PostGIS, correct geometry type).
    """
    _write_md(
        tmp_path,
        "geocode-post.md",
        """\
---
title: Geocode Post
slug: geocode-post
date: 2025-06-01
points_of_interest:
  - name: Café Sonnenberg
    category: restaurant
    place_query: "Café Sonnenberg, Freiburg"
---

Body.
""",
    )

    # Mock Nominatim — returns (lat, lon) as a 2-tuple.
    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        mock_gc.return_value = (48.0054, 7.8221)  # (lat, lon)

        factory = get_session_factory()
        async with factory() as session:
            counts = await sync_posts(tmp_path, session)
            await session.commit()

    assert counts["upserted"] == 1
    assert counts["skipped"] == 0

    # Geocode was called exactly once with the right query.
    mock_gc.assert_awaited_once()
    called_query = mock_gc.await_args[0][0]
    assert called_query == "Café Sonnenberg, Freiburg"

    # Verify the DB row has the correct geometry.
    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "geocode-post"))).scalar_one()
        pois = (
            (await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))).scalars().all()
        )

    assert len(pois) == 1
    poi = pois[0]
    assert poi.name == "Café Sonnenberg"
    assert poi.category == "restaurant"

    # PostGIS stores (lon, lat) — verify the correct swap happened.
    point = to_shape(poi.location)
    assert point.x == pytest.approx(7.8221)  # lon → x
    assert point.y == pytest.approx(48.0054)  # lat → y


# ---------------------------------------------------------------------------
# Done-when criterion 2:
# A POI with manual lat/lng is never geocoded — zero network calls.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_manual_coords_poi_never_triggers_network_call(tmp_path):
    """A POI with explicit lat/lng does not call _geocode at all.

    This is the hard boundary: the network call *never* happens when manual
    coordinates are present.  Verified by asserting the mock is not awaited.
    """
    _write_md(
        tmp_path,
        "manual-post.md",
        """\
---
title: Manual Coords Post
slug: manual-post
date: 2025-06-01
points_of_interest:
  - name: Wild Campsite
    category: campsite
    lat: 48.02
    lng: 8.05
    notes: No fire allowed.
---

Body.
""",
    )

    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        factory = get_session_factory()
        async with factory() as session:
            counts = await sync_posts(tmp_path, session)
            await session.commit()

    assert counts["upserted"] == 1

    # The geocoding function must never have been called.
    mock_gc.assert_not_awaited()

    # Verify the DB row has the manually specified coordinates.
    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "manual-post"))).scalar_one()
        pois = (
            (await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))).scalars().all()
        )

    assert len(pois) == 1
    point = to_shape(pois[0].location)
    assert point.x == pytest.approx(8.05)  # lng → x
    assert point.y == pytest.approx(48.02)  # lat → y


# ---------------------------------------------------------------------------
# Done-when criterion 3:
# A bad place_query fails gracefully — POI skipped, sync continues.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_bad_place_query_skipped_sync_continues(tmp_path):
    """A place_query that resolves to nothing skips that POI without aborting.

    The sync continues and the post itself is written.  A second POI with
    manual coordinates is written correctly, proving the batch doesn't stop.
    """
    _write_md(
        tmp_path,
        "bad-query-post.md",
        """\
---
title: Bad Query Post
slug: bad-query-post
date: 2025-06-01
points_of_interest:
  - name: Nonsense Place
    category: other
    place_query: "asdkfjasldkfj"
  - name: Good Campsite
    category: campsite
    lat: 48.0
    lng: 8.0
---

Body.
""",
    )

    # _geocode returns None for the bad query (Nominatim found nothing).
    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        mock_gc.return_value = None  # simulates empty Nominatim result

        factory = get_session_factory()
        async with factory() as session:
            counts = await sync_posts(tmp_path, session)
            await session.commit()

    # Post is upserted despite the bad POI.
    assert counts["upserted"] == 1
    assert counts["skipped"] == 0  # post-level skip, not POI-level

    # Geocoding was attempted for the bad query.
    mock_gc.assert_awaited_once()

    # Only the good POI (with manual coords) ended up in the DB.
    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "bad-query-post"))).scalar_one()
        pois = (
            (await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))).scalars().all()
        )

    assert len(pois) == 1
    assert pois[0].name == "Good Campsite"


# ---------------------------------------------------------------------------
# Extra: mixed POIs — both geocoded and manual in one sync run
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_mixed_poi_types_all_synced_correctly(tmp_path):
    """One post with both manual-coord and geocoded POIs syncs correctly."""
    _write_md(
        tmp_path,
        "mixed-post.md",
        """\
---
title: Mixed Post
slug: mixed-post
date: 2025-06-01
points_of_interest:
  - name: Wild Campsite
    category: campsite
    lat: 48.02
    lng: 8.01
  - name: Gasthaus Ritter
    category: restaurant
    place_query: "Gasthaus Ritter, Wolfach"
---

Body.
""",
    )

    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        mock_gc.return_value = (48.1, 8.2)  # geocoded result for Gasthaus Ritter

        factory = get_session_factory()
        async with factory() as session:
            await sync_posts(tmp_path, session)
            await session.commit()

    # Geocode called once (for the place_query POI only).
    mock_gc.assert_awaited_once()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "mixed-post"))).scalar_one()
        pois = (
            (await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))).scalars().all()
        )

    assert len(pois) == 2
    names = {p.name for p in pois}
    assert names == {"Wild Campsite", "Gasthaus Ritter"}

    # Check geocoded POI got the mock coordinates.
    gasthaus = next(p for p in pois if p.name == "Gasthaus Ritter")
    g_point = to_shape(gasthaus.location)
    assert g_point.x == pytest.approx(8.2)  # lon
    assert g_point.y == pytest.approx(48.1)  # lat
