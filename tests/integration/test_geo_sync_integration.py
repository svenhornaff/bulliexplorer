"""Integration tests for Phase 2 geo sync — requires PostGIS container.

Covers all Phase 2 "Done when" criteria:
1. Fixture post with GPX + manual-coord POIs syncs correctly; geometry
   round-trips through PostGIS correctly.
2. Computed stats stored in DB match values calculated from the same GPX.
3. Posts with no route/POIs still sync unaffected — explicit regression test.
4. A post that had a route, then has it removed, causes the Route row to
   be deleted (not orphaned).

Run with: docker compose up -d && uv run pytest tests/integration/ -v
"""

from __future__ import annotations

from pathlib import Path

import gpxpy
import pytest
from geoalchemy2.shape import to_shape
from sqlalchemy import select, text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.models.route import Route
from app.services.post_sync import sync_posts

REAL_DB_URL = get_settings().database_url

# ---------------------------------------------------------------------------
# Fixture GPX content — track with 3 segments for realistic stats testing.
#
# Elevation profile:
#   Point 1: (8.0, 48.0), ele=200m  — start
#   Point 2: (8.05, 48.05), ele=300m — climb +100m
#   Point 3: (8.1, 48.0), ele=250m  — descent -50m
# Duration: 08:00 → 09:00 = 60 minutes
# ---------------------------------------------------------------------------
FIXTURE_GPX = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="bulliexplorer-test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Integration Test Route</name>
    <trkseg>
      <trkpt lat="48.0" lon="8.0">
        <ele>200.0</ele>
        <time>2025-06-01T08:00:00Z</time>
      </trkpt>
      <trkpt lat="48.05" lon="8.05">
        <ele>300.0</ele>
        <time>2025-06-01T08:30:00Z</time>
      </trkpt>
      <trkpt lat="48.0" lon="8.1">
        <ele>250.0</ele>
        <time>2025-06-01T09:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_md(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def _write_gpx(directory: Path, name: str, content: str = FIXTURE_GPX) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def _gpx_expected_stats(gpx_content: str) -> dict[str, float | None]:
    """Compute expected stats from GPX text using gpxpy directly.

    This is the "independent calculation" used to validate what's stored in DB.
    """
    gpx = gpxpy.parse(gpx_content)
    distance_km = (gpx.length_2d() or 0.0) / 1000.0
    uphill, downhill = gpx.get_uphill_downhill()
    duration_s = gpx.get_duration()
    return {
        "distance_km": distance_km,
        "elevation_gain_m": uphill or 0.0,
        "elevation_loss_m": downhill or 0.0,
        "duration_minutes": duration_s / 60.0 if duration_s is not None else None,
    }


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
# Phase 2 Done-when criterion 1 & 2:
# A fixture post with a GPX file + manual-coord POIs syncs correctly;
# stats stored in the DB match values independently computed from the GPX.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_route_and_pois_sync_from_frontmatter(tmp_path):
    """GPX-backed route and manual-coord POIs upsert correctly from sync."""
    _write_gpx(tmp_path, "test-route.gpx")
    _write_md(
        tmp_path,
        "geo-post.md",
        """\
---
title: Geo Post
slug: geo-post
date: 2025-06-01
route:
  name: Integration Test Route
  gpx_file: test-route.gpx
  description: A loop through the test forest.
points_of_interest:
  - name: Wild Campsite
    category: campsite
    lat: 48.02
    lng: 8.02
    notes: No fire allowed.
  - name: Summit Viewpoint
    category: viewpoint
    lat: 48.05
    lng: 8.05
---

Post body.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        counts = await sync_posts(tmp_path, session)
        await session.commit()

    assert counts["upserted"] == 1
    assert counts["skipped"] == 0

    # Verify Route row exists and geometry round-trips through PostGIS.
    async with factory() as session:
        post_result = await session.execute(select(Post).where(Post.slug == "geo-post"))
        post = post_result.scalar_one()

        route_result = await session.execute(select(Route).where(Route.post_id == post.id))
        route = route_result.scalar_one()

        assert route.name == "Integration Test Route"
        assert route.description == "A loop through the test forest."

        # Geometry round-trip: recover the LineString and check coords.
        linestring = to_shape(route.track)
        coords = list(linestring.coords)
        assert len(coords) == 3
        assert coords[0] == pytest.approx((8.0, 48.0))
        assert coords[1] == pytest.approx((8.05, 48.05))
        assert coords[2] == pytest.approx((8.1, 48.0))

        # Verify POIs.
        poi_result = await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))
        pois = poi_result.scalars().all()
        assert len(pois) == 2

        names = {p.name for p in pois}
        assert names == {"Wild Campsite", "Summit Viewpoint"}

        campsite = next(p for p in pois if p.name == "Wild Campsite")
        campsite_point = to_shape(campsite.location)
        assert campsite_point.x == pytest.approx(8.02)  # lng → x
        assert campsite_point.y == pytest.approx(48.02)  # lat → y
        assert campsite.category == "campsite"
        assert campsite.notes == "No fire allowed."


@pytest.mark.integration
async def test_route_stats_match_independent_gpxpy_calculation(tmp_path):
    """Stats stored in the Route row match values calculated directly from the GPX.

    This is the hard criterion: values must be *correct*, not just non-null.
    """
    _write_gpx(tmp_path, "test-route.gpx")
    _write_md(
        tmp_path,
        "stats-post.md",
        """\
---
title: Stats Post
slug: stats-post
date: 2025-06-01
route:
  name: Stats Route
  gpx_file: test-route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    # Compute expected values independently via gpxpy on the raw GPX.
    expected = _gpx_expected_stats(FIXTURE_GPX)

    async with factory() as session:
        post_result = await session.execute(select(Post).where(Post.slug == "stats-post"))
        post = post_result.scalar_one()

        route_result = await session.execute(select(Route).where(Route.post_id == post.id))
        route = route_result.scalar_one()

    # All stats must be non-null and match the independently computed values.
    assert route.distance_km is not None
    assert route.elevation_gain_m is not None
    assert route.elevation_loss_m is not None
    assert route.duration_minutes is not None

    assert route.distance_km == pytest.approx(expected["distance_km"], rel=1e-3)
    assert route.elevation_gain_m == pytest.approx(expected["elevation_gain_m"], rel=1e-3)
    assert route.elevation_loss_m == pytest.approx(expected["elevation_loss_m"], rel=1e-3)
    assert route.duration_minutes == pytest.approx(expected["duration_minutes"], rel=1e-3)

    # Sanity-check the expected values themselves (so the test is self-documenting).
    assert expected["distance_km"] > 5.0  # at least 5 km
    assert expected["elevation_gain_m"] > 50.0  # at least 50 m climbed
    assert expected["duration_minutes"] == pytest.approx(60.0)  # exactly 1 hour


# ---------------------------------------------------------------------------
# Phase 2 Done-when criterion 3:
# Posts with no route/POIs still sync unaffected — explicit regression test.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_without_geo_syncs_unaffected(tmp_path):
    """A post with no route/POI fields syncs exactly as before Phase 2.

    This is the single most common case (every post today); it gets its own
    test rather than relying on the absence of a failure.
    """
    _write_md(
        tmp_path,
        "plain-post.md",
        """\
---
title: Plain Post
slug: plain-post
date: 2025-06-01
summary: No maps here.
tags:
  - gravel
draft: false
---

# Plain Post

Just text, no GPX, no POIs.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        counts = await sync_posts(tmp_path, session)
        await session.commit()

    assert counts["upserted"] == 1
    assert counts["skipped"] == 0
    assert counts["deleted"] == 0

    # Post row exists with correct data.
    async with factory() as session:
        post_result = await session.execute(select(Post).where(Post.slug == "plain-post"))
        post = post_result.scalar_one()
        assert post.title == "Plain Post"
        assert post.tags == "gravel"

        # No Route row.
        route_result = await session.execute(select(Route).where(Route.post_id == post.id))
        assert route_result.scalar_one_or_none() is None

        # No POI rows.
        poi_result = await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))
        assert poi_result.scalars().all() == []


@pytest.mark.integration
async def test_multiple_posts_geo_and_plain_coexist(tmp_path):
    """A geo post and a plain post in the same directory both sync correctly."""
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "geo-post.md",
        """\
---
title: Geo Post
slug: geo-post
date: 2025-06-01
route:
  name: My Route
  gpx_file: route.gpx
---

GPX body.
""",
    )
    _write_md(
        tmp_path,
        "plain-post.md",
        """\
---
title: Plain Post
slug: plain-post
date: 2025-06-02
---

Plain body.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        counts = await sync_posts(tmp_path, session)
        await session.commit()

    assert counts["upserted"] == 2
    assert counts["skipped"] == 0

    async with factory() as session:
        # Geo post has a Route.
        geo_post = (await session.execute(select(Post).where(Post.slug == "geo-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == geo_post.id))).scalar_one_or_none()
        assert route is not None

        # Plain post has no Route.
        plain_post = (await session.execute(select(Post).where(Post.slug == "plain-post"))).scalar_one()
        no_route = (await session.execute(select(Route).where(Route.post_id == plain_post.id))).scalar_one_or_none()
        assert no_route is None


# ---------------------------------------------------------------------------
# Phase 2 Done-when criterion 4:
# A fixture post that had a route, then has it removed, causes Route row
# deletion (not left orphaned).
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_route_removal_deletes_db_row(tmp_path):
    """Removing a route from frontmatter and re-syncing deletes the Route row."""
    _write_gpx(tmp_path, "route.gpx")
    md_file = _write_md(
        tmp_path,
        "evolving-post.md",
        """\
---
title: Evolving Post
slug: evolving-post
date: 2025-06-01
route:
  name: Initial Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()

    # First sync — Route row created.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    # Confirm the Route row exists.
    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "evolving-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one_or_none()
        assert route is not None, "Route should exist after first sync"

    # Update the frontmatter — remove the route block entirely.
    md_file.write_text(
        """\
---
title: Evolving Post
slug: evolving-post
date: 2025-06-01
---

Body — no route anymore.
""",
        encoding="utf-8",
    )

    # Second sync — Route row should be deleted.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "evolving-post"))).scalar_one()
        orphaned_route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one_or_none()
        assert orphaned_route is None, "Route row must be deleted when removed from frontmatter"


@pytest.mark.integration
async def test_poi_removal_deletes_db_rows(tmp_path):
    """Removing POIs from frontmatter and re-syncing deletes their DB rows."""
    md_file = _write_md(
        tmp_path,
        "poi-post.md",
        """\
---
title: POI Post
slug: poi-post
date: 2025-06-01
points_of_interest:
  - name: Campsite A
    category: campsite
    lat: 48.0
    lng: 8.0
  - name: Viewpoint B
    category: viewpoint
    lat: 48.1
    lng: 8.1
---

Body.
""",
    )

    factory = get_session_factory()

    # First sync — 2 POI rows created.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "poi-post"))).scalar_one()
        pois = (
            (await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))).scalars().all()
        )
        assert len(pois) == 2

    # Remove all POIs from frontmatter.
    md_file.write_text(
        """\
---
title: POI Post
slug: poi-post
date: 2025-06-01
---

Body — no POIs anymore.
""",
        encoding="utf-8",
    )

    # Second sync — all POI rows deleted.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "poi-post"))).scalar_one()
        remaining_pois = (
            (await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))).scalars().all()
        )
        assert remaining_pois == []


@pytest.mark.integration
async def test_poi_without_coords_skipped_gracefully(tmp_path):
    """A POI with no lat/lng and no place_query is skipped — sync continues."""
    _write_md(
        tmp_path,
        "partial-poi.md",
        """\
---
title: Partial POI Post
slug: partial-poi
date: 2025-06-01
points_of_interest:
  - name: No Coordinates POI
    category: other
  - name: Good POI
    category: campsite
    lat: 48.0
    lng: 8.0
---

Body.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        counts = await sync_posts(tmp_path, session)
        await session.commit()

    # Post is upserted despite the bad POI.
    assert counts["upserted"] == 1
    assert counts["skipped"] == 0

    # Only the POI with coordinates was written.
    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "partial-poi"))).scalar_one()
        pois = (
            (await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))).scalars().all()
        )
        assert len(pois) == 1
        assert pois[0].name == "Good POI"


@pytest.mark.integration
async def test_sync_is_idempotent_with_route_and_pois(tmp_path):
    """Syncing a geo post twice produces no duplicate Route/POI rows."""
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "idempotent.md",
        """\
---
title: Idempotent Post
slug: idempotent
date: 2025-06-01
route:
  name: Idempotent Route
  gpx_file: route.gpx
points_of_interest:
  - name: Stable POI
    category: campsite
    lat: 48.0
    lng: 8.0
---

Body.
""",
    )

    factory = get_session_factory()

    # First sync.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    # Second sync — identical files.
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "idempotent"))).scalar_one()

        routes = (await session.execute(select(Route).where(Route.post_id == post.id))).scalars().all()
        assert len(routes) == 1, "Exactly one Route row after two syncs"

        pois = (
            (await session.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))).scalars().all()
        )
        assert len(pois) == 1, "Exactly one POI row after two syncs"
