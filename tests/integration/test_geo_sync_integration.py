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

import datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

import gpxpy
import pytest
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString
from sqlalchemy import select, text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.models.nearby_amenity import NearbyAmenity
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.models.route import Route
from app.services.geo_sync import sync_route_amenities
from app.services.overpass import _parse_element  # noqa: PLC2701
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

    assert counts.upserted == 1
    assert counts.skipped == 0

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

    # elevation_profile round-trips through the JSON column correctly
    # (docs/dev/elevation_profile_chart.md Tier 1) — the fixture GPX has
    # elevation on every point, so the profile must be present and trace
    # the same 200m -> 300m -> 250m shape the aggregate stats confirm.
    assert route.elevation_profile is not None
    assert len(route.elevation_profile) == 3  # fewer points than max_points — passed through, not padded
    elevations = [elev for _, elev in route.elevation_profile]
    assert elevations[0] == pytest.approx(200.0)
    assert elevations[1] == pytest.approx(300.0)
    assert elevations[2] == pytest.approx(250.0)

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

    assert counts.upserted == 1
    assert counts.skipped == 0
    assert counts.deleted == 0

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

    assert counts.upserted == 2
    assert counts.skipped == 0

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
async def test_route_update_replaces_elevation_profile(tmp_path):
    """Re-syncing a post with a changed GPX updates the existing Route
    row's elevation_profile (the update branch of upsert_route_for_post,
    not just the insert branch the other tests exercise).
    """
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "changing-elevation-post.md",
        """\
---
title: Changing Elevation Post
slug: changing-elevation-post
date: 2025-06-01
route:
  name: Changing Elevation Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "changing-elevation-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()
        original_route_id = route.id
        assert route.elevation_profile is not None
        original_elevations = [elev for _, elev in route.elevation_profile]
        assert original_elevations[0] == pytest.approx(200.0)

    # A GPX with no elevation data at all — the update branch must
    # overwrite the profile with None, not leave the stale one in place.
    no_elevation_gpx = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="48.0" lon="8.0"></trkpt>
    <trkpt lat="48.05" lon="8.05"></trkpt>
  </trkseg></trk>
</gpx>
"""
    _write_gpx(tmp_path, "route.gpx", content=no_elevation_gpx)

    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "changing-elevation-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()
        assert route.id == original_route_id, "same row updated, not a new one inserted"
        assert route.elevation_profile is None


@pytest.mark.integration
async def test_track_updated_at_set_on_initial_insert(tmp_path):
    """A freshly-inserted Route gets track_updated_at populated — the
    amenity resync freshness check (docs/dev/fix_amenity_resync_freshness.md
    Phase 1) needs this set from the very first sync, not only from a
    later update.
    """
    before = datetime.datetime.now(datetime.UTC)
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "fresh-insert-post.md",
        """\
---
title: Fresh Insert Post
slug: fresh-insert-post
date: 2025-06-01
route:
  name: Fresh Insert Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "fresh-insert-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()
        assert route.track_updated_at is not None
        assert route.track_updated_at >= before


@pytest.mark.integration
async def test_track_updated_at_unchanged_on_description_only_edit(tmp_path):
    """Re-syncing a post with an unchanged GPX but an edited description
    must leave track_updated_at untouched — a prose-only edit is not a
    geometry change, and must never look like one to the amenity resync
    freshness check.
    """
    _write_gpx(tmp_path, "route.gpx")
    md_file = _write_md(
        tmp_path,
        "prose-edit-post.md",
        """\
---
title: Prose Edit Post
slug: prose-edit-post
date: 2025-06-01
route:
  name: Prose Edit Route
  gpx_file: route.gpx
  description: Original description.
---

Body.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "prose-edit-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()
        original_track_updated_at = route.track_updated_at
        assert original_track_updated_at is not None

    # Content-only edit — same GPX, different description.
    _write_md(
        tmp_path,
        "prose-edit-post.md",
        """\
---
title: Prose Edit Post
slug: prose-edit-post
date: 2025-06-01
route:
  name: Prose Edit Route
  gpx_file: route.gpx
  description: Edited description, no geometry change.
---

Body.
""",
    )

    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "prose-edit-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()
        assert route.description == "Edited description, no geometry change."
        assert route.track_updated_at == original_track_updated_at, (
            "a content-only edit must not touch track_updated_at"
        )

    assert md_file.exists()


