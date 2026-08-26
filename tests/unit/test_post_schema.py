"""Unit tests for PostFrontmatter schema — covers new Phase 2 geo fields.

No DB required.  Tests that:
- Posts without route/POIs are still valid.
- Posts with a route block parse correctly.
- Posts with points_of_interest parse correctly.
- Invalid or partial POI data is handled by Pydantic correctly.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.post_schema import PoiFrontmatter, PostFrontmatter, RouteFrontmatter

# ---------------------------------------------------------------------------
# PostFrontmatter — backward-compatible tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_post_without_geo_fields_valid():
    """A post with no route/POIs is still valid — maps are never mandatory."""
    fm = PostFrontmatter.model_validate(
        {
            "title": "Plain Post",
            "slug": "plain-post",
            "date": "2025-01-01",
        }
    )
    assert fm.route is None
    assert fm.points_of_interest == []


@pytest.mark.unit
def test_post_with_route_parses():
    """A post with a full route block parses correctly."""
    fm = PostFrontmatter.model_validate(
        {
            "title": "GPX Post",
            "slug": "gpx-post",
            "date": "2025-06-01",
            "route": {
                "name": "Kinzig Loop",
                "gpx_file": "kinzig.gpx",
                "description": "A great loop.",
            },
        }
    )
    assert fm.route is not None
    assert fm.route.name == "Kinzig Loop"
    assert fm.route.gpx_file == "kinzig.gpx"
    assert fm.route.description == "A great loop."


@pytest.mark.unit
def test_post_with_route_description_optional():
    """Route description is optional."""
    fm = PostFrontmatter.model_validate(
        {
            "title": "GPX Post",
            "slug": "gpx-post",
            "date": "2025-06-01",
            "route": {
                "name": "Quick Ride",
                "gpx_file": "quick.gpx",
            },
        }
    )
    assert fm.route is not None
    assert fm.route.description is None


@pytest.mark.unit
def test_post_with_pois_parses():
    """A post with a list of POIs parses correctly."""
    fm = PostFrontmatter.model_validate(
        {
            "title": "POI Post",
            "slug": "poi-post",
            "date": "2025-07-01",
            "points_of_interest": [
                {
                    "name": "Wild Campsite",
                    "category": "campsite",
                    "lat": 48.05,
                    "lng": 8.05,
                    "notes": "No fire allowed.",
                },
                {
                    "name": "Gasthaus zum Ritter",
                    "category": "restaurant",
                    "lat": 48.1,
                    "lng": 8.1,
                },
            ],
        }
    )
    assert len(fm.points_of_interest) == 2
    campsite = fm.points_of_interest[0]
    assert campsite.name == "Wild Campsite"
    assert campsite.category == "campsite"
    assert campsite.lat == pytest.approx(48.05)
    assert campsite.lng == pytest.approx(8.05)
    assert campsite.notes == "No fire allowed."

    restaurant = fm.points_of_interest[1]
    assert restaurant.name == "Gasthaus zum Ritter"
    assert restaurant.notes is None


@pytest.mark.unit
def test_poi_with_place_query_only():
    """A POI with only place_query (geocoding path — Phase 3) is valid at schema level."""
    poi = PoiFrontmatter(name="Café Sonnenberg", category="restaurant", place_query="Café Sonnenberg, Freiburg")
    assert poi.lat is None
    assert poi.lng is None
    assert poi.place_query == "Café Sonnenberg, Freiburg"


@pytest.mark.unit
def test_poi_with_manual_coordinates():
    """A POI with explicit lat/lng validates correctly."""
    poi = PoiFrontmatter(name="Trailhead", category="viewpoint", lat=47.99, lng=7.82)
    assert poi.lat == pytest.approx(47.99)
    assert poi.lng == pytest.approx(7.82)


@pytest.mark.unit
def test_route_frontmatter_direct():
    """RouteFrontmatter validates directly."""
    r = RouteFrontmatter(name="Test Route", gpx_file="test.gpx")
    assert r.name == "Test Route"
    assert r.gpx_file == "test.gpx"
    assert r.description is None


@pytest.mark.unit
def test_post_with_both_route_and_pois():
    """A post can have both a route and POIs simultaneously."""
    fm = PostFrontmatter.model_validate(
        {
            "title": "Full Post",
            "slug": "full-post",
            "date": "2025-08-01",
            "route": {"name": "Loop", "gpx_file": "loop.gpx"},
            "points_of_interest": [
                {"name": "Summit", "category": "viewpoint", "lat": 48.5, "lng": 8.0},
            ],
        }
    )
    assert fm.route is not None
    assert len(fm.points_of_interest) == 1


@pytest.mark.unit
def test_existing_post_fields_unaffected():
    """All original fields (title, slug, date, tags, etc.) still work after the Phase 2 additions."""
    fm = PostFrontmatter.model_validate(
        {
            "title": "Existing Post",
            "slug": "existing-post",
            "date": "2025-09-01",
            "summary": "A summary.",
            "tags": ["gravel", "germany"],
            "cover_image": "/static/uploads/img.jpg",
            "draft": True,
        }
    )
    assert fm.title == "Existing Post"
    assert fm.summary == "A summary."
    assert fm.tags == ["gravel", "germany"]
    assert fm.cover_image == "/static/uploads/img.jpg"
    assert fm.draft is True
    assert fm.published_date == date(2025, 9, 1)
    assert fm.route is None
    assert fm.points_of_interest == []
