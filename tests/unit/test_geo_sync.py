"""Unit tests for app/services/geo_sync.py — no DB required.

Tests cover the pure helper functions:
- _resolve_gpx_path: absolute vs relative path handling.
- _resolve_poi_location: lat/lng → Shapely Point, None when no coords.
- _parse_gpx: fixture GPX file produces correct geometry and stats.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import Point

from app.models.post_schema import PoiFrontmatter
from app.services.geo_sync import _parse_gpx, _resolve_gpx_path, _resolve_poi_location  # noqa: PLC2701

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
    """An absolute path is returned unchanged."""
    abs_path = "/some/absolute/path/route.gpx"
    result = _resolve_gpx_path(abs_path, Path("/content/posts"))
    assert result == Path(abs_path)


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
