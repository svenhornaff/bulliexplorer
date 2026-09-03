"""Integration tests for Phase 5 — post detail with Route + POI data.

Requires the PostGIS container.  Verifies:
- A post with route + POIs renders the stats row and map container on the
  post detail page.
- A post without route/POIs renders identically to pre-Phase-5 behaviour
  (zero regression — this is the single most common case today).
- The /posts/ list page is unaffected by posts that do or don't have routes
  (no row dropped or duplicated).
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import LineString, Point
from sqlalchemy import text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.models.route import Route

REAL_DB_URL = get_settings().database_url

# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def clean_db():
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_post(factory, slug: str = "kinzig-valley-loop") -> int:
    """Insert a minimal Post and return its id."""
    async with factory() as session:
        post = Post(
            slug=slug,
            title="The Kinzig Valley Loop",
            summary="68 km through Black Forest singletrack.",
            body_markdown="# Ride\n\nSome text.",
            published_date=datetime.date(2025, 8, 24),
            is_draft=False,
        )
        session.add(post)
        await session.flush()
        post_id = post.id
        await session.commit()
    return post_id


async def _insert_route(factory, post_id: int) -> None:
    """Insert a minimal Route with stats for the given post."""
    track = from_shape(
        LineString([(8.0, 48.0), (8.1, 48.1), (8.2, 48.0)]),
        srid=4326,
    )
    async with factory() as session:
        route = Route(
            post_id=post_id,
            name="Kinzig Valley Loop",
            description="A classic Black Forest loop.",
            track=track,
            distance_km=68.0,
            elevation_gain_m=1420.0,
            elevation_loss_m=1380.0,
            duration_minutes=275.0,
        )
        session.add(route)
        await session.commit()


async def _insert_poi(factory, post_id: int) -> None:
    """Insert a single PointOfInterest for the given post."""
    location = from_shape(Point(8.05, 48.05), srid=4326)
    async with factory() as session:
        poi = PointOfInterest(
            post_id=post_id,
            name="Wild Campsite",
            category="campsite",
            notes="No fire allowed.",
            location=location,
        )
        session.add(poi)
        await session.commit()


def _make_app(tiles_url: str = "pmtiles://https://example.com/tiles.pmtiles"):
    """FastAPI app with tiles_url patched in settings."""
    from app.main import create_app

    application = create_app()

    # Patch get_settings inside the posts router so tiles_url is set.
    original_get_settings = get_settings

    class _PatchedSettings:
        def __getattr__(self, name: str):
            return getattr(original_get_settings(), name)

        tiles_url = tiles_url
        is_production = False

    return application, _PatchedSettings


# ---------------------------------------------------------------------------
# Phase 5 Done-when criterion — post with route + POIs renders correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_with_route_renders_stats_row():
    """Stats row is present on a real post-detail page with route data."""
    factory = get_session_factory()
    post_id = await _insert_post(factory)
    await _insert_route(factory, post_id)
    await _insert_poi(factory, post_id)

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    with patch("app.routes.posts.get_settings") as mock_gs:
        mock_gs.return_value.tiles_url = "pmtiles://https://example.com/tiles.pmtiles"
        mock_gs.return_value.is_production = False

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/posts/kinzig-valley-loop")

    assert resp.status_code == 200
    assert "route-stats" in resp.text
    assert "68.0" in resp.text  # distance_km
    assert "1420" in resp.text  # elevation_gain_m
    assert "4h" in resp.text  # duration hours


@pytest.mark.integration
async def test_post_with_route_renders_map_container():
    """Map div is rendered when tiles_url is configured and route is present."""
    factory = get_session_factory()
    post_id = await _insert_post(factory)
    await _insert_route(factory, post_id)

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    with patch("app.routes.posts.get_settings") as mock_gs:
        mock_gs.return_value.tiles_url = "pmtiles://https://example.com/tiles.pmtiles"
        mock_gs.return_value.is_production = False

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/posts/kinzig-valley-loop")

    assert resp.status_code == 200
    assert "post-map" in resp.text
    assert "maplibre-gl.js" in resp.text
    assert "LineString" in resp.text  # route GeoJSON inlined
    assert "FeatureCollection" in resp.text  # POIs GeoJSON inlined


@pytest.mark.integration
async def test_post_with_route_geojson_contains_correct_coords():
    """Inlined route GeoJSON has the correct coordinate values."""
    factory = get_session_factory()
    post_id = await _insert_post(factory)
    await _insert_route(factory, post_id)

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    with patch("app.routes.posts.get_settings") as mock_gs:
        mock_gs.return_value.tiles_url = "pmtiles://https://example.com/tiles.pmtiles"
        mock_gs.return_value.is_production = False

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/posts/kinzig-valley-loop")

    assert "8.0" in resp.text  # first coordinate lon
    assert "48.0" in resp.text  # first coordinate lat


# ---------------------------------------------------------------------------
# Phase 5 Done-when criterion — post WITHOUT route unaffected
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_without_route_renders_no_map():
    """A post with no route renders identically to pre-Phase-5 — zero regression."""
    factory = get_session_factory()
    await _insert_post(factory, slug="plain-post")

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/plain-post")

    assert resp.status_code == 200
    assert "The Kinzig Valley Loop" in resp.text
    assert "post-map" not in resp.text
    assert "route-stats" not in resp.text
    assert "maplibregl" not in resp.text


# ---------------------------------------------------------------------------
# Phase 5 Done-when criterion — /posts/ list not affected by route data
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_list_not_affected_by_route_data():
    """Posts with and without routes both appear in the list — no drops or dupes."""
    factory = get_session_factory()

    # Insert two posts — one with route, one without.
    post_id_with = await _insert_post(factory, slug="with-route")
    await _insert_route(factory, post_id_with)
    await _insert_post(factory, slug="without-route")

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/")

    assert resp.status_code == 200
    # Both slugs must appear exactly once (no duplication from any implicit join).
    assert resp.text.count("with-route") == 1
    assert resp.text.count("without-route") == 1
    # No map code on the list page.
    assert "post-map" not in resp.text
    assert "maplibregl" not in resp.text