@pytest.mark.integration
async def test_track_updated_at_bumped_on_real_track_change(tmp_path):
    """Re-syncing a post with an actually-changed GPX track must bump
    track_updated_at — the signal the amenity resync freshness check
    relies on to detect a genuine geometry change.
    """
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "track-change-post.md",
        """\
---
title: Track Change Post
slug: track-change-post
date: 2025-06-01
route:
  name: Track Change Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "track-change-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()
        original_track_updated_at = route.track_updated_at
        assert original_track_updated_at is not None

    # Genuinely different track geometry.
    changed_gpx = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="49.0" lon="9.0"><ele>100.0</ele></trkpt>
    <trkpt lat="49.1" lon="9.1"><ele>150.0</ele></trkpt>
  </trkseg></trk>
</gpx>
"""
    _write_gpx(tmp_path, "route.gpx", content=changed_gpx)

    async with factory() as session:
        await sync_posts(tmp_path, session)
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "track-change-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()
        assert route.track_updated_at is not None
        assert route.track_updated_at > original_track_updated_at, "a real geometry change must bump track_updated_at"


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
    assert counts.upserted == 1
    assert counts.skipped == 0

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


# ---------------------------------------------------------------------------
# Phase 4 (gis_cycling_upgrade.md): NearbyAmenity discovery via Overpass.
#
# sync_route()/sync_posts() no longer call Overpass at all—see
# docs/dev/fix_startup_blocking_amenity_sync.md Phase 1. Amenity discovery
# is a separate, explicitly-invoked step now (sync_route_amenities(),
# typically run from a background task in production — see
# app/services/background_sync.py — but called directly and synchronously
# here since these tests only care about the amenity-sync behavior itself,
# not the background-task wiring). Every test above this point passes with
# zero changes since amenity discovery was never inline in the first place
# post-refactor. Always a mocked transport here — never a real network
# call.
# ---------------------------------------------------------------------------


_OVERPASS_CAMPSITE = {
    "type": "node",
    "id": 999,
    "lat": 48.02,
    "lon": 8.02,
    "tags": {"tourism": "camp_site", "name": "Overpass Test Camp"},
}


@pytest.mark.integration
async def test_amenity_discovery_populates_nearby_amenity_rows(tmp_path):
    """Syncing a route with enable_amenity_discovery=True populates
    NearbyAmenity rows from the (mocked) Overpass response — the actual
    DB round-trip the unit tests can't cover.
    """
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "amenity-post.md",
        """\
---
title: Amenity Post
slug: amenity-post
date: 2025-06-01
route:
  name: Amenity Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()

    async with factory() as session:
        result = await sync_posts(tmp_path, session)
        await session.commit()

    assert len(result.amenity_route_ids) == 1, "exactly one route should need amenity discovery"

    async with factory() as session:
        with patch("app.services.geo_sync.query_nearby_amenities", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [_parse_element(_OVERPASS_CAMPSITE)]
            await sync_route_amenities(session, result.amenity_route_ids[0])
        await session.commit()

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "amenity-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()

        amenities = (
            (await session.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route.id))).scalars().all()
        )
        assert len(amenities) == 1
        assert amenities[0].category == "campsite"
        assert amenities[0].name == "Overpass Test Camp"
        assert amenities[0].osm_element_type == "node"
        assert amenities[0].osm_element_id == 999

        location = to_shape(amenities[0].location)
        assert location.x == pytest.approx(8.02)
        assert location.y == pytest.approx(48.02)


@pytest.mark.integration
async def test_amenity_discovery_not_run_unless_explicitly_invoked(tmp_path):
    """sync_posts() alone (as every other test in this file does) creates
    zero NearbyAmenity rows and makes zero Overpass calls, confirmed via a
    mock that would raise if it were ever actually invoked —
    sync_route_amenities() must be called separately for amenities to
    exist at all (fix_startup_blocking_amenity_sync.md Phase 1).
    """
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "no-amenity-post.md",
        """\
