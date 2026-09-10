"""Unit tests for app/services/overpass.py — mocked transport, no real network."""

from __future__ import annotations

import httpx
import pytest

from app.services.overpass import _OVERPASS_URLS, AmenityResult, _build_query, _parse_element, query_nearby_amenities

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


class _PerUrlTransport(httpx.AsyncBaseTransport):
    """Mock transport whose response/failure depends on the target URL —
    lets a test simulate "primary fails, mirror succeeds" (or any other
    per-instance combination) without a stateful call counter. Records
    every request made, in order, so a test can assert exactly which
    instances were actually hit.
    """

    def __init__(self, responses: dict[str, dict | Exception]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self._responses[str(request.url)]
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(200, json=outcome)


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
    backwards — confirmed explicitly rather than assumed."""
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
    (requested via `out ... center` in the query) — normalized the same
    way as a node."""
    result = _parse_element(_FUEL_WAY)
    assert result is not None
    assert result.lat == 48.06
    assert result.lon == 8.13
    assert result.category == "gas_station"


@pytest.mark.unit
def test_parse_element_unmapped_tags_returns_none():
    """An element whose tags don't match any tracked category is dropped,
    not errored — Overpass's own tag filter is broad regex, so an
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
    from a failure — [] vs None is the whole point of this return type."""
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
    timeout/resource-limit issue — results may be partial, so this must
    NOT be trusted as a successful empty/partial answer."""
    transport = _JsonTransport({"elements": [_CAMPSITE_NODE], "remark": "runtime error: query timed out"})
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is None


# ---------------------------------------------------------------------------
# query_nearby_amenities — mirror fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_query_nearby_amenities_falls_back_to_mirror_on_primary_network_error():
    """The primary instance being unreachable (connection refused, e.g.
    the real abuse-protection block hit in production) must not be a
    hard failure — the mirror gets tried, and its result is used."""
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlTransport(
        {
            primary: httpx.ConnectError("Connection refused"),
            mirror: {"elements": [_CAMPSITE_NODE]},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is not None
    assert len(results) == 1
    assert [str(r.url) for r in transport.requests] == [primary, mirror]


@pytest.mark.unit
async def test_query_nearby_amenities_falls_back_to_mirror_on_primary_remark():
    """A `remark` (partial/truncated result) from the primary is also a
    trigger to try the mirror, not just a hard network/HTTP error — the
    real production incident (an overloaded 504-equivalent) was exactly
    this shape, not a connection failure."""
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlTransport(
        {
            primary: {"elements": [], "remark": "runtime error: query timed out"},
            mirror: {"elements": [_CAMPSITE_NODE]},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is not None
    assert len(results) == 1


@pytest.mark.unit
async def test_query_nearby_amenities_all_instances_failing_returns_none():
    """Every configured instance failing is still a clean `None`, not an
    exception — the caller's "preserve existing data" contract must hold
    even when the fallback itself doesn't save the day."""
    async with httpx.AsyncClient(transport=_ErrorTransport()) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is None


@pytest.mark.unit
async def test_query_nearby_amenities_healthy_primary_never_calls_mirror():
    """A successful primary response must not also hit the mirror — the
    fallback exists purely for failure recovery, never to double a
    healthy primary's load."""
    transport = _JsonTransport({"elements": [_CAMPSITE_NODE]})
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is not None
    assert len(transport.requests) == 1


@pytest.mark.unit
async def test_query_nearby_amenities_start_index_tries_mirror_first():
    """``start_index`` lets a multi-chunk caller stick with whichever
    instance last actually worked — confirms passing it changes which
    instance is tried FIRST, not just which one eventually serves."""
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlTransport(
        {
            primary: {"elements": [_CAMPSITE_NODE]},
            mirror: {"elements": [_FUEL_WAY]},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client, start_index=1)
    assert results is not None
    assert results[0].category == "gas_station"  # the mirror's data, not the primary's
    assert str(transport.requests[0].url) == mirror
    assert len(transport.requests) == 1  # mirror succeeded first try — primary never contacted


@pytest.mark.unit
async def test_query_nearby_amenities_result_meta_records_served_index():
    """``result_meta`` is the mechanism ``geo_sync.py``'s sticky failover
    reads to decide the next chunk's ``start_index`` — must reflect which
    instance actually served, both on a healthy primary and on fallback."""
    primary, mirror = _OVERPASS_URLS

    transport = _JsonTransport({"elements": []})
    async with httpx.AsyncClient(transport=transport) as client:
        meta: dict = {}
        await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client, result_meta=meta)
    assert meta["served_index"] == 0

    fallback_transport = _PerUrlTransport(
        {
            primary: httpx.ConnectError("Connection refused"),
            mirror: {"elements": []},
        }
    )
    async with httpx.AsyncClient(transport=fallback_transport) as client:
        meta = {}
        await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client, result_meta=meta)
    assert meta["served_index"] == 1


@pytest.mark.unit
async def test_query_nearby_amenities_result_meta_none_when_all_fail():
    async with httpx.AsyncClient(transport=_ErrorTransport()) as client:
        meta: dict = {}
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client, result_meta=meta)
    assert results is None
    assert meta["served_index"] is None


@pytest.mark.unit
async def test_query_nearby_amenities_paces_the_fallback_retry(monkeypatch):
    """A fallback event (primary fails, mirror retried) must not fire the
    two Overpass-bound requests back-to-back with zero pacing — confirms
    the inter-instance delay actually fires between the two attempts,
    without a real (slow, flaky-to-test) sleep."""
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlTransport(
        {
            primary: httpx.ConnectError("Connection refused"),
            mirror: {"elements": []},
        }
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.overpass.asyncio.sleep", _fake_sleep)
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results is not None
    assert sleep_calls == [1.0]  # exactly one paced gap, between the two attempts


@pytest.mark.unit
async def test_query_nearby_amenities_no_pacing_on_healthy_primary(monkeypatch):
    """A healthy first attempt must never sleep — the pacing exists only
    on the failure-recovery path, never adds latency to the common case."""
    transport = _JsonTransport({"elements": []})
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.overpass.asyncio.sleep", _fake_sleep)
    async with httpx.AsyncClient(transport=transport) as client:
        await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert sleep_calls == []
