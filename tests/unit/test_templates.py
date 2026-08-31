"""Smoke tests for templates — no DB required.

Uses FastAPI dependency overrides to inject a mock session so DB-backed
routes can be tested without a running database.

post_detail now makes three execute() calls (post, route, POIs) in sequence;
the mock session helpers use side_effect to return different results per call.
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

# ---------------------------------------------------------------------------
# Fake geometry — real WKBElements that to_shape() can process, no DB needed
# ---------------------------------------------------------------------------

_FAKE_TRACK = from_shape(
    LineString([(8.0, 48.0), (8.1, 48.1), (8.2, 48.0)]),
    srid=4326,
)
_FAKE_LOCATION = from_shape(Point(8.05, 48.05), srid=4326)


# ---------------------------------------------------------------------------
# Fake ORM objects
# ---------------------------------------------------------------------------


class _FakePost:
    id = 1
    slug = "test-post"
    title = "A Gravel Day in the Black Forest"
    summary = "Single-track, mud, and a very questionable coffee stop."
    published_date = datetime.date(2025, 8, 24)
    cover_image = None
    tags = "gravel,adventure"
    body_html = "<p>Placeholder body.</p>"
    is_draft = False


class _FakeRoute:
    id = 1
    post_id = 1
    name = "Kinzig Valley Loop"
    description = "A loop through the Black Forest"
    track = _FAKE_TRACK
    distance_km = 68.0
    elevation_gain_m = 1420.0
    elevation_loss_m = 1380.0
    duration_minutes = 275.0  # 4h 35min


class _FakePOI:
    id = 1
    post_id = 1
    name = "Wild Campsite"
    category = "campsite"
    notes = "No fire allowed."
    location = _FAKE_LOCATION


# ---------------------------------------------------------------------------
# Mock session helpers
# ---------------------------------------------------------------------------


def _result(scalar=None, scalars_list=None):
    """Return a single MagicMock(spec=Result) with pre-set return values."""
    r = MagicMock(spec=Result)
    r.scalar_one_or_none.return_value = scalar
    r.scalars.return_value.all.return_value = scalars_list if scalars_list is not None else []
    return r


def _session(*call_results):
    """Async session mock that returns a different Result per execute() call."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=list(call_results))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


async def _empty_session():
    """Post-list session: no posts."""
    yield _session(_result(scalars_list=[]))


async def _404_session():
    """Post-detail session: post not found."""
    yield _session(_result(scalar=None))


async def _post_session():
    """Post-detail session: post found, no route, no POIs."""
    yield _session(
        _result(scalar=_FakePost()),  # post query
        _result(scalar=None),  # route query
        _result(scalars_list=[]),  # POIs query
    )


async def _post_with_route_session():
    """Post-detail session: post found with route (no POIs)."""
    yield _session(
        _result(scalar=_FakePost()),
        _result(scalar=_FakeRoute()),
        _result(scalars_list=[]),
    )


async def _post_with_route_and_pois_session():
    """Post-detail session: post found with route and one POI."""
    yield _session(
        _result(scalar=_FakePost()),
        _result(scalar=_FakeRoute()),
        _result(scalars_list=[_FakePOI()]),
    )


# ---------------------------------------------------------------------------
# App fixtures
# ---------------------------------------------------------------------------


def _app(session_dep):
    app = create_app()
    app.dependency_overrides[get_db_session] = session_dep
    return app


@pytest.fixture
async def mock_client():
    transport = ASGITransport(app=_app(_empty_session))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client_with_post():
    transport = ASGITransport(app=_app(_post_session))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client_with_route():
    """Post detail with a route but no tiles URL (stats row, no map widget)."""
    with patch("app.routes.posts.get_settings") as mock_settings:
        mock_settings.return_value.tiles_url = ""  # explicitly empty — map must not render
        mock_settings.return_value.is_production = False
        transport = ASGITransport(app=_app(_post_with_route_session))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
async def client_with_route_and_tiles():
    """Post detail with route + tiles URL configured → full map renders."""
    with patch("app.routes.posts.get_settings") as mock_settings:
        mock_settings.return_value.tiles_url = "pmtiles://https://example.com/tiles/black-forest.pmtiles"
        mock_settings.return_value.is_production = False
        transport = ASGITransport(app=_app(_post_with_route_and_pois_session))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


# ---------------------------------------------------------------------------
# Home redirect
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_root_redirects_to_posts(mock_client):
    resp = await mock_client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/posts/"


# ---------------------------------------------------------------------------
# Post list page (/posts/)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_list_returns_200(mock_client):
    resp = await mock_client.get("/posts/")
    assert resp.status_code == 200


@pytest.mark.unit
async def test_post_list_contains_site_name(mock_client):
    resp = await mock_client.get("/posts/")
    assert "BulliExplorer" in resp.text


@pytest.mark.unit
async def test_post_list_has_nav(mock_client):
    resp = await mock_client.get("/posts/")
    assert 'id="mainNav"' in resp.text
    assert 'class="brand"' in resp.text


@pytest.mark.unit
async def test_post_list_has_masthead(mock_client):
    resp = await mock_client.get("/posts/")
    assert "masthead" in resp.text
    assert "site-heading" in resp.text


@pytest.mark.unit
async def test_post_list_empty_state(mock_client):
    resp = await mock_client.get("/posts/")
    assert "No posts yet" in resp.text