---
title: No Amenity Post
slug: no-amenity-post
date: 2025-06-01
route:
  name: No Amenity Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    with patch("app.services.geo_sync.query_nearby_amenities", new_callable=AsyncMock) as mock_query:
        async with factory() as session:
            result = await sync_posts(tmp_path, session)  # sync_route_amenities not called
            await session.commit()
        mock_query.assert_not_awaited()

    assert len(result.amenity_route_ids) == 1, "the route is still reported as needing amenity discovery"

    async with factory() as session:
        post = (await session.execute(select(Post).where(Post.slug == "no-amenity-post"))).scalar_one()
        route = (await session.execute(select(Route).where(Route.post_id == post.id))).scalar_one()

        amenities = (
            (await session.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route.id))).scalars().all()
        )
        assert amenities == []


@pytest.mark.integration
async def test_amenity_discovery_resync_replaces_snapshot_not_duplicates(tmp_path):
    """Re-syncing the same route with amenity discovery on twice produces
    the same NearbyAmenity row — not a duplicate (delete-and-replace
    idempotency, same discipline as PointOfInterest/Route).
    """
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "resync-amenity-post.md",
        """\
---
title: Resync Amenity Post
slug: resync-amenity-post
date: 2025-06-01
route:
  name: Resync Amenity Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    parsed = _parse_element(_OVERPASS_CAMPSITE)

    async with factory() as session:
        result = await sync_posts(tmp_path, session)
        await session.commit()
    route_id = result.amenity_route_ids[0]

    with patch("app.services.geo_sync.query_nearby_amenities", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [parsed]
        async with factory() as session:
            await sync_route_amenities(session, route_id)
            await session.commit()

        # The per-route cooldown (geo_sync.py's _AMENITY_SYNC_COOLDOWN) would
        # otherwise skip this second sync entirely since it happens
        # milliseconds after the first — clearing the timestamp simulates
        # "long enough since last attempt" so this test still exercises the
        # actual delete-and-replace path, not the cooldown skip.
        async with factory() as session:
            route = await session.get(Route, route_id)
            route.amenities_synced_at = None
            await session.commit()

        async with factory() as session:
            await sync_route_amenities(session, route_id)
            await session.commit()

    assert mock_query.await_count == 2, "cooldown reset correctly — both syncs actually queried Overpass"

    async with factory() as session:
        amenities = (
            (await session.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route_id))).scalars().all()
        )
        assert len(amenities) == 1, "Exactly one NearbyAmenity row after two syncs, not a duplicate"


@pytest.mark.integration
async def test_amenity_discovery_cooldown_skips_repeat_sync(tmp_path):
    """Re-syncing the same route with amenity discovery on twice in quick
    succession only queries Overpass once — the second call falls within
    the per-route cooldown and is skipped entirely, leaving the first
    sync's rows untouched. Guards against the exact production incident
    this cooldown was added for: a burst of resyncs of the same route
    tripping overpass-api.de's abuse protection.
    """
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "cooldown-amenity-post.md",
        """\
---
title: Cooldown Amenity Post
slug: cooldown-amenity-post
date: 2025-06-01
route:
  name: Cooldown Amenity Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    parsed = _parse_element(_OVERPASS_CAMPSITE)

    async with factory() as session:
        result = await sync_posts(tmp_path, session)
        await session.commit()
    route_id = result.amenity_route_ids[0]

    with patch("app.services.geo_sync.query_nearby_amenities", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [parsed]
        async with factory() as session:
            await sync_route_amenities(session, route_id)
            await session.commit()
        async with factory() as session:
            await sync_route_amenities(session, route_id)
            await session.commit()

    assert mock_query.await_count == 1, "second sync within the cooldown window must not query Overpass again"

    async with factory() as session:
        route = await session.get(Route, route_id)

        assert route.amenities_synced_at is not None
        amenities = (
            (await session.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route_id))).scalars().all()
        )
        assert len(amenities) == 1, "the cooldown-skipped sync must leave the first sync's row untouched"


