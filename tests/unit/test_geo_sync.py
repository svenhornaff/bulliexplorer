"""Unit tests for app/services/geo_sync.py — no DB required.

Tests cover the pure helper functions:
- _resolve_gpx_path: absolute vs relative path handling.
- _resolve_poi_location: lat/lng → Shapely Point, None when no coords.
- _parse_gpx: fixture GPX file produces correct geometry and stats.
- _geocode: Nominatim client behaviour (mock HTTP transport).
- _resolve_poi_location_with_geocoding: priority logic, mock _geocode.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from shapely.geometry import Point

import app.services.geo_sync as _geo_module
from app.models.post_schema import PoiFrontmatter
from app.services.geo_sync import (  # noqa: PLC2701
    _geocode,
    _parse_gpx,
    _resolve_gpx_path,
    _resolve_poi_location,
    _resolve_poi_location_with_geocoding,
)

# Minimal valid GPX with two track points and elevation/timestamp data.
# Distance ≈ 11.13 km (straight-line Haversine between the two points).
# Elevation gain = 100 m (climbs from 200 m to 300 m).
# Duration = 60 minutes (timestamps 1 hour apart).
_MINIMAL_GPX = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="48.0" lon="8.0">
        <ele>200.0</ele>
        <time>2025-06-01T08:00:00Z</time>
      </trkpt>
      <trkpt lat="48.1" lon="8.1">
        <ele>300.0</ele>
        <time>2025-06-01T09:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""

# GPX without timestamps — duration_minutes should be None.
_NO_TIMESTAMP_GPX = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="48.0" lon="8.0"><ele>200.0</ele></trkpt>
      <trkpt lat="48.1" lon="8.1"><ele>300.0</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


# ---------------------------------------------------------------------------
# _resolve_gpx_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_gpx_path_relative(tmp_path):
    """A relative path is resolved against content_dir."""
    result = _resolve_gpx_path("my-route.gpx", tmp_path)
    assert result == (tmp_path / "my-route.gpx").resolve()


@pytest.mark.unit
def test_resolve_gpx_path_absolute():
    """A non-static absolute path is returned unchanged."""
    abs_path = "/some/absolute/path/route.gpx"
    result = _resolve_gpx_path(abs_path, Path("/content/posts"))
    assert result == Path(abs_path)


@pytest.mark.unit
def test_resolve_gpx_path_sveltia_public_path(tmp_path):
    """A /static/... path (from Sveltia's file widget) resolves relative to
    the project root (content_dir.parent.parent), not the filesystem root."""
    # Simulate: project_root = tmp_path, content_dir = tmp_path/content/posts
    content_dir = tmp_path / "content" / "posts"
    content_dir.mkdir(parents=True)

    result = _resolve_gpx_path("/static/uploads/my-route.gpx", content_dir)
    expected = (tmp_path / "static" / "uploads" / "my-route.gpx").resolve()
    assert result == expected


# ---------------------------------------------------------------------------
# _resolve_poi_location
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_poi_location_with_coords():
    """A POI with explicit lat/lng returns a Shapely Point (lng, lat order)."""
    poi = PoiFrontmatter(name="Summit", category="viewpoint", lat=48.05, lng=8.05)
    point = _resolve_poi_location(poi)
    assert point is not None
    assert isinstance(point, Point)
    assert point.x == pytest.approx(8.05)  # longitude → x
    assert point.y == pytest.approx(48.05)  # latitude  → y


@pytest.mark.unit
def test_resolve_poi_location_no_coords():
    """A POI with no lat/lng returns None (geocoding path — Phase 3)."""
    poi = PoiFrontmatter(name="Café", category="restaurant", place_query="Café Sonnenberg")
    assert _resolve_poi_location(poi) is None


@pytest.mark.unit
def test_resolve_poi_location_partial_lat_only():
    """Only lat set (no lng) → None — both are required for a valid point."""
    poi = PoiFrontmatter(name="Partial", category="other", lat=48.0)
    assert _resolve_poi_location(poi) is None


@pytest.mark.unit
def test_resolve_poi_location_partial_lng_only():
    """Only lng set (no lat) → None."""
    poi = PoiFrontmatter(name="Partial", category="other", lng=8.0)
    assert _resolve_poi_location(poi) is None


# ---------------------------------------------------------------------------
# _parse_gpx
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_gpx_geometry(tmp_path):
    """Parsed LineString contains the correct track points."""
    gpx_file = tmp_path / "test.gpx"
    gpx_file.write_text(_MINIMAL_GPX, encoding="utf-8")

    result = _parse_gpx("test.gpx", tmp_path)
    assert result is not None
    linestring, _dist, _gain, _loss, _dur = result

    coords = list(linestring.coords)
    assert len(coords) == 2
    assert coords[0] == pytest.approx((8.0, 48.0))
    assert coords[1] == pytest.approx((8.1, 48.1))


@pytest.mark.unit
def test_parse_gpx_distance(tmp_path):
    """Parsed distance_km is a positive float."""
    gpx_file = tmp_path / "test.gpx"
    gpx_file.write_text(_MINIMAL_GPX, encoding="utf-8")

    result = _parse_gpx("test.gpx", tmp_path)
    assert result is not None
    _, distance_km, _, _, _ = result

    # 2D straight-line between (8.0,48.0) and (8.1,48.1) is roughly 12–13 km.
    assert distance_km > 0.0
    assert 10.0 < distance_km < 15.0


@pytest.mark.unit
def test_parse_gpx_elevation_gain(tmp_path):
    """Parsed elevation gain matches the track's climb (200 m → 300 m = +100 m)."""
    gpx_file = tmp_path / "test.gpx"
    gpx_file.write_text(_MINIMAL_GPX, encoding="utf-8")

    result = _parse_gpx("test.gpx", tmp_path)
    assert result is not None
    _, _, elevation_gain_m, elevation_loss_m, _ = result

    assert elevation_gain_m == pytest.approx(100.0)
    assert elevation_loss_m == pytest.approx(0.0)


@pytest.mark.unit
def test_parse_gpx_duration(tmp_path):
    """Duration is 60 minutes when timestamps span exactly 1 hour."""
    gpx_file = tmp_path / "test.gpx"
    gpx_file.write_text(_MINIMAL_GPX, encoding="utf-8")

    result = _parse_gpx("test.gpx", tmp_path)
    assert result is not None
    _, _, _, _, duration_minutes = result

    assert duration_minutes is not None
    assert duration_minutes == pytest.approx(60.0)


@pytest.mark.unit
def test_parse_gpx_no_timestamps_duration_none(tmp_path):
    """When GPX has no timestamps, duration_minutes is None."""
    gpx_file = tmp_path / "no_ts.gpx"
    gpx_file.write_text(_NO_TIMESTAMP_GPX, encoding="utf-8")

    result = _parse_gpx("no_ts.gpx", tmp_path)
    assert result is not None
    _, _, _, _, duration_minutes = result
    assert duration_minutes is None


@pytest.mark.unit
def test_parse_gpx_file_not_found_returns_none(tmp_path):
    """A non-existent GPX file returns None (logged, not raised)."""
    result = _parse_gpx("does-not-exist.gpx", tmp_path)
    assert result is None


@pytest.mark.unit
def test_parse_gpx_invalid_xml_returns_none(tmp_path):
    """A file that is not valid GPX/XML returns None."""
    bad = tmp_path / "bad.gpx"
    bad.write_text("this is not xml at all <unclosed", encoding="utf-8")

    result = _parse_gpx("bad.gpx", tmp_path)
    assert result is None


@pytest.mark.unit
def test_parse_gpx_single_point_returns_none(tmp_path):
    """A GPX with only one track point returns None (can't form a LineString)."""
    one_point = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="48.0" lon="8.0"><ele>200.0</ele></trkpt>
  </trkseg></trk>
</gpx>
"""
    gpx_file = tmp_path / "one.gpx"
    gpx_file.write_text(one_point, encoding="utf-8")
    result = _parse_gpx("one.gpx", tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# Rate-limit reset
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Reset the module-level geocode timestamp so tests never sleep."""
    _geo_module._last_geocode_time = 0.0  # noqa: SLF001 — module-level rate-limit state
    yield
    _geo_module._last_geocode_time = 0.0  # noqa: SLF001


# ---------------------------------------------------------------------------
# _geocode — Nominatim HTTP client tests (mock transport, no real network)
# ---------------------------------------------------------------------------


class _JsonTransport(httpx.AsyncBaseTransport):
    """Mock httpx transport that returns a fixed JSON response."""

    def __init__(self, payload: list | dict, status_code: int = 200) -> None:
        self._payload = payload
        self._status_code = status_code
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code, json=self._payload)


