"""Unit tests for GET /trips.geojson's serialization helpers.

Phase 2b, Step 3 (docs/dev/bulliexplorer_experience_2027.md). Tests the
pure ``_route_feature``/``_poi_only_feature`` functions directly with
in-memory Shapely geometry (same convention as
tests/unit/test_amenities_geojson.py — no DB needed for these). The
full endpoint's query/tiering/ordering is covered by
tests/integration/test_trips_geojson_integration.py, per AGENTS.md's
PostGIS-testing rule.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point

from app.routes.trips import _poi_only_feature, _route_feature

pytestmark = pytest.mark.unit


def _fake_post(slug: str = "test-post", title: str = "Test Post") -> MagicMock:
    post = MagicMock()
    post.slug = slug
    post.title = title
    return post


def _fake_route(track=None, distance_km: float = 25.2, elevation_gain_m: float = 974.0) -> MagicMock:
    route = MagicMock()
    route.track = track
    route.distance_km = distance_km
    route.elevation_gain_m = elevation_gain_m
    return route


def _fake_poi(location=None) -> MagicMock:
    poi = MagicMock()
    poi.location = location
    return poi


def test_route_feature_builds_simplified_linestring():
    track = from_shape(
        LineString([(8.0, 48.0), (8.001, 48.0005), (8.002, 48.001), (8.1, 48.1)]),
        srid=4326,
    )
    post = _fake_post(slug="feldberg-summit-loop", title="Feldberg Summit Loop")
    route = _fake_route(track=track)

    feature = _route_feature(post, route)

    assert feature is not None
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "LineString"
    # Simplification actually reduced the point count (4 -> 2 for this
    # near-collinear fixture at the 0.001-degree tolerance).
    assert len(feature["geometry"]["coordinates"]) < 4
    assert feature["properties"] == {
        "slug": "feldberg-summit-loop",
        "title": "Feldberg Summit Loop",
        "distance_km": 25.2,
        "elevation_gain_m": 974.0,
        "tier": "route",
    }


def test_route_feature_none_track_logs_and_returns_none(caplog):
    post = _fake_post(slug="no-track-post")
    route = _fake_route(track=None)

    with caplog.at_level("WARNING"):
        feature = _route_feature(post, route)

    assert feature is None
    assert "no-track-post" in caplog.text


def test_route_feature_malformed_geometry_logs_and_returns_none(caplog):
    """A track value that isn't parseable WKB/WKBElement — the real
    malformed-geometry case from the doc's acceptance criteria, not just
    a missing track.
    """
    post = _fake_post(slug="malformed-post")
    route = _fake_route(track="not-a-real-geometry")

    with caplog.at_level("WARNING"):
        feature = _route_feature(post, route)

    assert feature is None
    assert "malformed-post" in caplog.text


def test_poi_only_feature_builds_point():
    location = from_shape(Point(10.185381, 61.461463), srid=4326)
    post = _fake_post(slug="poi-only-post", title="POI Only Post")
    poi = _fake_poi(location=location)

    feature = _poi_only_feature(post, poi)

    assert feature == {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [10.185381, 61.461463]},
        "properties": {
            "slug": "poi-only-post",
            "title": "POI Only Post",
            "tier": "poi_only",
        },
    }


def test_poi_only_feature_none_location_logs_and_returns_none(caplog):
    post = _fake_post(slug="no-location-post")
    poi = _fake_poi(location=None)

    with caplog.at_level("WARNING"):
        feature = _poi_only_feature(post, poi)

    assert feature is None
    assert "no-location-post" in caplog.text


def test_poi_only_feature_malformed_geometry_logs_and_returns_none(caplog):
    post = _fake_post(slug="malformed-poi-post")
    poi = _fake_poi(location="not-a-real-geometry")

    with caplog.at_level("WARNING"):
        feature = _poi_only_feature(post, poi)

    assert feature is None
    assert "malformed-poi-post" in caplog.text
