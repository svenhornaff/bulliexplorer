"""Unit tests for app/services/overpass.py — mocked transport, no real network."""

from __future__ import annotations

import urllib.parse

import httpx
import pytest

from app.services.overpass import (  # noqa: PLC2701
    _HTTP_TIMEOUT_S,
    _MAX_SPLIT_DEPTH,
    _OVERPASS_URLS,
    AmenityResult,
    _build_query,
    _parse_element,
    _split_bbox_in_half,
    query_nearby_amenities,
)

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

    def __init__(self, responses: dict[str, dict | Exception | tuple[int, dict]]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self._responses[str(request.url)]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, tuple):
            status_code, payload = outcome
            return httpx.Response(status_code, json=payload)
        return httpx.Response(200, json=outcome)


class _PerUrlAndBboxTransport(httpx.AsyncBaseTransport):
    """Mock transport keyed on (url, bbox-substring-in-query-body).

    A split retries the SAME two URLs with a DIFFERENT (halved) bbox, so
    a plain per-URL transport can't distinguish an original query from
    one of its split halves. This keys responses on the request body
    containing a given bbox substring instead, so a test can express
    "primary+mirror both fail for the full bbox, but each half succeeds
    against a specific instance." Falls back to ``default`` when no
    bbox key matches (e.g. a URL that should never be reached for a
    given bbox at all raises on unmatched lookups instead).
    """

    def __init__(self, responses: dict[tuple[str, str], dict | Exception | tuple[int, dict]]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        # The POST body is form-urlencoded (the query string is inside a
        # "data=..." field), so a plain bbox substring like "(0.0,0.0)"
        # never matches the raw bytes — decode first.
        body = urllib.parse.unquote(request.content.decode())
        for (expected_url, bbox_substring), outcome in self._responses.items():
            if expected_url == url and bbox_substring in body:
                if isinstance(outcome, Exception):
                    raise outcome
                if isinstance(outcome, tuple):
                    status_code, payload = outcome
                    return httpx.Response(status_code, json=payload)
                return httpx.Response(200, json=outcome)
        raise AssertionError(f"no mocked response for url={url!r} body={body!r}")


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

_RESTAURANT_NODE = {
    "type": "node",
    "id": 789,
    "lat": 48.07,
    "lon": 8.14,
    "tags": {"amenity": "restaurant", "name": "Test Restaurant"},
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
    assert "restaurant" in query
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
def test_parse_element_restaurant_maps_to_restaurant_category():
    """amenity=restaurant (docs/dev/fix_amenity_restaurant_category.md)
    is a tracked category, not dropped — the auto-discovery gap this
    fix closes."""
    result = _parse_element(_RESTAURANT_NODE)
    assert result == AmenityResult(
        osm_element_type="node",
        osm_element_id=789,
        category="restaurant",
        name="Test Restaurant",
        lat=48.07,
        lon=8.14,
        tags={"amenity": "restaurant", "name": "Test Restaurant"},
    )


@pytest.mark.unit
def test_parse_element_unmapped_tags_returns_none():
    """An element whose tags don't match any tracked category is dropped,
    not errored — Overpass's own tag filter is broad regex, so an
    unrelated match is expected occasionally."""
    element = {"type": "node", "id": 1, "lat": 1.0, "lon": 1.0, "tags": {"amenity": "parking"}}
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
async def test_query_nearby_amenities_sets_timeout_per_request_not_via_client():
    """Regression test for fix_overpass_urban_density_timeout.md's
    corrected root cause: the timeout must be set on the client.post()
    call itself (request.extensions["timeout"]), not left to whatever
    timeout the caller's client happens to be configured with. A caller
    (geo_sync.sync_amenities) that passes in a bare httpx.AsyncClient()
    with no timeout= at all must still get the full _HTTP_TIMEOUT_S
    budget on every request — httpx.AsyncClient()'s own default is a
    mere 5s, which is exactly how this bug reached production.
    """
    transport = _JsonTransport({"elements": []})
    # Deliberately no timeout= here — the point is that the caller's own
    # client config must not matter.
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client)
    assert results == []
    assert len(transport.requests) == 1
    timeout = transport.requests[0].extensions["timeout"]
    assert timeout["read"] == _HTTP_TIMEOUT_S
    assert timeout["connect"] == _HTTP_TIMEOUT_S


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


# ---------------------------------------------------------------------------
# _split_bbox_in_half
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_split_bbox_in_half_splits_the_taller_axis():
    """A bbox taller (lat span) than it is wide (lon span) splits along
    latitude, not longitude."""
    half_a, half_b = _split_bbox_in_half(south=0.0, west=0.0, north=2.0, east=1.0)
    assert half_a == (0.0, 0.0, 1.0, 1.0)
    assert half_b == (1.0, 0.0, 2.0, 1.0)


@pytest.mark.unit
def test_split_bbox_in_half_splits_the_wider_axis():
    """A bbox wider (lon span) than it is tall (lat span) splits along
    longitude instead."""
    half_a, half_b = _split_bbox_in_half(south=0.0, west=0.0, north=1.0, east=2.0)
    assert half_a == (0.0, 0.0, 1.0, 1.0)
    assert half_b == (0.0, 1.0, 1.0, 2.0)


@pytest.mark.unit
def test_split_bbox_in_half_covers_the_same_total_area_with_no_gap():
    """The two halves must share exactly the split boundary — no gap, no
    double-covered strip beyond the intentional inclusive-bound overlap
    Overpass itself allows at the exact boundary."""
    (s1, w1, n1, e1), (s2, w2, n2, e2) = _split_bbox_in_half(south=0.0, west=0.0, north=4.0, east=1.0)
    assert n1 == s2  # halves meet exactly at the midpoint, no gap
    assert s1 == 0.0
    assert n2 == 4.0


# ---------------------------------------------------------------------------
# query_nearby_amenities — adaptive split on dual-instance failure
# (fix_overpass_urban_density_timeout.md Phase 2)
# ---------------------------------------------------------------------------

_FULL_BBOX = (0.0, 0.0, 2.0, 1.0)
_FULL_BBOX_STR = "(0.0,0.0,2.0,1.0)"
_HALF_A_STR = "(0.0,0.0,1.0,1.0)"  # south half
_HALF_B_STR = "(1.0,0.0,2.0,1.0)"  # north half


@pytest.mark.unit
async def test_query_nearby_amenities_splits_bbox_when_both_instances_fail():
    """A bbox failing against BOTH instances is split into two halves
    and each half is retried through the normal instance-fallback path —
    the actual observed failure shape from fix_overpass_urban_density_timeout.md
    (same bbox timing out on both overpass-api.de and the mirror)."""
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlAndBboxTransport(
        {
            (primary, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (mirror, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (primary, _HALF_A_STR): {"elements": [_CAMPSITE_NODE]},
            (primary, _HALF_B_STR): {"elements": [_FUEL_WAY]},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(*_FULL_BBOX, http_client=client)
    assert results is not None
    assert {r.category for r in results} == {"campsite", "gas_station"}
    # 2 failed attempts for the full bbox + 1 successful attempt per half.
    assert len(transport.requests) == 4


@pytest.mark.unit
async def test_query_nearby_amenities_split_is_bounded_to_one_level():
    """A half that ALSO fails against both instances is not split again —
    the depth cap (_MAX_SPLIT_DEPTH) stops recursion at quarters, keeping
    worst-case query count for one bad chunk small and predictable."""
    assert _MAX_SPLIT_DEPTH == 1
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlAndBboxTransport(
        {
            (primary, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (mirror, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (primary, _HALF_A_STR): httpx.ReadTimeout("timed out"),
            (mirror, _HALF_A_STR): httpx.ReadTimeout("timed out"),
            (primary, _HALF_B_STR): {"elements": []},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(*_FULL_BBOX, http_client=client)
    # Half A failing on both instances means an incomplete answer overall
    # — even though half B succeeded, the whole bbox's answer is untrusted.
    assert results is None
    # Bounded: full bbox (2) + half A (2, gives up, no further split) +
    # half B (1) = 5 total requests, never a quarter-bbox query.
    assert len(transport.requests) == 5
    assert not any("0.5" in str(r.content) for r in transport.requests)


@pytest.mark.unit
async def test_query_nearby_amenities_split_dedupes_boundary_elements():
    """Overpass bbox bounds are inclusive on both ends, so an element
    sitting exactly on the split boundary can be returned by both halves
    — must be deduplicated, not double-counted."""
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlAndBboxTransport(
        {
            (primary, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (mirror, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (primary, _HALF_A_STR): {"elements": [_CAMPSITE_NODE]},
            (primary, _HALF_B_STR): {"elements": [_CAMPSITE_NODE]},  # same element, boundary duplicate
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(*_FULL_BBOX, http_client=client)
    assert results is not None
    assert len(results) == 1


@pytest.mark.unit
async def test_query_nearby_amenities_split_result_meta_reflects_last_half():
    """result_meta["served_index"] after a split reports whichever
    instance served the SECOND half — the most recently confirmed to be
    working, for geo_sync.py's sticky failover to start the next chunk
    there."""
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlAndBboxTransport(
        {
            (primary, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (mirror, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (primary, _HALF_A_STR): {"elements": []},
            (primary, _HALF_B_STR): httpx.ReadTimeout("timed out"),
            (mirror, _HALF_B_STR): {"elements": []},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        meta: dict = {}
        results = await query_nearby_amenities(*_FULL_BBOX, http_client=client, result_meta=meta)
    assert results is not None
    assert meta["served_index"] == 1  # mirror served half B, the last half


@pytest.mark.unit
async def test_query_nearby_amenities_healthy_chunk_never_triggers_split():
    """A chunk that succeeds normally must never trigger any splitting
    logic — no regression to the common case, which is every chunk on
    every route except the one dense-urban bbox this fix targets."""
    transport = _PerUrlAndBboxTransport(
        {
            (_OVERPASS_URLS[0], _FULL_BBOX_STR): {"elements": [_CAMPSITE_NODE]},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        results = await query_nearby_amenities(*_FULL_BBOX, http_client=client)
    assert results is not None
    assert len(transport.requests) == 1  # no split, no mirror, no half queries


# ---------------------------------------------------------------------------
# query_nearby_amenities — explicit 429 signal (Phase 4,
# fix_overpass_urban_density_timeout.md "New finding: 429 under
# cumulative load")
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_query_nearby_amenities_result_meta_reports_rate_limited_on_429():
    """A real HTTP 429 from an instance must be distinguishable from any
    other failure via result_meta["rate_limited"] — the caller
    (geo_sync.sync_amenities) needs this specific signal to trigger an
    extended backoff before its next chunk, not just "this bbox failed"
    (which the mirror fallback already retries with no extra delay).
    """
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlTransport(
        {
            primary: (429, {"error": "rate limited"}),
            mirror: {"elements": [_CAMPSITE_NODE]},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        meta: dict = {}
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client, result_meta=meta)
    assert results is not None  # the mirror still answered
    assert meta["rate_limited"] is True


@pytest.mark.unit
async def test_query_nearby_amenities_result_meta_false_on_non_429_failure():
    """A plain timeout, connection error, or non-429 HTTP error must NOT
    set rate_limited — only a real 429 should trigger the Phase 4
    extended backoff; every other failure already has its own handling
    (instance fallback, bbox splitting) that a longer wait wouldn't
    improve."""
    transport = _JsonTransport({"error": "bad request"}, status_code=400)
    async with httpx.AsyncClient(transport=transport) as client:
        meta: dict = {}
        results = await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client, result_meta=meta)
    assert results is None
    assert meta["rate_limited"] is False


@pytest.mark.unit
async def test_query_nearby_amenities_result_meta_false_on_healthy_primary():
    """No regression to the common (healthy) case — rate_limited must be
    False when nothing went wrong at all."""
    transport = _JsonTransport({"elements": []})
    async with httpx.AsyncClient(transport=transport) as client:
        meta: dict = {}
        await query_nearby_amenities(1.0, 2.0, 3.0, 4.0, http_client=client, result_meta=meta)
    assert meta["rate_limited"] is False


@pytest.mark.unit
async def test_query_nearby_amenities_rate_limited_reported_even_when_split_eventually_succeeds():
    """A 429 on the ORIGINAL (pre-split) bbox must still be reported even
    if the split-and-retry path that follows ultimately succeeds —
    geo_sync.py needs to know a real rate limit was hit at all during
    this bbox's resolution, not just whether the final answer arrived.
    """
    primary, mirror = _OVERPASS_URLS
    transport = _PerUrlAndBboxTransport(
        {
            (primary, _FULL_BBOX_STR): (429, {"error": "rate limited"}),
            (mirror, _FULL_BBOX_STR): httpx.ReadTimeout("timed out"),
            (primary, _HALF_A_STR): {"elements": [_CAMPSITE_NODE]},
            (primary, _HALF_B_STR): {"elements": [_FUEL_WAY]},
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        meta: dict = {}
        results = await query_nearby_amenities(*_FULL_BBOX, http_client=client, result_meta=meta)
    assert results is not None
    assert meta["rate_limited"] is True
