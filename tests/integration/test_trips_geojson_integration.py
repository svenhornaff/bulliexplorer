"""Integration test for GET /trips.geojson — Phase 2b, Step 3
(docs/dev/bulliexplorer_experience_2027.md).

Requires the PostGIS container, per AGENTS.md's rule that any change
touching the PostGIS-backed models needs a real geometry round-trip
test, not just a mocked-session unit test. Uses the same fixture
helpers/conventions as tests/integration/test_post_map_integration.py.
"""

from __future__ import annotations

import datetime

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


async def _insert_routed_post(factory, slug: str, title: str, published_date: datetime.date) -> None:
    async with factory() as session:
        post = Post(
            slug=slug,
            title=title,
            summary="Test summary.",
            body_markdown="# Ride\n\nSome text.",
            published_date=published_date,
            is_draft=False,
        )
        session.add(post)
        await session.flush()
        route = Route(
            post_id=post.id,
            name=title,
            track=from_shape(LineString([(8.0, 48.0), (8.1, 48.1), (8.2, 48.0)]), srid=4326),
            distance_km=25.2,
            elevation_gain_m=974.0,
        )
        session.add(route)
        await session.commit()


async def _insert_poi_only_post(factory, slug: str, title: str, published_date: datetime.date) -> None:
    async with factory() as session:
        post = Post(
            slug=slug,
            title=title,
            summary="Test summary.",
            body_markdown="# Trip\n\nSome text.",
            published_date=published_date,
            is_draft=False,
        )
        session.add(post)
        await session.flush()
        poi = PointOfInterest(
            post_id=post.id,
            name="A Place",
            category="viewpoint",
            location=from_shape(Point(10.185381, 61.461463), srid=4326),
        )
        session.add(poi)
        await session.commit()


async def _insert_draft_routed_post(factory, slug: str, published_date: datetime.date) -> None:
    async with factory() as session:
        post = Post(
            slug=slug,
            title="Draft Post",
            summary="Should never appear.",
            body_markdown="# Draft\n\nSome text.",
            published_date=published_date,
            is_draft=True,
        )
        session.add(post)
        await session.flush()
        route = Route(
            post_id=post.id,
            name="Draft Route",
            track=from_shape(LineString([(8.0, 48.0), (8.1, 48.1)]), srid=4326),
            distance_km=10.0,
            elevation_gain_m=100.0,
        )
        session.add(route)
        await session.commit()


@pytest.mark.integration
async def test_trips_geojson_empty_site_returns_empty_feature_collection():
    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/trips.geojson")

    assert resp.status_code == 200
    assert resp.json() == {"type": "FeatureCollection", "features": []}


@pytest.mark.integration
async def test_trips_geojson_tiers_and_orders_real_posts():
    """The literal acceptance criterion from the doc: routed posts first
    (newest first), poi_only posts second (newest first), draft posts
    never appear.
    """
    factory = get_session_factory()
    await _insert_routed_post(factory, "older-route", "Older Route", datetime.date(2025, 1, 1))
    await _insert_routed_post(factory, "newer-route", "Newer Route", datetime.date(2026, 1, 1))
    await _insert_poi_only_post(factory, "older-poi", "Older POI", datetime.date(2025, 6, 1))
    await _insert_poi_only_post(factory, "newer-poi", "Newer POI", datetime.date(2026, 6, 1))
    await _insert_draft_routed_post(factory, "draft-route", datetime.date(2026, 12, 1))

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/trips.geojson")

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "public, max-age=300"

    body = resp.json()
    slugs_and_tiers = [(f["properties"]["slug"], f["properties"]["tier"]) for f in body["features"]]

    assert slugs_and_tiers == [
        ("newer-route", "route"),
        ("older-route", "route"),
        ("newer-poi", "poi_only"),
        ("older-poi", "poi_only"),
    ]

    route_feature = body["features"][0]
    assert route_feature["geometry"]["type"] == "LineString"
    assert len(route_feature["geometry"]["coordinates"]) >= 2
    assert route_feature["properties"]["distance_km"] == 25.2
    assert route_feature["properties"]["elevation_gain_m"] == 974.0

    poi_feature = body["features"][2]
    assert poi_feature["geometry"]["type"] == "Point"
    assert poi_feature["geometry"]["coordinates"] == [10.185381, 61.461463]
    assert "distance_km" not in poi_feature["properties"]
