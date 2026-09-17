"""Unit tests for GET /posts/{slug}/amenities.geojson.

F1, docs/dev/review_17SEP2026.md — the lazy amenity GeoJSON endpoint that
replaces inlining the full FeatureCollection into post.html. No DB needed:
uses the same dependency-override mock-session pattern as
tests/unit/test_templates.py.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import LineString, Point
from sqlalchemy.engine import Result

from app.core.db import get_db_session
from app.main import create_app

_FAKE_TRACK = from_shape(LineString([(8.0, 48.0), (8.1, 48.1), (8.2, 48.0)]), srid=4326)
_FAKE_LOCATION = from_shape(Point(8.05, 48.05), srid=4326)


class _FakePost:
    id = 1
    slug = "test-post"
    is_draft = False


class _FakeRoute:
    id = 1
    post_id = 1
    name = "Kinzig Valley Loop"
    track = _FAKE_TRACK
    amenities_synced_at = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.UTC)


class _FakeAmenity:
    id = 1
    route_id = 1
    osm_element_type = "node"
    osm_element_id = 42
    category = "campsite"
    name = "Wild Camp"
    location = _FAKE_LOCATION
    tags = {"website": "https://example.com"}


def _result(scalar=None, scalars_list=None):
    r = MagicMock(spec=Result)
    r.scalar_one_or_none.return_value = scalar
    r.scalars.return_value.all.return_value = scalars_list if scalars_list is not None else []
    return r


def _session(*call_results):
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=list(call_results))
    return session


def _app(session_dep):
    app = create_app()
    app.dependency_overrides[get_db_session] = session_dep
    return app


async def _client(session_dep):
    with patch("app.routes.posts.get_settings") as mock_gs:
        mock_gs.return_value.is_production = False
        transport = ASGITransport(app=_app(session_dep))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.unit
async def test_amenities_endpoint_404_for_unknown_slug():
    async def session_dep():
        yield _session(_result(scalar=None))

    async for client in _client(session_dep):
        resp = await client.get("/posts/does-not-exist/amenities.geojson")
    assert resp.status_code == 404


@pytest.mark.unit
async def test_amenities_endpoint_404_when_post_has_no_route():
    async def session_dep():
        yield _session(_result(scalar=_FakePost()), _result(scalar=None))

    async for client in _client(session_dep):
        resp = await client.get("/posts/test-post/amenities.geojson")
    assert resp.status_code == 404


@pytest.mark.unit
async def test_amenities_endpoint_returns_empty_collection_when_no_amenities():
    async def session_dep():
        yield _session(
            _result(scalar=_FakePost()),
            _result(scalar=_FakeRoute()),
            _result(scalars_list=[]),
        )

    async for client in _client(session_dep):
        resp = await client.get("/posts/test-post/amenities.geojson")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"type": "FeatureCollection", "features": []}


@pytest.mark.unit
async def test_amenities_endpoint_returns_features_when_present():
    async def session_dep():
        yield _session(
            _result(scalar=_FakePost()),
            _result(scalar=_FakeRoute()),
            _result(scalars_list=[_FakeAmenity()]),
        )

    async for client in _client(session_dep):
        resp = await client.get("/posts/test-post/amenities.geojson")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["name"] == "Wild Camp"
    assert body["features"][0]["properties"]["tags"] == {"website": "https://example.com"}


@pytest.mark.unit
async def test_amenities_endpoint_sets_etag_from_amenities_synced_at():
    async def session_dep():
        yield _session(
            _result(scalar=_FakePost()),
            _result(scalar=_FakeRoute()),
            _result(scalars_list=[_FakeAmenity()]),
        )

    async for client in _client(session_dep):
        resp = await client.get("/posts/test-post/amenities.geojson")
    assert resp.status_code == 200
    assert "etag" in resp.headers
    assert "2026-09-01" in resp.headers["etag"]
