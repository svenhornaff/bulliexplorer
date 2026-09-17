"""Unit tests for app.routes.posts._amenities_to_geojson.

fix_amenity_overlay_ux.md Phase 3 — tags need to be present in the
GeoJSON properties sent to the browser, since the frontend popup
builder conditionally shows a website/phone link only when those OSM
tags exist on a given amenity. No DB needed: NearbyAmenity.location is
built directly via geoalchemy2.shape.from_shape (a real in-memory
WKBElement, no round-trip through Postgres/PostGIS required), matching
the same pattern already used for constructing Route.track fixtures
elsewhere in this project's unit tests.
"""

from __future__ import annotations

from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.models.nearby_amenity import NearbyAmenity
from app.routes.posts import _amenities_to_geojson


def _amenity(
    *, amenity_id: int = 1, name: str | None = "Test Camp", category: str = "campsite", tags: dict | None = None
) -> NearbyAmenity:
    return NearbyAmenity(
        id=amenity_id,
        route_id=1,
        osm_element_type="node",
        osm_element_id=1000 + amenity_id,
        category=category,
        name=name,
        location=from_shape(Point(8.02, 48.02), srid=4326),
        tags=tags,
    )


def test_amenities_to_geojson_includes_tags_when_present():
    """The whole point of Phase 3: tags must reach the browser now."""
    amenity = _amenity(tags={"website": "https://example.com", "phone": "+49 761 1234"})
    result = _amenities_to_geojson([amenity])
    assert result["features"][0]["properties"]["tags"] == {
        "website": "https://example.com",
        "phone": "+49 761 1234",
    }


def test_amenities_to_geojson_tags_defaults_to_empty_dict_when_none():
    """NearbyAmenity.tags is nullable — a None must not crash or become
    None in the output (the frontend checks for presence of specific
    keys via `tags.website` etc.; an empty object is the safe default,
    not a missing key or a null)."""
    amenity = _amenity(tags=None)
    result = _amenities_to_geojson([amenity])
    assert result["features"][0]["properties"]["tags"] == {}


def test_amenities_to_geojson_still_includes_name_and_category():
    """Non-regression: the pre-existing properties are untouched by this
    change, just extended with a new key."""
    amenity = _amenity(name="Test Camp", category="campsite", tags={"website": "https://example.com"})
    result = _amenities_to_geojson([amenity])
    props = result["features"][0]["properties"]
    assert props["name"] == "Test Camp"
    assert props["category"] == "campsite"
