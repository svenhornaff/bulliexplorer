"""Smoke tests for templates — no DB required.

Uses FastAPI dependency overrides to inject a mock session so DB-backed
routes can be tested without a running database.

post_detail now makes three execute() calls (post, route, POIs) in sequence;
the mock session helpers use side_effect to return different results per call.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import LineString, Point
from sqlalchemy.engine import Result

from app.core.db import get_db_session
from app.main import create_app

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

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
    updated_at = datetime.datetime(2025, 8, 24, 12, 0, tzinfo=datetime.UTC)
    cover_image = None
    tags = "gravel,adventure"
    body_html = "<p>Placeholder body.</p>"
    body_blocks = [{"type": "prose", "html": "<p>Placeholder body.</p>"}]
    is_draft = False


class _FakeOlderPost:
    """Second post — used for the homepage's 2-post "more rides" grid case."""

    id = 2
    slug = "older-post"
    title = "An Older Ride"
    summary = "The one before this one."
    published_date = datetime.date(2025, 7, 1)
    updated_at = datetime.datetime(2025, 7, 1, 12, 0, tzinfo=datetime.UTC)
    cover_image = None
    tags = "gravel"
    body_html = "<p>Older placeholder body.</p>"
    body_blocks = [{"type": "prose", "html": "<p>Older placeholder body.</p>"}]
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
    elevation_profile = [[0.0, 200.0], [34.0, 900.0], [68.0, 620.0]]


class _FakeRouteNoElevation(_FakeRoute):
    """A route whose source GPX had no elevation values at all — the
    chart must be omitted entirely, not rendered empty/flat
    (elevation_profile_chart.md Tier 1's graceful-omission requirement).
    """

    elevation_profile = None


class _FakePostWithRouteMapBlock(_FakePost):
    """A post whose body_blocks already includes a route-map block — the
    post_detail route/route_geojson context is what post.html actually
    renders from, so this only needs to include the block in the plan.
    """

    body_blocks = [
        {"type": "prose", "html": "<p>Placeholder body.</p>"},
        {"type": "route-map"},
    ]


class _FakeOlderRoute(_FakeRoute):
    """A second, distinct route belonging to _FakeOlderPost (post_id=2) —
    exercises the "more rides" grid card metadata added in Phase 1 of
    docs/dev/bulliexplorer_experience_2027.md, distinct from the hero's route
    so a test can tell the two chip sets apart.
    """

    id = 2
    post_id = 2
    name = "Older Ride Loop"
    distance_km = 42.0
    elevation_gain_m = 310.0
    elevation_loss_m = 305.0
    duration_minutes = 150.0  # 2h 30min


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
    """Post-list session: no posts (0-post homepage case).

    No second execute() call — post_list only queries a latest-post route
    when there is at least one post.
    """
    yield _session(_result(scalars_list=[]))


async def _one_post_session():
    """Post-list session: 1 post, no route (1-post homepage case: hero only)."""
    yield _session(
        _result(scalars_list=[_FakePost()]),  # posts query
        _result(scalars_list=[]),  # routes-for-all-listed-posts query
    )


async def _one_post_with_route_session():
    """Post-list session: 1 post that has a route (hero shows stat chips)."""
    yield _session(
        _result(scalars_list=[_FakePost()]),  # posts query
        _result(scalars_list=[_FakeRoute()]),  # routes-for-all-listed-posts query
    )


async def _two_posts_session():
    """Post-list session: 2 posts, neither has a route (2-post homepage case)."""
    yield _session(
        _result(scalars_list=[_FakePost(), _FakeOlderPost()]),  # posts query, newest first
        _result(scalars_list=[]),  # routes-for-all-listed-posts query
    )


async def _two_posts_both_with_routes_session():
    """Post-list session: 2 posts, both have routes — hero *and* grid card
    metadata (docs/dev/bulliexplorer_experience_2027.md Phase 1) exercised
    with distinct values so a test can tell which chip set is which.
    """
    yield _session(
        _result(scalars_list=[_FakePost(), _FakeOlderPost()]),  # posts query, newest first
        _result(scalars_list=[_FakeRoute(), _FakeOlderRoute()]),  # routes-for-all-listed-posts query
    )


async def _post_no_marker_with_route_session():
    """Post-detail session: post found with a route, but body_blocks is
    plain prose — no explicit [[route-map]] marker. This is the actual
    shape of every real post as of Phase 1 of
    docs/dev/bulliexplorer_experience_2027.md, and is what exercises the
    map-first *fallback* path (as opposed to _post_with_route_session,
    which uses _FakePostWithRouteMapBlock and so always exercised the
    marker-based path only — the fallback path had no direct test before
    this).
    """
    yield _session(
        _result(scalar=_FakePost()),
        _result(scalar=_FakeRoute()),
        _result(scalars_list=[]),  # POIs query
        _result(scalar=None),  # NearbyAmenity existence check (route is not None)
    )


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
    """Post-detail session: post found with route (no POIs, no amenities)."""
    yield _session(
        _result(scalar=_FakePostWithRouteMapBlock()),
        _result(scalar=_FakeRoute()),
        _result(scalars_list=[]),  # POIs query
        _result(scalar=None),  # NearbyAmenity existence check (route is not None)
    )


