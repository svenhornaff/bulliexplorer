"""Unit tests for app/services/overpass.py — mocked transport, no real network."""

from __future__ import annotations

import httpx
import pytest

from app.services.overpass import AmenityResult, _build_query, _parse_element, query_nearby_amenities

# ---------------------------------------------------------------------------


class _JsonTransport(httpx.AsyncBaseTransport):
    """Mock httpx transport that returns a fixed JSON response."""

    def __init__(self, payload: dict, status_code: int = 200) -> None:
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


_CAMPSITE_NODE = {
    "type": "node",
    "id": 123,
    "lat": 48.05,
    "lon": 8.12,
    "tags": {"tourism": "camp_site", "name": "Test Camp"},
}

_FUEL_WAY = {
    "type": "way",
    "id": 456,
    "center": {"lat": 48.06, "lon": 8.13},
    "tags": {"amenity": "fuel", "name": "Test Fuel"},
}


# ---------------------------------------------------------------------------
# _build_query
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_query_uses_south_west_north_east_order():
    """Overpass QL's own bbox order (south,west,north,east), easy to get
    backwards \u2014 confirmed explicitly rather than assumed."""
    query = _build_query(south=1.0, west=2.0, north=3.0, east=4.0)
    assert "(1.0,2.0,3.0,4.0)" in query


@pytest.mark.unit
def test_build_query_includes_all_target_tags():
    query = _build_query(south=1.0, west=2.0, north=3.0, east=4.0)
    assert "camp_site" in query
    assert "wilderness_hut" in query
    assert "shelter" in query
    assert "drinking_water" in query
    assert "fuel" in query
    assert '"shop"="bicycle"' in query


# ---------------------------------------------------------------------------
# _parse_element
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_element_node_with_direct_coords():
    result = _parse_element(_CAMPSITE_NODE)
    assert result == AmenityResult(
        osm_element_type="node",
        osm_element_id=123,
        category="campsite",
        name="Test Camp",
        lat=48.05,
        lon=8.12,
        tags={"tourism": "camp_site", "name": "Test Camp"},
    )


@pytest.mark.unit
def test_parse_element_way_uses_center():
    """Ways/relations carry a `center` object instead of lat/lon directly
    (requested via `out ... center` in the query) \u2014 normalized the same
    way as a node."""
    result = _parse_element(_FUEL_WAY)
    assert result is not None
    assert result.lat == 48.06
    assert result.lon == 8.13
    assert result.category == "gas_station"


@pytest.mark.unit
def test_parse_element_unmapped_tags_returns_none():
    """An element whose tags don't match any tracked category is dropped,
    not errored \u2014 Overpass's own tag filter is broad regex, so an
    unrelated match is expected occasionally."""
    element = {"type": "node", "id": 1, "lat": 1.0, "lon": 1.0, "tags": {"amenity": "restaurant"}}
    assert _parse_element(element) is None


@pytest.mark.unit
def test_parse_element_missing_coordinates_returns_none():
    element = {"type": "way", "id": 1, "tags": {"amenity": "fuel"}}
    assert _parse_element(element) is None


@pytest.mark.unit
def test_parse_element_malformed_coordinates_returns_none():
    element = {"type": "node", "id": 1, "lat": "not-a-number", "lon": 8.0, "tags": {"amenity": "fuel"}}
    assert _parse_element(element) is None


@pytest.mark.unit
def test_parse_element_missing_name_is_fine():
    element = {"type": "node", "id": 1, "lat": 1.0, "lon": 1.0, "tags": {"amenity": "drinking_water"}}
    result = _parse_element(element)
    assert result is not None
    assert result.name is None


# ---------------------------------------------------------------------------
# query_nearby_amenities
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_query_nearby_amenities_success():
    transport = _JsonTransport({"elements": [_CAMPSITE_NODE, _FUEL_WAY]})
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is not None
    assert len(results) == 2
    assert {r.category for r in results} == {"campsite", "gas_station"}


@pytest.mark.unit
async def test_query_nearby_amenities_empty_result_is_empty_list_not_none():
    """A genuinely empty (but successful) response must be distinguishable
    from a failure \u2014 [] vs None is the whole point of this return type."""
    transport = _JsonTransport({"elements": []})
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results == []


@pytest.mark.unit
async def test_query_nearby_amenities_network_error_returns_none():
    async with httpx.AsyncClient(transport=_ErrorTransport()) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is None


@pytest.mark.unit
async def test_query_nearby_amenities_http_error_returns_none():
    transport = _JsonTransport({"error": "bad request"}, status_code=400)
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is None


@pytest.mark.unit
async def test_query_nearby_amenities_remark_treated_as_failure():
    """A 200 response can still carry a `remark` describing a server-side
    timeout/resource-limit issue \u2014 results may be partial, so this must
    NOT be trusted as a successful empty/partial answer."""
    transport = _JsonTransport({"elements": [_CAMPSITE_NODE], "remark": "runtime error: query timed out"})
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is None