@pytest.mark.unit
async def test_post_list_links_theme_css(mock_client):
    resp = await mock_client.get("/posts/")
    assert "theme.css" in resp.text


@pytest.mark.unit
async def test_post_list_has_no_bootstrap_or_clean_blog(mock_client):
    """Phase 1 retires Bootstrap/Clean Blog entirely — no CDN scripts/links left."""
    resp = await mock_client.get("/posts/")
    assert "clean-blog" not in resp.text
    assert "bootstrap" not in resp.text.lower()
    assert "fonts.googleapis.com" not in resp.text
    assert "fontawesome" not in resp.text.lower()


@pytest.mark.unit
async def test_post_list_has_footer_copyright(mock_client):
    resp = await mock_client.get("/posts/")
    assert "BulliExplorer" in resp.text
    assert ("&copy;" in resp.text) or ("©" in resp.text)


# ---------------------------------------------------------------------------
# Post detail — 404
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_detail_unknown_slug_returns_404():
    transport = ASGITransport(app=_app(_404_session))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/posts/no-such-post")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Post detail — plain post (no route, no POIs) — regression tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_detail_returns_200(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert resp.status_code == 200


@pytest.mark.unit
async def test_post_detail_shows_title(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "A Gravel Day in the Black Forest" in resp.text


@pytest.mark.unit
async def test_post_detail_shows_summary_subheading(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "subheading" in resp.text
    assert "Single-track" in resp.text


@pytest.mark.unit
async def test_post_detail_shows_author(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "Sven" in resp.text


@pytest.mark.unit
async def test_post_detail_renders_body(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "Placeholder body" in resp.text


@pytest.mark.unit
async def test_post_detail_shows_tags(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "gravel" in resp.text
    assert "adventure" in resp.text


@pytest.mark.unit
async def test_post_detail_has_back_link(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "Back to all posts" in resp.text


@pytest.mark.unit
async def test_post_detail_links_theme_css(client_with_post):
    resp = await client_with_post.get("/posts/test-post")
    assert "theme.css" in resp.text


@pytest.mark.unit
async def test_post_detail_has_no_bootstrap_or_clean_blog(client_with_post):
    """Phase 1 retires Bootstrap/Clean Blog entirely — no CDN scripts/links left."""
    resp = await client_with_post.get("/posts/test-post")
    assert "clean-blog" not in resp.text
    assert "bootstrap" not in resp.text.lower()
    assert "fonts.googleapis.com" not in resp.text
    assert "fontawesome" not in resp.text.lower()


@pytest.mark.unit
async def test_post_without_route_has_no_map_container(client_with_post):
    """A post with no route must not render a map div — zero regression."""
    resp = await client_with_post.get("/posts/test-post")
    assert resp.status_code == 200
    assert "post-map" not in resp.text
    assert "route-stats" not in resp.text
    assert "maplibregl" not in resp.text


# ---------------------------------------------------------------------------
# Post detail — route present, no tiles URL → stats row only, no map widget
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_with_route_shows_stats_row(client_with_route):
    """Stats row is rendered when route data is present."""
    resp = await client_with_route.get("/posts/test-post")
    assert resp.status_code == 200
    assert "route-stats" in resp.text


@pytest.mark.unit
async def test_post_with_route_shows_distance(client_with_route):
    resp = await client_with_route.get("/posts/test-post")
    assert "68.0" in resp.text  # distance_km formatted as "68.0 km"


@pytest.mark.unit
async def test_post_with_route_shows_elevation_gain(client_with_route):
    resp = await client_with_route.get("/posts/test-post")
    assert "1420" in resp.text  # elevation_gain_m | int


@pytest.mark.unit
async def test_post_with_route_shows_duration(client_with_route):
    resp = await client_with_route.get("/posts/test-post")
    # 275 min = 4h 35min
    assert "4h" in resp.text
    assert "35" in resp.text


@pytest.mark.unit
async def test_post_with_route_no_tiles_url_hides_map(client_with_route):
    """Route present but TILES_URL empty → map div not rendered."""
    resp = await client_with_route.get("/posts/test-post")
    assert "post-map" not in resp.text
    assert "maplibregl" not in resp.text


# ---------------------------------------------------------------------------
# Post detail — route + tiles URL → full map renders
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_with_route_and_tiles_shows_map_container(client_with_route_and_tiles):
    """When tiles_url is set and route data is present, the map div is rendered."""
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert resp.status_code == 200
    assert "post-map" in resp.text


@pytest.mark.unit
async def test_post_with_route_and_tiles_loads_maplibre(client_with_route_and_tiles):
    """MapLibre vendor JS is included in the page when the map is active."""
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert "maplibre-gl.js" in resp.text
    assert "maplibre-gl.css" in resp.text
    assert "pmtiles.js" in resp.text
    assert "basemaps.js" in resp.text


@pytest.mark.unit
async def test_post_with_route_and_tiles_inlines_geojson(client_with_route_and_tiles):
    """Route GeoJSON is inlined as a JS variable in the page."""
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert "ROUTE_GEOJSON" in resp.text
    assert "LineString" in resp.text


@pytest.mark.unit
async def test_post_with_route_and_tiles_inlines_poi_geojson(client_with_route_and_tiles):
    """POI GeoJSON is inlined as a JS variable (FeatureCollection)."""
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert "POIS_GEOJSON" in resp.text
    assert "FeatureCollection" in resp.text
    assert "Wild Campsite" in resp.text