@pytest.mark.integration
async def test_amenity_freshness_skips_resync_for_unchanged_route_outside_cooldown(tmp_path):
    """A route synced well outside the 15-minute cooldown window, but
    whose geometry hasn't changed since, is skipped by the freshness
    check (docs/dev/fix_amenity_resync_freshness.md Phase 2) — the exact
    scenario the cooldown alone doesn't catch: a webhook push touching
    unrelated post content, hours after the route's last sync attempt.
    """
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "freshness-post.md",
        """\
---
title: Freshness Post
slug: freshness-post
date: 2025-06-01
route:
  name: Freshness Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    parsed = _parse_element(_OVERPASS_CAMPSITE)

    async with factory() as session:
        result = await sync_posts(tmp_path, session)
        await session.commit()
    route_id = result.amenity_route_ids[0]

    with patch("app.services.geo_sync.query_nearby_amenities", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [parsed]
        async with factory() as session:
            await sync_route_amenities(session, route_id)
            await session.commit()

        # Push both the last attempt AND the geometry-change timestamp
        # back by the same 2 hours — well outside the 15-minute cooldown
        # but still inside the multi-day freshness window, with the
        # geometry provably unchanged since that sync (a content-only
        # webhook push hours later, not a rapid burst, and not a real
        # track edit either).
        async with factory() as session:
            route = await session.get(Route, route_id)
            assert route is not None
            two_hours_ago = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
            route.amenities_synced_at = two_hours_ago
            route.track_updated_at = two_hours_ago
            await session.commit()

        async with factory() as session:
            await sync_route_amenities(session, route_id)
            await session.commit()

    assert mock_query.await_count == 1, "freshness must skip the second sync even though the cooldown has elapsed"

    async with factory() as session:
        amenities = (
            (await session.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route_id))).scalars().all()
        )
        assert len(amenities) == 1, "the freshness-skipped sync must leave the first sync's row untouched"


@pytest.mark.integration
async def test_amenity_freshness_does_not_skip_after_real_track_change(tmp_path):
    """A route whose track genuinely changed after its last amenity sync
    attempt must not be skipped by freshness, even within the freshness
    window — freshness must never mask a real geometry change.
    """
    _write_gpx(tmp_path, "route.gpx")
    _write_md(
        tmp_path,
        "freshness-changed-post.md",
        """\
---
title: Freshness Changed Post
slug: freshness-changed-post
date: 2025-06-01
route:
  name: Freshness Changed Route
  gpx_file: route.gpx
---