class _ErrorTransport(httpx.AsyncBaseTransport):
    """Mock httpx transport that raises a network error."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")


@pytest.mark.unit
async def test_geocode_returns_lat_lon_on_success():
    """A valid Nominatim response yields (lat, lon) as floats."""
    transport = _JsonTransport([{"lat": "48.05", "lon": "8.12", "display_name": "Somewhere"}])
    async with httpx.AsyncClient(transport=transport) as client:
        result = await _geocode("Café Sonnenberg, Freiburg", client)

    assert result is not None
    lat, lon = result
    assert lat == pytest.approx(48.05)
    assert lon == pytest.approx(8.12)


@pytest.mark.unit
async def test_geocode_empty_results_returns_none():
    """An empty Nominatim result list returns None (logged, not raised)."""
    transport = _JsonTransport([])
    async with httpx.AsyncClient(transport=transport) as client:
        result = await _geocode("asdkfjasldkfj", client)

    assert result is None


@pytest.mark.unit
async def test_geocode_network_error_returns_none():
    """A network error returns None (logged, not raised)."""
    async with httpx.AsyncClient(transport=_ErrorTransport()) as client:
        result = await _geocode("somewhere", client)

    assert result is None


@pytest.mark.unit
async def test_geocode_http_error_returns_none():
    """A 500 response returns None (logged, not raised)."""
    transport = _JsonTransport({"error": "server error"}, status_code=500)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await _geocode("somewhere", client)

    assert result is None


@pytest.mark.unit
async def test_geocode_sends_user_agent_header():
    """Every Nominatim request carries the required User-Agent header."""
    transport = _JsonTransport([{"lat": "48.0", "lon": "8.0"}])
    async with httpx.AsyncClient(transport=transport) as client:
        await _geocode("Test Place", client)

    assert len(transport.requests) == 1
    ua = transport.requests[0].headers.get("user-agent", "")
    assert "bulliexplorer" in ua


@pytest.mark.unit
async def test_geocode_sends_correct_query_params():
    """The search endpoint receives ``q``, ``format=json``, and ``limit=1``."""
    transport = _JsonTransport([{"lat": "48.0", "lon": "8.0"}])
    async with httpx.AsyncClient(transport=transport) as client:
        await _geocode("My Place", client)

    req = transport.requests[0]
    assert req.url.params["q"] == "My Place"
    assert req.url.params["format"] == "json"
    assert req.url.params["limit"] == "1"


# ---------------------------------------------------------------------------
# _resolve_poi_location_with_geocoding — priority logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_geocoding_manual_coords_skip_network():
    """Manual lat/lng always wins — _geocode is never called."""
    poi = PoiFrontmatter(name="Summit", category="viewpoint", lat=48.05, lng=8.05)

    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        point = await _resolve_poi_location_with_geocoding(poi, client=None)

    assert point is not None
    assert point.x == pytest.approx(8.05)  # longitude → x
    assert point.y == pytest.approx(48.05)  # latitude  → y
    mock_gc.assert_not_awaited()


@pytest.mark.unit
async def test_geocoding_place_query_calls_geocode():
    """A POI with only place_query triggers _geocode."""
    poi = PoiFrontmatter(
        name="Café Sonnenberg",
        category="restaurant",
        place_query="Café Sonnenberg, Freiburg",
    )

    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        mock_gc.return_value = (48.0, 7.82)  # (lat, lon) from Nominatim
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        point = await _resolve_poi_location_with_geocoding(poi, client=mock_client)

    assert point is not None
    assert point.x == pytest.approx(7.82)  # lon → x
    assert point.y == pytest.approx(48.0)  # lat → y
    mock_gc.assert_awaited_once()


@pytest.mark.unit
async def test_geocoding_failed_geocode_returns_none():
    """When _geocode returns None, the function returns None (POI will be skipped)."""
    poi = PoiFrontmatter(name="Nowhere", category="other", place_query="asdkfjasldkfj")

    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        mock_gc.return_value = None
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        point = await _resolve_poi_location_with_geocoding(poi, client=mock_client)

    assert point is None


@pytest.mark.unit
async def test_geocoding_no_coords_no_query_returns_none():
    """A POI with neither lat/lng nor place_query always returns None."""
    poi = PoiFrontmatter(name="Empty", category="other")

    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        point = await _resolve_poi_location_with_geocoding(poi, client=None)

    assert point is None
    mock_gc.assert_not_awaited()


@pytest.mark.unit
async def test_geocoding_place_query_without_client_returns_none():
    """place_query is ignored when no HTTP client is provided."""
    poi = PoiFrontmatter(name="Some Place", category="campsite", place_query="Some Place, DE")

    with patch("app.services.geo_sync._geocode", new_callable=AsyncMock) as mock_gc:
        point = await _resolve_poi_location_with_geocoding(poi, client=None)

    assert point is None
    mock_gc.assert_not_awaited()
