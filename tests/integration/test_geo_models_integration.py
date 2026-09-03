"""Integration tests for PostGIS-backed models — requires the PostGIS container.

Per AGENTS.md: any change touching models/route.py or models/campsite.py
(now point_of_interest.py) needs at least one integration test that
round-trips the geometry through the DB.
"""

from __future__ import annotations

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import select, text

import app.core.db as db_module
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.models.route import Route

REAL_DB_URL = get_settings().database_url


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


async def _create_post(session, slug: str = "test-post") -> Post:
    """Insert a minimal Post and return it with its id populated."""
    from datetime import date

    post = Post(
        slug=slug,
        title="Test Post",
        body_markdown="# Test",
        published_date=date(2025, 1, 1),
    )
    session.add(post)
    await session.flush()
    return post


@pytest.mark.integration
async def test_route_geometry_round_trip():
    """A LineString stored via Route round-trips through PostGIS correctly."""
    factory = get_session_factory()
    coords = [(8.0, 48.0), (8.1, 48.1), (8.2, 48.2)]
    line = LineString(coords)

    async with factory() as session:
        post = await _create_post(session)
        route = Route(
            post_id=post.id,
            name="Test Route",
            track=from_shape(line, srid=4326),
        )
        session.add(route)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(Route))
        route = result.scalar_one()
        recovered = to_shape(route.track)

        assert list(recovered.coords) == coords
        assert route.name == "Test Route"


@pytest.mark.integration
async def test_poi_geometry_round_trip():
    """A Point stored via PointOfInterest round-trips through PostGIS correctly."""
    factory = get_session_factory()
    point = Point(8.05, 48.05)

    async with factory() as session:
        post = await _create_post(session)
        poi = PointOfInterest(
            post_id=post.id,
            name="Wild Campsite",
            category="campsite",
            location=from_shape(point, srid=4326),
        )
        session.add(poi)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(PointOfInterest))
        poi = result.scalar_one()
        recovered = to_shape(poi.location)

        assert recovered.x == pytest.approx(8.05)
        assert recovered.y == pytest.approx(48.05)
        assert poi.category == "campsite"


@pytest.mark.integration
async def test_route_post_id_unique_constraint():
    """Two routes cannot reference the same post (unique constraint on post_id)."""
    factory = get_session_factory()
    line = LineString([(8.0, 48.0), (8.1, 48.1)])

    async with factory() as session:
        post = await _create_post(session)
        route1 = Route(post_id=post.id, name="Route A", track=from_shape(line, srid=4326))
        session.add(route1)
        await session.flush()

        route2 = Route(post_id=post.id, name="Route B", track=from_shape(line, srid=4326))
        session.add(route2)
        with pytest.raises(Exception):  # noqa: B017 — IntegrityError wrapped by SA
            await session.flush()


@pytest.mark.integration
async def test_multiple_pois_per_post():
    """Multiple POIs can reference the same post (no unique constraint)."""
    factory = get_session_factory()

    async with factory() as session:
        post = await _create_post(session)
        for i, cat in enumerate(["campsite", "restaurant", "viewpoint"]):
            poi = PointOfInterest(
                post_id=post.id,
                name=f"POI {i}",
                category=cat,
                location=from_shape(Point(8.0 + i * 0.1, 48.0), srid=4326),
            )
            session.add(poi)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(PointOfInterest))
        pois = result.scalars().all()
        assert len(pois) == 3
        categories = {p.category for p in pois}
        assert categories == {"campsite", "restaurant", "viewpoint"}