Body.
""",
    )

    factory = get_session_factory()
    parsed = _parse_element(_OVERPASS_CAMPSITE)

    async with factory() as session:
        result = await sync_posts(tmp_path, session)
        await session.commit()
    route_id = result.amenity_route_ids[0]

    with patch("app.services.geo_sync.query_nearby_amenities", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [parsed]
        async with factory() as session:
            await sync_route_amenities(session, route_id)
            await session.commit()

        # Simulate: last sync attempt happened 20 minutes ago (outside
        # the 15-minute cooldown, so this actually reaches the freshness
        # check), THEN the route's actual geometry changed just now (a
        # real GPX re-upload) — track_updated_at strictly after
        # amenities_synced_at, which must never be treated as fresh.
        async with factory() as session:
            route = await session.get(Route, route_id)
            assert route is not None
            route.amenities_synced_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=20)
            route.track_updated_at = datetime.datetime.now(datetime.UTC)
            await session.commit()

        async with factory() as session:
            await sync_route_amenities(session, route_id)
            await session.commit()

    assert mock_query.await_count == 2, "a real geometry change must never be masked by the freshness check"


# ---------------------------------------------------------------------------
# fix_incremental_amenity_writes.md Phase 1: per-chunk incremental writes.
#
# These tests need a route spanning more than _SINGLE_QUERY_MAX_SPAN_DEG
# (1.0°) so _amenity_query_bboxes() actually plans more than one chunk —
# the whole point of this phase is behavior that's only observable across
# multiple chunks in the same sync run.
# ---------------------------------------------------------------------------

_MULTI_CHUNK_GPX = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="bulliexplorer-test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Multi-Chunk Test Route</name>
    <trkseg>
      <trkpt lat="48.0" lon="8.0"><ele>200.0</ele><time>2025-06-01T08:00:00Z</time></trkpt>
      <trkpt lat="48.5" lon="8.0"><ele>210.0</ele><time>2025-06-01T08:20:00Z</time></trkpt>
      <trkpt lat="49.0" lon="8.0"><ele>220.0</ele><time>2025-06-01T08:40:00Z</time></trkpt>
      <trkpt lat="49.5" lon="8.0"><ele>230.0</ele><time>2025-06-01T09:00:00Z</time></trkpt>
      <trkpt lat="50.0" lon="8.0"><ele>240.0</ele><time>2025-06-01T09:20:00Z</time></trkpt>
      <trkpt lat="50.5" lon="8.0"><ele>250.0</ele><time>2025-06-01T09:40:00Z</time></trkpt>
      <trkpt lat="51.0" lon="8.0"><ele>260.0</ele><time>2025-06-01T10:00:00Z</time></trkpt>
      <trkpt lat="51.5" lon="8.0"><ele>270.0</ele><time>2025-06-01T10:20:00Z</time></trkpt>
      <trkpt lat="52.0" lon="8.0"><ele>280.0</ele><time>2025-06-01T10:40:00Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


def _overpass_node(osm_id: int, lat: float, lon: float, name: str) -> dict:
    return {
        "type": "node",
        "id": osm_id,
        "lat": lat,
        "lon": lon,
        "tags": {"tourism": "camp_site", "name": name},
    }


async def _sync_multi_chunk_route(tmp_path: Path, slug: str) -> int:
    """Shared setup for the Phase 1 tests below: write a multi-chunk GPX
    + post, sync content, return the route id.
    """
    _write_gpx(tmp_path, "route.gpx", content=_MULTI_CHUNK_GPX)
    _write_md(
        tmp_path,
        f"{slug}.md",
        f"""\
---
title: Multi Chunk Post
slug: {slug}
date: 2025-06-01
route:
  name: Multi Chunk Route
  gpx_file: route.gpx
---