async def _post_with_route_and_pois_session():
    """Post-detail session: post found with route and one POI (no amenities)."""
    yield _session(
        _result(scalar=_FakePostWithRouteMapBlock()),
        _result(scalar=_FakeRoute()),
        _result(scalars_list=[_FakePOI()]),  # POIs query
        _result(scalar=None),  # NearbyAmenity existence check (route is not None)
    )


async def _post_with_route_no_elevation_session():
    """Post-detail session: route present but with no elevation_profile."""
    yield _session(
        _result(scalar=_FakePostWithRouteMapBlock()),
        _result(scalar=_FakeRouteNoElevation()),
        _result(scalars_list=[]),  # POIs query
        _result(scalar=None),  # NearbyAmenity existence check (route is not None)
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
async def client_with_one_post():
    """Homepage with exactly 1 post, no route — hero only, no "more rides"."""
    transport = ASGITransport(app=_app(_one_post_session))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client_with_one_post_and_route():
    """Homepage with 1 post that has a route — hero shows stat chips."""
    transport = ASGITransport(app=_app(_one_post_with_route_session))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client_with_two_posts():
    """Homepage with 2 posts — hero + "more rides" grid with 1 entry."""
    transport = ASGITransport(app=_app(_two_posts_session))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client_with_two_posts_both_with_routes():
    """Homepage with 2 posts, both with routes — hero *and* grid card stats."""
    transport = ASGITransport(app=_app(_two_posts_both_with_routes_session))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client_with_route_no_marker():
    """Post detail with a route but no explicit [[route-map]] marker — the
    fallback path, and the actual shape of every real post today."""
    with patch("app.routes.posts.get_settings") as mock_settings:
        mock_settings.return_value.tiles_url = ""
        mock_settings.return_value.is_production = False
        mock_settings.return_value.site_url = "https://bulliexplorer.com"
        mock_settings.return_value.legal_name = "Sven Hornaff"
        transport = ASGITransport(app=_app(_post_no_marker_with_route_session))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
async def client_with_route():
    """Post detail with a route but no tiles URL (stats row, no map widget)."""
    with patch("app.routes.posts.get_settings") as mock_settings:
        mock_settings.return_value.tiles_url = ""  # explicitly empty — map must not render
        mock_settings.return_value.is_production = False
        mock_settings.return_value.site_url = "https://bulliexplorer.com"
        mock_settings.return_value.legal_name = "Sven Hornaff"
        transport = ASGITransport(app=_app(_post_with_route_session))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
async def client_with_route_and_tiles():
    """Post detail with route + tiles URL configured → full map renders."""
    with patch("app.routes.posts.get_settings") as mock_settings:
        mock_settings.return_value.tiles_url = "pmtiles://https://example.com/tiles/black-forest.pmtiles"
        mock_settings.return_value.is_production = False
        mock_settings.return_value.site_url = "https://bulliexplorer.com"
        mock_settings.return_value.legal_name = "Sven Hornaff"
        transport = ASGITransport(app=_app(_post_with_route_and_pois_session))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
async def client_with_route_no_elevation():
    """Post detail with a route that has no elevation_profile."""
    with patch("app.routes.posts.get_settings") as mock_settings:
        mock_settings.return_value.tiles_url = ""
        mock_settings.return_value.is_production = False
        mock_settings.return_value.site_url = "https://bulliexplorer.com"
        mock_settings.return_value.legal_name = "Sven Hornaff"
        transport = ASGITransport(app=_app(_post_with_route_no_elevation_session))
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
async def test_post_list_has_site_intro(mock_client):
    """Homepage header: site-proposition text stack (site-heading/-tagline).
    Reopened per issue tracker to include a cover photo (site-intro-cover)
    with a dark overlay — this test only asserts the text-stack markup
    stays present, not the absence of a cover image."""
    resp = await mock_client.get("/posts/")
    assert "site-intro" in resp.text
    assert "site-heading" in resp.text
    assert "site-tagline" in resp.text


@pytest.mark.unit
async def test_post_list_empty_state(mock_client):
    """0-post homepage case: empty-state copy, no hero, no crash."""
    resp = await mock_client.get("/posts/")
    assert resp.status_code == 200
    assert "No posts yet" in resp.text
    assert "post-hero" not in resp.text
    assert "post-grid-heading" not in resp.text


# ---------------------------------------------------------------------------
# Homepage hero (latest post) — 1-post and 2-post cases (Phase 3, §6.1)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_home_one_post_shows_hero(client_with_one_post):
    """1-post case: hero renders with the post's title."""
    resp = await client_with_one_post.get("/posts/")
    assert resp.status_code == 200
    assert "post-hero" in resp.text
    assert "A Gravel Day in the Black Forest" in resp.text


@pytest.mark.unit
async def test_home_one_post_has_no_more_rides_section(client_with_one_post):
    """1-post case: no dangling "more rides" heading over an empty list."""
    resp = await client_with_one_post.get("/posts/")
    assert "post-grid-heading" not in resp.text
    assert "post-grid" not in resp.text


@pytest.mark.unit
async def test_home_one_post_no_route_hides_stat_chips(client_with_one_post):
    """Latest post without a Route: stat chips are simply absent, not empty/broken."""
    resp = await client_with_one_post.get("/posts/")
    assert "route-stats" not in resp.text


@pytest.mark.unit
async def test_home_one_post_with_route_shows_stat_chips(client_with_one_post_and_route):
    """Latest post with a Route: stat chips render in the hero."""
    resp = await client_with_one_post_and_route.get("/posts/")
    assert resp.status_code == 200
    assert "route-stats" in resp.text
    assert "68.0" in resp.text  # distance_km formatted
    assert "1420" in resp.text  # elevation_gain_m


@pytest.mark.unit
async def test_home_two_posts_shows_hero_and_grid(client_with_two_posts):
    """2-post case: latest post is the hero, remaining post appears in the grid."""
    resp = await client_with_two_posts.get("/posts/")
    assert resp.status_code == 200
    assert "post-hero" in resp.text
    assert "A Gravel Day in the Black Forest" in resp.text  # hero (newest)
    assert "post-grid-heading" in resp.text
    assert "An Older Ride" in resp.text  # grid (older)


@pytest.mark.unit
async def test_home_two_posts_older_post_not_in_hero(client_with_two_posts):
    """The older post's title must only appear once, inside the grid, not the hero."""
    resp = await client_with_two_posts.get("/posts/")
    assert resp.text.count("An Older Ride") == 1


@pytest.mark.unit
async def test_home_two_posts_grid_card_no_route_hides_stat_chips(client_with_two_posts):
    """Grid card metadata (docs/dev/bulliexplorer_experience_2027.md Phase 1):
    a listed post with no Route gets no chip row, not an empty one."""
    resp = await client_with_two_posts.get("/posts/")
    assert "route-stats--compact" not in resp.text


@pytest.mark.unit
async def test_home_two_posts_grid_card_shows_route_stats(
    client_with_two_posts_both_with_routes,
):
    """Grid card metadata: the older (non-hero) post's own route stats render
    in its grid card, using its own Route row — not the hero's."""
    resp = await client_with_two_posts_both_with_routes.get("/posts/")
    assert resp.status_code == 200
    assert "route-stats--compact" in resp.text
    assert "42.0" in resp.text  # older post's Route.distance_km
    assert "310" in resp.text  # older post's Route.elevation_gain_m


@pytest.mark.unit
async def test_home_two_posts_grid_card_uses_its_own_route_not_hero_route(
    client_with_two_posts_both_with_routes,
):
    """Regression guard for the routes_by_post_id lookup being keyed correctly
    — the hero's distance (68.0) must not leak into the grid card, and vice
    versa the grid card's distance (42.0) must not appear twice as if shared."""
    resp = await client_with_two_posts_both_with_routes.get("/posts/")
    assert resp.text.count("68.0") == 1
    assert resp.text.count("42.0") == 1


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
async def test_post_with_explicit_marker_keeps_prose_before_map(client_with_route):
    """Author-intent preservation (docs/dev/bulliexplorer_experience_2027.md
    Phase 1): a post that explicitly authors [[route-map]] mid-body
    (_FakePostWithRouteMapBlock, what client_with_route uses) must keep the
    map where the author put it — after the prose — not get force-hoisted
    to the top by the map-first fallback logic."""
    resp = await client_with_route.get("/posts/test-post")
    body = resp.text
    prose_pos = body.find("Placeholder body")
    map_pos = body.find("route-stats")
    assert prose_pos != -1
    assert map_pos != -1
    assert prose_pos < map_pos


@pytest.mark.unit
async def test_post_with_route_no_marker_renders_map_before_prose(client_with_route_no_marker):
    """Map-first fallback (docs/dev/bulliexplorer_experience_2027.md Phase 1):
    a post with a route but *no* explicit [[route-map]] marker — the actual
    shape of every real post today — must render its map/stats *before* the
    prose, not after. This is the concrete, code-verified version of the
    review's "trip page should read map-first" claim; the previous fallback
    rendered this exact case after all prose, the opposite of the goal."""
    resp = await client_with_route_no_marker.get("/posts/test-post")
    body = resp.text
    map_pos = body.find("route-stats")
    prose_pos = body.find("Placeholder body")
    assert map_pos != -1
    assert prose_pos != -1
    assert map_pos < prose_pos


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


@pytest.mark.unit
async def test_post_with_route_shows_elevation_chart_without_tiles(client_with_route):
    """Elevation profile chart (elevation_profile_chart.md Tier 1) renders
    even with no tiles_url — gated independently of the map guard, since a
    route can have elevation data without map tiles configured."""
    resp = await client_with_route.get("/posts/test-post")
    assert 'id="elevation-chart"' in resp.text
    assert "elevation-chart-wrap" in resp.text
    assert "/static/vendor/chart.js" in resp.text
    assert "/static/js/elevation-chart.js" in resp.text
    assert "BULLIEXPLORER_ELEVATION_DATA" in resp.text
    assert "elevationProfile" in resp.text


@pytest.mark.unit
async def test_post_with_route_no_elevation_data_omits_chart(client_with_route_no_elevation):
    """A route with elevation_profile=None (GPX had no elevation values)
    omits the chart entirely — no empty <canvas>, no vendor/behavior
    script tags loaded for nothing."""
    resp = await client_with_route_no_elevation.get("/posts/test-post")
    assert resp.status_code == 200
    assert 'id="elevation-chart"' not in resp.text
    assert "elevation-chart-wrap" not in resp.text
    assert "/static/vendor/chart.js" not in resp.text
    assert "/static/js/elevation-chart.js" not in resp.text


# ---------------------------------------------------------------------------
# Post detail — route + tiles URL → full map renders
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_route_stats_renders_map_before_elevation_chart(client_with_route_and_tiles):
    """Layout fix (docs/dev/fix_elevation_chart_below_map.md) — the map
    must render before the elevation chart in source order, not after.
    Both blocks stay independently gated (unchanged from
    elevation_profile_chart.md Tier 1); only their relative order in
    route_stats.html changed.
    """
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert resp.status_code == 200
    map_index = resp.text.index('id="map-wrap"')
    chart_index = resp.text.index('id="elevation-chart"')
    assert map_index < chart_index, "map must appear before the elevation chart in the rendered HTML"


@pytest.mark.unit
async def test_post_with_route_and_tiles_shows_cyclosm_toggle_independent_of_amenities(client_with_route_and_tiles):
    """CyclOSM optional layer toggle (docs/dev/cyclosm_optional_layer.md
    Phase 1) — an unconditional sibling to the amenity toggle, not gated
    on has_amenities: this fixture's own session mocks the NearbyAmenity
    existence check to None (see _post_with_route_and_pois_session), so
    has_amenities is False here — the amenity toggle correctly doesn't
    render, but the CyclOSM toggle must render anyway, since it's a
    third-party basemap overlay, not derived from this project's own
    discovered-amenity data.
    """
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert resp.status_code == 200
    assert 'id="cyclosm-toggle-input"' in resp.text
    assert "Show CyclOSM cycling map" in resp.text
    assert 'id="amenity-toggle-input"' not in resp.text, (
        "has_amenities is False for this fixture — the amenity toggle must not render"
    )


@pytest.mark.unit
async def test_post_with_route_no_tiles_omits_cyclosm_toggle(client_with_route):
    """No map at all (no tiles_url) — the CyclOSM toggle is nested inside
    the same {% if route_geojson and tiles_url %} guard as the map itself,
    so it must not render for a post with a route but no map widget.
    """
    resp = await client_with_route.get("/posts/test-post")
    assert resp.status_code == 200
    assert 'id="cyclosm-toggle-input"' not in resp.text


@pytest.mark.unit
async def test_post_with_route_and_tiles_shows_map_container(client_with_route_and_tiles):
    """When tiles_url is set and route data is present, the map div is rendered."""
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert resp.status_code == 200
    assert "post-map" in resp.text


@pytest.mark.unit
async def test_post_with_route_and_tiles_loads_maplibre(client_with_route_and_tiles):
    """MapLibre vendor JS, plus the extracted post-map.js behavior file
    (F4, docs/dev/review_17SEP2026.md), is included when the map is active.
    """
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert "maplibre-gl.js" in resp.text
    assert "maplibre-gl.css" in resp.text
    assert "pmtiles.js" in resp.text
    assert "basemaps.js" in resp.text
    assert "/static/js/post-map.js" in resp.text


@pytest.mark.unit
async def test_post_with_route_and_tiles_inlines_geojson(client_with_route_and_tiles):
    """Route GeoJSON is inlined into window.BULLIEXPLORER_MAP_DATA — the
    data-only inline block that remains in post.html after F4's extraction
    of behavior into static/js/post-map.js (docs/dev/review_17SEP2026.md).
    """
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert "BULLIEXPLORER_MAP_DATA" in resp.text
    assert "routeGeojson" in resp.text
    assert "LineString" in resp.text


@pytest.mark.unit
async def test_post_with_route_and_tiles_inlines_poi_geojson(client_with_route_and_tiles):
    """POI GeoJSON is inlined into window.BULLIEXPLORER_MAP_DATA (FeatureCollection)."""
    resp = await client_with_route_and_tiles.get("/posts/test-post")
    assert "poisGeojson" in resp.text
    assert "FeatureCollection" in resp.text
    assert "Wild Campsite" in resp.text


@pytest.mark.unit
def test_post_map_js_includes_cycling_layers():
    """cyclingLayers() (gis_cycling_upgrade.md Phase 1) is defined and
    appended to both the initial style and the theme-swap setStyle call.

    Lives in static/js/post-map.js since F4's extraction
    (docs/dev/review_17SEP2026.md) — no longer part of the per-request
    HTML response, so this test reads the static file directly.
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    assert "function cyclingLayers(flavor)" in js
    # Appended via .concat(...) in both places the base style is built —
    # initial load and the theme-change setStyle rebuild — not replacing
    # basemaps.layers()'s own array.
    assert js.count(".concat(cyclingLayers(") == 2


@pytest.mark.unit
def test_post_map_js_defines_locality_label_priority_split():
    """adjustLocalityLabelPriority() (fix_label_priority_and_
    trail_differentiation.md Phase 1-2) splits the basemap's single
    "places_locality" layer into two: real settlement names (kept
    exactly as the native library defines them) and hyper-local
    field/forest micro-toponyms (kind_detail=="locality", deferred
    behind a minzoom so they don't compete with peaks at whole-route
    zoom — real tile inspection over Siebengebirge/Königswinter found
    real settlements distinguished from cadastral names only by
    kind_detail, not by kind, so a blanket minzoom raise on the whole
    layer would have wrongly suppressed real town names too).
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    assert "function adjustLocalityLabelPriority(layers)" in js
    assert '"places_locality_micro_toponym"' in js
    assert '["!=", ["get", "kind_detail"], "locality"]' in js
    assert '["==", ["get", "kind_detail"], "locality"]' in js
    # Wired into both style-build call sites (initial + theme swap),
    # same as cyclingLayers()/peakElevationLayer() above it.
    assert js.count("adjustLocalityLabelPriority(") == 3  # 1 definition + 2 call sites


@pytest.mark.unit
def test_post_map_js_locality_filters_never_splice_vendored_legacy_filter():
    """Real regression, reproduced with a real headless browser before
    this fix: the vendored basemaps library's own "places_locality"
    filter is legacy MapLibre syntax (["==","kind","locality"], a bare
    property-name string), not the modern expression syntax
    (["==",["get","kind"],"locality"]) used everywhere else in this
    file. Splicing that legacy filter directly into an "all" alongside
    a modern ["get", ...] expression produces a filter MapLibre's style
    validator rejects outright ("filter[2][1]: string expected, array
    found") — and since this is one layer inside the single style
    object passed to the Map constructor, that validation failure took
    down the ENTIRE style load: base tiles gone, map area a blank void,
    while elevation-chart.js (a separate script) kept working fine.
    Confirmed with a real headless browser: exactly this console error,
    twice, before the fix; zero errors and 15 real tile requests (200/
    206) after it.

    Regression guard: adjustLocalityLabelPriority() must never embed
    the raw `layer.filter` value (the vendored, legacy-syntax filter)
    inside either of the two filters it constructs — only the
    explicit, self-built modern-expression `KIND_IS_LOCALITY` constant.
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    start = js.index("function adjustLocalityLabelPriority(layers)")
    end = js.index("\n    }", js.index("function peakElevationLayer", start))
    func_body = js[start:end]
    assert "KIND_IS_LOCALITY" in func_body, "expected an explicit modern-expression kind check"
    assert "layer.filter" not in func_body, (
        "must not splice the vendored layer's own (legacy-syntax) filter into a new "
        "filter array alongside modern [get, ...] expressions"
    )


@pytest.mark.unit
def test_post_map_js_includes_peak_elevation_layer():
    """peakElevationLayer() (fix_peaks_cablecars_amenity_review.md
    Phase 1) is defined and appended to both the initial style and the
    theme-swap setStyle call, same pattern as cyclingLayers() above.
    Filtered on kind=="peak" against the real "pois" source-layer
    (confirmed via direct tile inspection — no "physical_point" layer
    exists in this basemap's actual schema, contrary to the doc's
    initial research-phase assumption).
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    assert "function peakElevationLayer(flavor)" in js
    assert '"source-layer": "pois"' in js
    assert '["==", ["get", "kind"], "peak"]' in js
    assert js.count(".concat([peakElevationLayer(") == 2


@pytest.mark.unit
def test_post_map_js_peak_elevation_layer_never_competes_for_collision():
    """Real regression, found live in production after the filter-
    dialect crash fix: peaks stopped rendering at all (not just the
    elevation text — the native "pois" layer's own icon+name label too)
    once this layer existed at all. Ruled out an "elevation" vs "ele"
    property-name mismatch by checking real decoded tile bytes for
    Feldberg/Seebuck/Baldenweger Buck directly (the property genuinely
    is "elevation"). Isolated the real cause with a real headless
    browser: rebuilding the style incrementally (stock vendor layers
    alone render Feldberg's peak; adding this layer makes it disappear,
    with every other addition held constant) proved this layer's own
    presence was winning MapLibre's cross-layer collision budget over
    the native "pois" layer's peak icon+name for the same feature,
    hiding the more important native label.

    A first attempted fix (an explicit `symbol-sort-key` deliberately
    set numerically worse than "pois"'s own fallback) was tested with
    the same method and disproven — MapLibre's cross-layer collision
    priority didn't behave the way that theory assumed. The verified
    fix: `text-allow-overlap: true` + `text-ignore-placement: true`,
    removing this layer from the collision system entirely rather than
    trying to out-rank "pois" within it — confirmed with the literal
    extracted function from this file (not a manual reconstruction):
    "pois" back to rendering its peak, this layer still rendering its
    own elevation text at the same time.

    Regression guard: both properties must be present together, not
    just one — either alone leaves this layer partially back in the
    collision system.
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    start = js.index("function peakElevationLayer(flavor)")
    end = js.index("\n    }", start)
    func_body = js[start:end]
    assert '"text-allow-overlap": true' in func_body, (
        "must not participate in MapLibre's collision system — confirmed live to "
        "suppress the native pois layer's own peak icon+name when it does"
    )
    assert '"text-ignore-placement": true' in func_body


@pytest.mark.unit
def test_post_map_js_peak_elevation_layer_matches_native_prominence_gate():
    """Regression fix #3, found live in production by a real side-by-
    side comparison against the OSM reference at a dense real location
    (Siebengebirge — Petersberg/Großer Ölberg/Drachenfels): once
    regression fix #2 stopped this layer from hiding the native peak
    label, it introduced a different real problem — dozens of orphaned
    bare elevation numbers with no icon/name, for minor unnamed
    elevation points the native "pois" layer deliberately doesn't
    consider prominent enough to label yet.

    Real mechanism: the native layer gates on each feature's own
    `min_zoom` property, a per-feature prominence value baked into the
    tile data (real summits earn a low enough min_zoom to show at a
    given zoom; minor points don't). This layer's filter had no
    equivalent gate, so it fired for every peak feature regardless of
    that feature's own prominence.

    Fix: add the identical `zoom >= feature.min_zoom` gate the native
    layer already uses. Verified with a real headless browser at both
    the original regression #2 location (Feldberg, sparse — still
    correct) and this denser one (Siebengebirge — zero orphaned labels
    once isolated from unrelated MapLibre collision crowding, which is
    a separate, narrower, pre-existing trade-off of this layer's
    text-allow-overlap design in busy areas specifically, not a bug in
    this gate).
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    start = js.index("function peakElevationLayer(flavor)")
    end = js.index("\n    }", start)
    func_body = js[start:end]
    assert '[">=", ["zoom"], ["+", ["get", "min_zoom"], 0]]' in func_body, (
        "must gate on each feature's own min_zoom, matching the native pois layer's "
        "own prominence filter — confirmed live to otherwise produce orphaned bare "
        "elevation numbers for minor, unnamed elevation points"
    )


@pytest.mark.unit
def test_post_map_js_amenity_categories_include_cafe_and_bike_repair_station():
    """cafe/bike_repair_station (fix_peaks_cablecars_amenity_review.md
    Phase 2) have both a marker colour and an icon path — a category
    present in one but not the other would silently fall back to a
    plain dot or the wrong colour rather than erroring, so both need an
    explicit regression check, not just "the key exists somewhere".
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    colours_start = js.index("const CATEGORY_COLOURS = {")
    colours_end = js.index("};", colours_start)
    colours_body = js[colours_start:colours_end]
    icons_start = js.index("const CATEGORY_ICON_PATHS = {")
    icons_end = js.index("};", icons_start)
    icons_body = js[icons_start:icons_end]
    for category in ("cafe", "bike_repair_station"):
        assert f"{category}:" in colours_body, f"{category} missing a marker colour"
        assert f"{category}:" in icons_body, f"{category} missing an icon path"


@pytest.mark.unit
def test_post_map_js_defines_hover_sync_interpolation():
    """interpolateAlongRoute() (elevation_profile_chart.md Tier 2) exists
    in post-map.js and is wired to the chart-hover CustomEvents
    elevation-chart.js dispatches.

    No JS test runner exists in this project (AGENTS.md: no build step,
    no npm) — tests/unit/test_templates.py's existing convention for this
    file is reading the static source and asserting structural facts
    about it (see test_post_map_js_includes_cycling_layers above), which
    this test follows. The interpolation math itself (midpoint,
    zero/negative/beyond-total-distance edge cases, multi-segment
    accumulation) was verified correct via a standalone Node script
    during development — not part of CI, since this project has no Node
    runtime dependency anywhere else and shouldn't gain one just for this.
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    assert "function interpolateAlongRoute(coordinates, targetDistanceKm)" in js
    # Never upsamples/crashes on a degenerate route — explicit guards for
    # <2 points, zero, and negative distance.
    assert "coordinates.length < 2" in js
    assert "targetDistanceKm <= 0" in js
    # Wired to the events elevation-chart.js dispatches (Tier 2's
    # "chart leads, map follows" one-way design — map-hover-syncs-chart
    # is explicitly out of scope per the Tier 2 doc).
    assert 'addEventListener("bulliexplorer:elevationhover"' in js
    assert 'addEventListener("bulliexplorer:elevationhoverend"' in js


@pytest.mark.unit
def test_elevation_chart_js_defines_incline_color_coding():
    """Per-segment incline color-coding (elevation_profile_chart.md
    Tier 3) exists and is wired into Chart.js's native `segment`
    scriptable option — no plugin needed beyond what Tier 1 vendors.

    Same testing convention as Tier 1/2 (no JS test runner in this
    project, AGENTS.md): read the static source, assert structural
    facts. The color-bucketing/smoothing math itself (flat → green,
    steady climbs at known grades → correct green/amber/red bucket,
    smoothing damps point-to-point GPS noise) was verified correct via
    a standalone Node script during development, cross-checked against
    Feldberg Summit Loop's real synced elevation_profile — not part of
    CI, same reasoning as Tier 2's interpolation math.
    """
    js = (STATIC_DIR / "js" / "elevation-chart.js").read_text(encoding="utf-8")
    assert "function smoothElevations(profile, window)" in js
    assert "function inclineColorForGradient(gradientPercent, alpha)" in js
    assert "function gradientPercentAt(profile, smoothedElevations, index)" in js
    assert "segment:" in js
    assert "borderColor: function (ctx)" in js
    # Cutoffs tuned against a real route, not arbitrary — documented in
    # the source comment as well as here.
    assert "INCLINE_GREEN_MAX = 5" in js
    assert "INCLINE_AMBER_MAX = 10" in js


@pytest.mark.unit
def test_elevation_chart_js_fills_area_under_incline_colored_line():
    """fill must be enabled (not `false`) and segment.backgroundColor
    must exist alongside segment.borderColor, or the incline coloring
    only ever paints a thin 2px line with nothing underneath — at route
    scale (thousands of km) that reads as "just green" even on a route
    with a real climb, since only a hairline would show any color at
    all. Regression coverage for exactly this gap.
    """
    js = (STATIC_DIR / "js" / "elevation-chart.js").read_text(encoding="utf-8")
    assert 'fill: "origin"' in js
    assert "fill: false" not in js
    assert "segment.backgroundColor" in js or "backgroundColor: function (ctx)" in js
    assert "function withAlpha(hexColor, alpha)" in js
    # The fill must reuse the same three incline colors as the line
    # (via withAlpha), not a second hardcoded color table.
    dataset_start = js.index('type: "line"')
    segment_start = js.index("segment: {", dataset_start)
    segment_end = js.index("},\n        },", segment_start)
    segment_body = js[segment_start:segment_end]
    assert "backgroundColor: function (ctx)" in segment_body
    assert "inclineColorForGradient(gradient, 0.3)" in segment_body


@pytest.mark.unit
def test_elevation_chart_js_has_tight_x_axis_and_start_end_markers():
    """Tight X-axis (chart max = route's actual total distance, no
    auto-padding) and start/end marker dots — both elevation_profile_
    chart.md Tier 3 scope items independent of the incline coloring.
    """
    js = (STATIC_DIR / "js" / "elevation-chart.js").read_text(encoding="utf-8")
    assert "max: totalDistanceKm" in js
    assert "grace: 0" in js
    assert "elevationStartEndMarkers" in js
    assert '["A", "B"]' in js


@pytest.mark.unit
def test_elevation_chart_js_tooltip_shows_incline_not_surface():
    """Hover tooltip shows distance/elevation/cumulative-gain/incline —
    explicitly not surface or way-type, per Tier 3's own callout that
    this project's tile data doesn't reliably carry that
    (gis_cycling_upgrade.md Phase 0).
    """
    js = (STATIC_DIR / "js" / "elevation-chart.js").read_text(encoding="utf-8")
    assert "climbed so far" in js
    assert "% grade" in js
    # The tooltip's own label callback builds only elevation/gain/grade
    # lines — checked by isolating that function's body, not the whole
    # file, since a comment elsewhere legitimately explains *why*
    # surface/way-type is deliberately absent (mentioning the word).
    tooltip_label_start = js.index("label: function (item) {")
    tooltip_label_end = js.index("},", tooltip_label_start)
    tooltip_label_body = js[tooltip_label_start:tooltip_label_end].lower()
    assert "surface" not in tooltip_label_body
    assert "way-type" not in tooltip_label_body and "waytype" not in tooltip_label_body


@pytest.mark.unit
async def test_post_with_route_passes_distance_km_to_elevation_chart(client_with_route):
    """route.distance_km is passed alongside elevation_profile so the
    chart's X-axis can be set to the route's exact total distance
    (Tier 3's tight-axis requirement needs this value)."""
    resp = await client_with_route.get("/posts/test-post")
    assert "distanceKm" in resp.text
    assert "68.0" in resp.text  # _FakeRoute.distance_km


@pytest.mark.unit
def test_post_map_js_cycling_layers_use_kind_detail():
    """Filters on kind_detail (the OSM highway=* value), not kind itself —
    Phase 0's tile-inspection finding: kind only has 5 broad buckets, the
    real cycleway/path/track distinction lives on kind_detail.
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    assert '"kind_detail"' in js
    assert '"cycleway"' in js
    # Both cycling layers read from the "roads" source-layer confirmed
    # present via direct tile inspection in Phase 0.
    assert js.count('"source-layer": "roads"') >= 2


# ---------------------------------------------------------------------------
# CyclOSM optional raster layer (docs/dev/cyclosm_optional_layer.md)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_post_map_js_cyclosm_not_added_at_initial_map_construction():
    """The core design principle (the doc's own framing): CyclOSM is
    never fetched, never initialized, never touched at all unless the
    reader explicitly opts in. Confirmed at the source level — the Map
    constructor's initial `style.sources`/`style.layers` must not
    reference cyclosm at all; only addCyclosmLayer() (called later, only
    from the toggle's change listener) may add it.
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    ctor_start = js.index("const map = new maplibregl.Map({")
    ctor_end = js.index("\n    });", ctor_start)
    ctor_body = js[ctor_start:ctor_end]
    assert "cyclosm" not in ctor_body.lower(), (
        "CyclOSM must not appear in the Map constructor's initial style — "
        "toggling on is the only thing allowed to add it"
    )


@pytest.mark.unit
def test_post_map_js_cyclosm_transform_request_scopes_only_cyclosm_host():
    """transformRequest must return every non-CyclOSM URL unmodified
    (`{ url: url }`, no signal) — vector tiles/sprites/glyphs must behave
    exactly as before this feature existed. Only CyclOSM URLs get the
    AbortController + timeout treatment.

    The timeout mechanism itself was verified empirically against this
    exact vendored MapLibre build (v4.7.1) with a real headless browser
    before relying on it here: a caller-supplied AbortSignal returned
    from transformRequest genuinely aborts the fetch (confirmed via a
    non-routable host, abort fired at ~3013ms against a 3000ms timeout,
    zero map error events, zero resolved-tile events) — this test checks
    the source wiring, not the browser mechanism itself, which isn't
    something a Python unit test can exercise.
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    fn_start = js.index("function transformRequest(url)")
    fn_end = js.index("\n    }", fn_start)
    fn_body = js[fn_start:fn_end]
    assert "if (url.indexOf(CYCLOSM_HOST) === -1) return { url: url };" in fn_body
    assert "new AbortController()" in fn_body
    assert "controller.abort()" in fn_body
    assert "CYCLOSM_TIMEOUT_MS" in fn_body
    assert "signal: controller.signal" in fn_body


@pytest.mark.unit
def test_post_map_js_cyclosm_timeout_is_a_few_seconds_not_a_browser_default():
    """docs/dev/cyclosm_optional_layer.md: "A tile request timeout (short
    — a few seconds, this is a visual nice-to-have, not content worth
    waiting on)" — not the browser's own multi-minute connection default.
    Pinned as a concrete, testable range rather than just "some number".
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    match = re.search(r"CYCLOSM_TIMEOUT_MS\s*=\s*(\d+);", js)
    assert match is not None, "CYCLOSM_TIMEOUT_MS constant not found"
    timeout_ms = int(match.group(1))
    assert 1000 <= timeout_ms <= 10000, f'CYCLOSM_TIMEOUT_MS={timeout_ms} is not "a few seconds"'


@pytest.mark.unit
def test_post_map_js_add_cyclosm_layer_inserts_below_route_casing():
    """Layer ordering (the doc's explicit requirement): CyclOSM sits
    below the route line/POI/amenity layers, all of which stay on top
    regardless of which basemap is active underneath. addLayer()'s
    second argument is MapLibre's own "insert before this id" mechanism
    — inserting before "route-casing" (the first user-content layer
    added in the "load" handler) is what achieves this, confirmed live
    with a real headless browser (cyclosm-raster at index 75, immediately
    before route-casing at 76 and route-line at 77, out of 81 total
    layers).
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    fn_start = js.index("function addCyclosmLayer(mapInstance)")
    fn_end = js.index("\n    }", fn_start)
    fn_body = js[fn_start:fn_end]
    assert '"route-casing"' in fn_body
    assert "CYCLOSM_LAYER_ID" in fn_body
    assert 'type: "raster", source: CYCLOSM_SOURCE_ID }, "route-casing"' in fn_body


@pytest.mark.unit
def test_post_map_js_add_cyclosm_layer_is_idempotent():
    """Same reasoning as addAmenitiesSourceAndLayers's own idempotency —
    must be a no-op if the source already exists, since this is also
    called after a theme-swap setStyle() where transformStyle's carry-
    over already restored both the source and the layer.
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    fn_start = js.index("function addCyclosmLayer(mapInstance)")
    fn_end = js.index("\n    }", fn_start)
    fn_body = js[fn_start:fn_end]
    assert "if (mapInstance.getSource(CYCLOSM_SOURCE_ID)) return;" in fn_body


@pytest.mark.unit
def test_post_map_js_remove_cyclosm_layer_removes_layer_before_source():
    """Toggling off removes the layer entirely, not just hides it (the
    doc's explicit requirement — no lingering raster tile requests
    continuing in the background). MapLibre throws if a source is
    removed while still referenced by a layer, so the layer must be
    removed first — checked here as an ordering assertion, not just
    "both calls exist somewhere".
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    fn_start = js.index("function removeCyclosmLayer(mapInstance)")
    fn_end = js.index("\n    }", fn_start)
    fn_body = js[fn_start:fn_end]
    layer_idx = fn_body.index("removeLayer(CYCLOSM_LAYER_ID)")
    source_idx = fn_body.index("removeSource(CYCLOSM_SOURCE_ID)")
    assert layer_idx < source_idx, "the layer must be removed before its source"


@pytest.mark.unit
def test_post_map_js_cyclosm_source_has_required_attribution():
    """Required by the tile usage policy, not optional (the doc's own
    framing) — CyclOSM/OpenStreetMap-France attribution must be present
    on the source definition itself, so MapLibre's AttributionControl
    picks it up automatically (confirmed live: shown while the layer is
    active, gone once removed — no separate control-manipulation code
    needed).
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    fn_start = js.index("function addCyclosmLayer(mapInstance)")
    fn_end = js.index("\n    }", fn_start)
    fn_body = js[fn_start:fn_end]
    assert "cyclosm.org" in fn_body
    assert "openstreetmap.org" in fn_body
    assert "attribution:" in fn_body


@pytest.mark.unit
def test_post_map_js_theme_swap_carries_cyclosm_below_route_layers():
    """Theme-swap (setStyle()) tears down every source/layer — CyclOSM
    needs the same carry-over treatment already proven for route/
    amenities, but with a different required z-order: this project's
    own layers get appended *after* nextStyle.layers, while cyclosm-
    raster must stay *below* route-casing/route-line/amenities even
    across a theme swap. Checked as an ordering assertion in the actual
    concat expression, not just "cyclosm is mentioned somewhere in
    transformStyle" — confirmed live with a real headless browser
    (CyclOSM attribution present before and after a real theme toggle
    click, zero console errors).
    """
    js = (STATIC_DIR / "js" / "post-map.js").read_text(encoding="utf-8")
    fn_start = js.index("transformStyle: function (previousStyle, nextStyle)")
    fn_end = js.index("\n          },", fn_start)
    fn_body = js[fn_start:fn_end]
    assert "cyclosmActive" in fn_body
    assert "cyclosmCarriedLayers" in fn_body
    concat_idx = fn_body.index("layers: nextStyle.layers.concat(cyclosmCarriedLayers).concat(")
    assert concat_idx != -1, "cyclosmCarriedLayers must be concatenated before the route/amenities carriedLayers"
