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
from sqlalchemy import select, text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.models.nearby_amenity import NearbyAmenity
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


async def _route_id_for_post(factory, post_id: int) -> int:
    """Look up a Route's id by its post_id (F1, review_17SEP2026.md tests)."""
    async with factory() as session:
        result = await session.execute(select(Route.id).where(Route.post_id == post_id))
        return result.scalar_one()


async def _insert_amenity(factory, route_id: int) -> None:
    """Insert a single NearbyAmenity for the given route (F1, review_17SEP2026.md)."""
    location = from_shape(Point(8.05, 48.05), srid=4326)
    async with factory() as session:
        amenity = NearbyAmenity(
            route_id=route_id,
            osm_element_type="node",
            osm_element_id=999,
            category="restaurant",
            name="Waldgasthof",
            location=location,
            tags={"website": "https://example.com"},
        )
        session.add(amenity)
        await session.commit()


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
async def test_post_with_route_renders_fullscreen_toggle():
    """Phase 2 (gis_cycling_upgrade.md): the full-screen map toggle button
    and its wrapping element render alongside the map, with the ARIA
    attributes the accessibility scope requires present from the start.
    """
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
    assert 'id="map-wrap"' in resp.text
    assert 'id="map-fullscreen-toggle"' in resp.text
    assert 'aria-pressed="false"' in resp.text
    assert 'aria-controls="post-map"' in resp.text
    # The toggle must be rendered *before* #post-map so the focus-trap's
    # first/last element ordering (post.html's getFocusable walk) puts it
    # first — a screen-reader/keyboard user landing in the modal always
    # reaches the close control without having to Shift+Tab backwards.
    assert resp.text.index('id="map-fullscreen-toggle"') < resp.text.index('id="post-map"')


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


# ---------------------------------------------------------------------------
# F1 (docs/dev/review_17SEP2026.md) — lazy amenity GeoJSON endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_detail_no_longer_inlines_amenity_data():
    """The whole point of F1: a post with amenities must not carry their
    name/tags in the HTML response body any more — that data is now
    fetched lazily from the new endpoint instead."""
    factory = get_session_factory()
    post_id = await _insert_post(factory)
    await _insert_route(factory, post_id)
    route_id = await _route_id_for_post(factory, post_id)
    await _insert_amenity(factory, route_id)

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    with patch("app.routes.posts.get_settings") as mock_gs:
        mock_gs.return_value.tiles_url = "pmtiles://https://example.com/tiles.pmtiles"
        mock_gs.return_value.is_production = False

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/posts/kinzig-valley-loop")

    assert resp.status_code == 200
    assert "Waldgasthof" not in resp.text  # amenity name must not be inlined
    assert "amenities.geojson" in resp.text  # lazy-fetch URL is present instead
    assert "amenity-toggle" in resp.text  # toggle still renders (has_amenities=True)


@pytest.mark.integration
async def test_amenities_geojson_endpoint_returns_real_geometry():
    """Round-trips a real NearbyAmenity's PostGIS geometry through the new
    /posts/{slug}/amenities.geojson endpoint end-to-end."""
    factory = get_session_factory()
    post_id = await _insert_post(factory)
    await _insert_route(factory, post_id)
    route_id = await _route_id_for_post(factory, post_id)
    await _insert_amenity(factory, route_id)

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    with patch("app.routes.posts.get_settings") as mock_gs:
        mock_gs.return_value.is_production = False

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/posts/kinzig-valley-loop/amenities.geojson")

    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    feature = body["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["geometry"]["coordinates"] == [8.05, 48.05]
    assert feature["properties"]["name"] == "Waldgasthof"
    assert feature["properties"]["tags"] == {"website": "https://example.com"}
    assert "etag" in resp.headers


@pytest.mark.integration
async def test_amenities_geojson_endpoint_empty_when_route_has_none():
    """A route with zero amenities returns an empty FeatureCollection, not a 404."""
    factory = get_session_factory()
    post_id = await _insert_post(factory)
    await _insert_route(factory, post_id)

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    with patch("app.routes.posts.get_settings") as mock_gs:
        mock_gs.return_value.is_production = False

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/posts/kinzig-valley-loop/amenities.geojson")

    assert resp.status_code == 200
    assert resp.json() == {"type": "FeatureCollection", "features": []}


@pytest.mark.integration
async def test_amenities_geojson_endpoint_404_for_unknown_slug():
    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/posts/does-not-exist/amenities.geojson")

    assert resp.status_code == 404