Body.
""",
    )
    factory = get_session_factory()
    async with factory() as session:
        result = await sync_posts(tmp_path, session)
        await session.commit()
    assert len(result.amenity_route_ids) == 1
    return result.amenity_route_ids[0]


@pytest.mark.integration
async def test_amenity_sync_partial_failure_preserves_other_chunks_writes(tmp_path):
    """The whole point of Phase 1: one chunk failing must not discard
    other chunks' already-written results in the same run — the old
    all-or-nothing behavior this replaces would have left zero rows here.
    """
    route_id = await _sync_multi_chunk_route(tmp_path, "partial-failure-post")

    from app.services.geo_sync import _amenity_query_bboxes

    async with get_session_factory()() as session:
        route = await session.get(Route, route_id)
        assert route is not None
        linestring = cast("LineString", to_shape(route.track))
    bboxes = _amenity_query_bboxes(linestring)
    assert len(bboxes) >= 3, "fixture route must plan at least 3 chunks for this test to mean anything"

    call_index = 0

    async def _fake_query(south, west, north, east, *, http_client=None, result_meta=None, **kwargs):
        nonlocal call_index
        idx = call_index
        call_index += 1
        if result_meta is not None:
            result_meta["served_index"] = 0
            result_meta["rate_limited"] = False
        if idx == 1:
            # The second chunk fails outright.
            return None
        return [_parse_element(_overpass_node(1000 + idx, (south + north) / 2, (west + east) / 2, f"Camp {idx}"))]

    with patch("app.services.geo_sync.query_nearby_amenities", side_effect=_fake_query):
        async with get_session_factory()() as session:
            await sync_route_amenities(session, route_id)

    async with get_session_factory()() as session:
        amenities = (
            (await session.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route_id))).scalars().all()
        )
    surviving_ids = {a.osm_element_id for a in amenities}
    # Chunk 1 (index 1) failed and wrote nothing; chunks 0 and 2+ succeeded
    # and their rows must exist.
    assert 1001 not in surviving_ids
    assert 1000 in surviving_ids
    assert any(oid not in (1000, 1001) for oid in surviving_ids), "a later successful chunk's row must also survive"


@pytest.mark.integration
async def test_amenity_sync_overlapping_chunks_no_duplicate_row(tmp_path):
    """The same OSM element returned by two different (overlapping,
    buffer-padded) chunks must upsert to one row, not create a duplicate
    — exercises the DB's own uq_nearby_amenities_route_osm_element
    constraint via the natural-key upsert, not just in-memory dedup.
    """
    route_id = await _sync_multi_chunk_route(tmp_path, "overlap-post")

    shared_node = _overpass_node(42, 48.5, 8.0, "Shared Camp")

    async def _fake_query(south, west, north, east, *, http_client=None, result_meta=None, **kwargs):
        if result_meta is not None:
            result_meta["served_index"] = 0
            result_meta["rate_limited"] = False
        # Every chunk "sees" the same shared element (simulating it
        # falling within more than one chunk's buffer-padded bbox).
        return [_parse_element(shared_node)]

    with patch("app.services.geo_sync.query_nearby_amenities", side_effect=_fake_query):
        async with get_session_factory()() as session:
            await sync_route_amenities(session, route_id)

    async with get_session_factory()() as session:
        amenities = (
            (
                await session.execute(
                    select(NearbyAmenity).where(NearbyAmenity.route_id == route_id, NearbyAmenity.osm_element_id == 42)
                )
            )
            .scalars()
            .all()
        )
    assert len(amenities) == 1, "the same OSM element from multiple chunks must upsert to one row, not duplicate"


@pytest.mark.integration
async def test_amenity_sync_stale_element_removed_when_absent_from_fresh_chunk(tmp_path):
    """An element that used to be in a chunk's bbox but is legitimately
    gone from a fresh, successful re-query of that same bbox must be
    deleted — staleness handling preserved at chunk granularity.
    """
    route_id = await _sync_multi_chunk_route(tmp_path, "staleness-post")

    vanishing_node = _overpass_node(77, 48.02, 8.0, "Soon Gone Camp")
    call_count = 0

    async def _fake_query_first_run(south, west, north, east, *, http_client=None, result_meta=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if result_meta is not None:
            result_meta["served_index"] = 0
            result_meta["rate_limited"] = False
        # Only the first chunk (covering lat ~48.0-48.5, where
        # vanishing_node sits) returns it; later chunks return nothing.
        if call_count == 1:
            return [_parse_element(vanishing_node)]
        return []

    with patch("app.services.geo_sync.query_nearby_amenities", side_effect=_fake_query_first_run):
        async with get_session_factory()() as session:
            await sync_route_amenities(session, route_id)

    async with get_session_factory()() as session:
        amenities = (
            (await session.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route_id))).scalars().all()
        )
    assert any(a.osm_element_id == 77 for a in amenities), "first run must have written the node"

    # Reset the cooldown so a second sync actually re-queries Overpass.
    async with get_session_factory()() as session:
        route = await session.get(Route, route_id)
        assert route is not None
        route.amenities_synced_at = None
        await session.commit()

    async def _fake_query_second_run(south, west, north, east, *, http_client=None, result_meta=None, **kwargs):
        if result_meta is not None:
            result_meta["served_index"] = 0
            result_meta["rate_limited"] = False
        # The node is genuinely gone now — every chunk, including the one
        # that used to cover it, returns nothing.
        return []

    with patch("app.services.geo_sync.query_nearby_amenities", side_effect=_fake_query_second_run):
        async with get_session_factory()() as session:
            await sync_route_amenities(session, route_id)

    async with get_session_factory()() as session:
        amenities = (
            (await session.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route_id))).scalars().all()
        )
    assert not any(a.osm_element_id == 77 for a in amenities), "stale node must be removed after a fresh empty query"
