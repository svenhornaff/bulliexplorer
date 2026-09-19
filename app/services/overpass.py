"""Overpass API client for nearby-amenity discovery.

Framework-free, per ``app/services/`` convention — no FastAPI/SQLAlchemy
imports here. ``geo_sync.py`` owns orchestration and persistence; this
module only knows how to build the query, call Overpass, and parse the
response into plain dataclasses.

Design (``docs/dev/gis_cycling_upgrade.md`` Phase 4):

- One bounding-box query per route sync — a buffer around the route's
  envelope, not a precise along-the-track corridor (v1 simplification,
  documented as a deferred refinement in the concept doc).
- Best-effort: any failure (timeout, non-200, malformed JSON, an
  Overpass ``remark`` indicating a partial/truncated result) is logged
  and returns ``None`` — the caller decides how to handle "we don't know"
  (``geo_sync.py`` preserves whatever amenities already exist rather than
  wiping them on a transient Overpass outage).
- The public ``overpass-api.de`` instance is free, shared, and
  best-effort with no uptime guarantee (confirmed in production: both a
  hard connection refusal under burst load and, separately, an ordinary
  ``504``/timeout under everyday load). One fallback retry against a
  second independently-run public mirror before giving up meaningfully
  improves real-world reliability for very little code — short of
  self-hosting an Overpass instance, which stays out of scope here.
  Only retries on *failure*; never doubles up load on a healthy primary.
- A bbox that still fails against *every* instance is a different
  failure shape from a transient outage — it can mean the bbox covers
  a densely-OSM-mapped area where the query is structurally expensive
  regardless of which server answers it
  (``docs/dev/fix_overpass_urban_density_timeout.md``). In that case,
  the bbox is split in half and each half is retried through the same
  instance-fallback logic, once (never recursively past one split).
- Same discipline this project already applies to Nominatim: an
  identifying ``User-Agent``, and a request budget the caller can inject
  a client into for testing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Primary first, then one independently-run public mirror as a fallback
# — tried in order, only on the previous one failing. kumi.systems is
# generally the most consistently maintained of the community mirrors;
# not looping through every known mirror keeps the worst-case latency of
# a fully-failed query bounded to two attempts, not an open-ended chain.
_OVERPASS_URLS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

_OVERPASS_UA = "bulliexplorer/1.0 (https://github.com/svenhornaff/bulliexplorer)"

_OVERPASS_QL_TIMEOUT_S = 25

# Paced gap between a failed primary attempt and the mirror retry within
# ONE query — keeps a fallback event from firing two Overpass-bound
# requests back-to-back with no pacing at all. Deliberately shorter than
# geo_sync.py's own _MIN_OVERPASS_INTERVAL between separate chunk
# queries (that pacing is for load, not recovery latency); this one only
# fires on the failure path, never on a healthy primary.
_INTER_INSTANCE_RETRY_DELAY_S = 1.0
# Read timeout is intentionally a bit longer than the QL timeout above —
# giving Overpass room to actually hit *its own* timeout and return a
# clean (if partial) response, rather than us cutting the connection first
# and turning a would-be-parseable "remark" into a bare network error.
# Raised 35s -> 90s (fix_overpass_urban_density_timeout.md Phase 1) after
# a real dense-urban bbox (Cologne-Bonn-Ruhr) timed out against both
# instances at 35s — cheap headroom to try before reaching for the
# heavier Phase 2 adaptive-split fix below.
#
# Set explicitly on the client.post() call itself (see
# _query_one_instance below), not just on this module's own
# httpx.AsyncClient() construction — matches geo_sync._fetch_gpx_over_http's
# proven per-request pattern. A caller-supplied client passed in via
# ``http_client=`` (as geo_sync.sync_amenities does) has no way to
# silently undercut this budget, unlike relying on the client's own
# timeout config: httpx.AsyncClient() defaults to a 5s timeout when none
# is given, which is exactly what happened in production before this was
# set per-request (fix_overpass_urban_density_timeout.md "Root cause,
# corrected (again)").
_HTTP_TIMEOUT_S = 90.0

# Max times a failing bbox is split in half and retried
# (fix_overpass_urban_density_timeout.md Phase 2). Capped at 1 — split
# once into two halves, never recurse into quarters/eighths — so the
# worst-case extra query count for one bad chunk stays small and
# predictable rather than open-ended.
_MAX_SPLIT_DEPTH: int = 1

# OSM tag -> this project's amenity category (config.yml's category
# select plus a couple of derived-only values not offered to authors,
# since a reader distinguishing "camp_site" from "wilderness_hut" is
# useful, but an author choosing between them for their own curated POI
# is not worth the extra dropdown entries).
_TAG_TO_CATEGORY: dict[tuple[str, str], str] = {
    ("tourism", "camp_site"): "campsite",
    ("tourism", "wilderness_hut"): "shelter",
    ("amenity", "shelter"): "shelter",
    ("amenity", "drinking_water"): "water_point",
    ("amenity", "fuel"): "gas_station",
    ("shop", "bicycle"): "bike_shop",
    # Restaurant (docs/dev/fix_amenity_restaurant_category.md) —
    # "restaurant" already existed as a curated-POI category in
    # static/editor/config.yml's dropdown and had full marker icon/color
    # support in post-map.js's CATEGORY_COLOURS/CATEGORY_ICON_PATHS, but
    # was never actually fetched by the auto-discovery query below — a
    # real gap in the auto-discovered set, not a missing frontend
    # feature. amenity=restaurant is OSM's standard tag for a
    # sit-down restaurant; amenity=fast_food and amenity=cafe are
    # deliberately separate OSM tags for a different kind of place and
    # stay out of scope (see that doc's Leftover).
    ("amenity", "restaurant"): "restaurant",
}


@dataclass(frozen=True)
class AmenityResult:
    """One parsed Overpass element, ready for ``NearbyAmenity`` insertion."""

    osm_element_type: str
    osm_element_id: int
    category: str
    name: str | None
    lat: float
    lon: float
    tags: dict[str, str]


def _build_query(south: float, west: float, north: float, east: float) -> str:
    """Build the Overpass QL query string for the given bounding box.

    Bbox order is ``south, west, north, east`` — Overpass QL's own
    convention (not ``west, south, east, north`` as some other GIS tools
    use), easy to transpose by accident.
    """
    bbox = f"{south},{west},{north},{east}"
    return (
        f"[out:json][timeout:{_OVERPASS_QL_TIMEOUT_S}];"
        "("
        f'nwr["tourism"~"^(camp_site|wilderness_hut)$"]({bbox});'
        f'nwr["amenity"~"^(shelter|drinking_water|fuel|restaurant)$"]({bbox});'
        f'nwr["shop"="bicycle"]({bbox});'
        ");"
        "out tags center;"
    )


async def query_nearby_amenities(
    south: float,
    west: float,
    north: float,
    east: float,
    *,
    http_client: httpx.AsyncClient | None = None,
    start_index: int = 0,
    result_meta: dict | None = None,
) -> list[AmenityResult] | None:
    """Query Overpass for amenities within a bounding box.

    Best-effort: returns ``None`` (not an empty list) on any failure, so
    the caller can distinguish "genuinely nothing nearby" from "we don't
    know, Overpass didn't answer" and preserve existing data in the
    latter case rather than wiping it.

    A bbox that fails against *every* configured instance is retried
    once as two halves (split along its longer axis) before giving up
    entirely — handles a bbox that's structurally expensive regardless of
    which server answers it, e.g. a densely-OSM-mapped urban area, not
    just a transient whole-instance outage
    (``docs/dev/fix_overpass_urban_density_timeout.md``). Both halves
    must succeed for this to return anything — one half failing still
    means an incomplete answer for the original bbox.

    Parameters
    ----------
    south, west, north, east:
        Bounding box in EPSG:4326 degrees, Overpass QL's own
        ``south,west,north,east`` order.
    http_client:
        Optional ``httpx.AsyncClient``. When ``None`` a default client is
        created internally — pass an explicit client in tests to inject a
        mock transport, same pattern as ``geo_sync.py``'s Nominatim calls.
    start_index:
        Index into ``_OVERPASS_URLS`` to try first, wrapping around —
        lets a multi-chunk caller (``geo_sync.py``'s ``sync_amenities``)
        stick with whichever instance last actually worked for the rest
        of a sync run, instead of re-proving a known-bad primary is
        still down on every single chunk.
    result_meta:
        Optional dict this call mutates in place with
        ``{"served_index": int | None, "rate_limited": bool}`` —
        ``served_index`` is the ``_OVERPASS_URLS`` index that actually
        served the response, or ``None`` if every instance failed;
        ``rate_limited`` is ``True`` if *any* attempt made while
        answering this bbox (across instance fallback and any split
        retries) received an explicit HTTP 429, even if a later attempt
        ultimately succeeded — see
        ``docs/dev/fix_overpass_urban_density_timeout.md`` Phase 4. Kept
        out of the return type itself so existing callers checking
        ``results is None`` / ``results == []`` are unaffected.

    Returns
    -------
    A list of :class:`AmenityResult` (possibly empty, if genuinely
    nothing was found), or ``None`` on any failure.
    """
    _close_client = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": _OVERPASS_UA}, timeout=_HTTP_TIMEOUT_S)
        _close_client = True

    # Single-element mutable container, not a plain bool, so every nested
    # call (instance fallback, both branches of a split, recursively) can
    # set it in place without each one needing to return and merge a
    # separate rate-limited flag alongside (results, served_index).
    rate_limited = [False]
    try:
        results, served_index = await _query_bbox_with_split(
            south, west, north, east, client, start_index=start_index, split_depth=0, rate_limited=rate_limited
        )
        if result_meta is not None:
            result_meta["served_index"] = served_index
            result_meta["rate_limited"] = rate_limited[0]
        return results
    finally:
        if _close_client:
            await client.aclose()


async def _query_bbox_with_split(
    south: float,
    west: float,
    north: float,
    east: float,
    client: httpx.AsyncClient,
    *,
    start_index: int,
    split_depth: int,
    rate_limited: list[bool],
) -> tuple[list[AmenityResult] | None, int | None]:
    """Try every instance for one bbox; split-and-retry once on total failure.

    A bbox failing against *every* configured instance (see
    :func:`_query_one_bbox_all_instances`) can mean a transient
    whole-instance issue, but it can also mean the bbox is structurally
    expensive regardless of which server answers it — e.g. it covers a
    densely-OSM-mapped area, so the same geographic span has to scan a
    much larger feature index than an equally-sized rural bbox
    (``docs/dev/fix_overpass_urban_density_timeout.md``). In that case
    the bbox is split into two halves along its longer axis and each
    half is retried through the same instance-fallback logic, bounded to
    :data:`_MAX_SPLIT_DEPTH` (1) — split once, never recurse into
    quarters/eighths, so one bad chunk's worst-case extra query count
    stays small and predictable.

    Both halves must succeed for this to report success — a half that
    also fails on every instance means the answer for the *other* half
    alone is still an incomplete answer for the original bbox, and this
    project doesn't trust partial Overpass answers anywhere else in the
    pipeline either (``geo_sync.py``'s ``sync_amenities`` aborts an
    entire sync rather than write a partial snapshot).

    Returns
    -------
    A tuple of ``(results, served_index)``. ``served_index`` is the
    ``_OVERPASS_URLS`` index that actually served the response — for a
    split bbox, the second half's serving instance, since that's the most
    recently confirmed to be working. Both are ``None`` together on total
    failure (this bbox, and any split attempted for it, never got a
    trustworthy answer).
    """
    results, served_index = await _query_one_bbox_all_instances(
        south, west, north, east, client, start_index, rate_limited
    )
    if results is not None:
        return results, served_index

    if split_depth >= _MAX_SPLIT_DEPTH:
        return None, None

    logger.warning(
        "bbox (%s,%s,%s,%s) too expensive for any instance, retrying as two halves", south, west, north, east
    )
    (s1, w1, n1, e1), (s2, w2, n2, e2) = _split_bbox_in_half(south, west, north, east)
    # Both halves are independent queries with no data dependency between
    # them — run concurrently so a split doesn't double the wall-clock
    # cost of the already-slow failure path.
    (result_a, idx_a), (result_b, idx_b) = await asyncio.gather(
        _query_bbox_with_split(
            s1, w1, n1, e1, client, start_index=start_index, split_depth=split_depth + 1, rate_limited=rate_limited
        ),
        _query_bbox_with_split(
            s2, w2, n2, e2, client, start_index=start_index, split_depth=split_depth + 1, rate_limited=rate_limited
        ),
    )
    if result_a is None or result_b is None:
        return None, None

    # The two halves share a clean split boundary in principle, but
    # Overpass bbox filters are inclusive on both ends — an element
    # sitting exactly on the dividing line can be returned by both
    # halves. Dedup by the same natural key geo_sync.py already uses
    # across chunks.
    deduped: dict[tuple[str, int], AmenityResult] = {}
    for result in (*result_a, *result_b):
        deduped[(result.osm_element_type, result.osm_element_id)] = result

    # idx_b is never None here (result_b is not None only alongside a
    # served_index) — reported as the "last half" per this bbox's own
    # split, not the recursive call's own start_index.
    return list(deduped.values()), idx_b


async def _query_one_bbox_all_instances(
    south: float,
    west: float,
    north: float,
    east: float,
    client: httpx.AsyncClient,
    start_index: int,
    rate_limited: list[bool],
) -> tuple[list[AmenityResult] | None, int | None]:
    """Try every ``_OVERPASS_URLS`` instance, in ``start_index`` order.

    Returns ``(results, served_index)`` on the first instance to answer
    successfully, or ``(None, None)`` if every instance fails. Sets
    ``rate_limited[0] = True`` in place if any attempt got an explicit
    HTTP 429 — recorded regardless of whether a later attempt (a
    different instance) went on to succeed, since the caller
    (``geo_sync.py``) needs to know a real rate limit was hit at all to
    back off before its *next* chunk, not just whether this one
    ultimately got an answer.
    """
    query = _build_query(south, west, north, east)
    payload = None
    served_index = None
    ordered_indices = [(start_index + i) % len(_OVERPASS_URLS) for i in range(len(_OVERPASS_URLS))]
    for attempt, idx in enumerate(ordered_indices):
        if attempt > 0:
            # Only paces the failure-recovery path — a healthy
            # first attempt never sleeps here.
            await asyncio.sleep(_INTER_INSTANCE_RETRY_DELAY_S)
        payload, was_rate_limited = await _query_one_instance(
            client, _OVERPASS_URLS[idx], query, south, west, north, east
        )
        if was_rate_limited:
            rate_limited[0] = True
        if payload is not None:
            served_index = idx
            break

    if payload is None:
        return None, None
    assert served_index is not None  # noqa: S101 — payload set only alongside served_index, together

    elements = payload.get("elements", [])
    results: list[AmenityResult] = []
    for element in elements:
        parsed = _parse_element(element)
        if parsed is not None:
            results.append(parsed)

    logger.info(
        "Overpass (%s) returned %d amenities for bbox (%s,%s,%s,%s)",
        _OVERPASS_URLS[served_index],
        len(results),
        south,
        west,
        north,
        east,
    )
    return results, served_index


def _split_bbox_in_half(
    south: float, west: float, north: float, east: float
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """Split a bbox into two halves along its longer axis.

    Splits along latitude if the bbox is taller than it is wide, else
    along longitude — keeps each half as close to square as possible
    rather than always halving the same axis regardless of shape.
    Returns two ``(south, west, north, east)`` bboxes covering the same
    total area with no gap or overlap along the split axis (Overpass's
    own inclusive bbox bounds mean elements sitting exactly on the
    dividing line can still appear in both — handled by the caller's
    dedup, not here).
    """
    lat_span = north - south
    lon_span = east - west
    if lat_span >= lon_span:
        mid_lat = (south + north) / 2
        return (south, west, mid_lat, east), (mid_lat, west, north, east)
    mid_lon = (west + east) / 2
    return (south, west, north, mid_lon), (south, mid_lon, north, east)


async def _query_one_instance(
    client: httpx.AsyncClient,
    url: str,
    query: str,
    south: float,
    west: float,
    north: float,
    east: float,
) -> tuple[dict | None, bool]:
    """POST one query to one Overpass instance; ``None`` on any failure.

    Failure includes a 200 response carrying a ``remark`` — Overpass's own
    way of describing a partial/truncated result (e.g. a server-side
    timeout or resource limit) — treated the same as a hard failure so
    the caller never silently trusts an incomplete answer, whether it
    came from the primary or a fallback mirror.

    Returns
    -------
    A tuple of ``(payload, was_rate_limited)``. ``was_rate_limited`` is
    ``True`` only for an explicit HTTP 429 from this specific instance —
    distinct from every other failure (timeouts, other 5xx, connection
    errors), which all stay on the existing retry/split/give-up path
    unchanged (``docs/dev/fix_overpass_urban_density_timeout.md`` Phase
    4). A 429 is the one signal precise enough to justify a
    disproportionately long backoff before the *next* chunk in the same
    sync run — everything else already has its own handling (instance
    fallback, bbox splitting) that a longer wait wouldn't improve.
    """
    try:
        resp = await client.post(
            url,
            data={"data": query},
            headers={"User-Agent": _OVERPASS_UA},
            # Set per-request, not left to whatever the caller's client
            # happens to be configured with — matches
            # geo_sync._fetch_gpx_over_http's proven pattern. A client
            # passed in via http_client= (as sync_amenities does) has no
            # way to silently undercut this: see
            # fix_overpass_urban_density_timeout.md "Root cause,
            # corrected (again)" for the caller-side bug this closes at
            # its actual root instead of at one call site.
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPStatusError as exc:
        was_rate_limited = exc.response.status_code == 429
        logger.warning(
            "Overpass request to %s failed for bbox (%s,%s,%s,%s): %s: %s",
            url,
            south,
            west,
            north,
            east,
            type(exc).__name__,
            exc,
        )
        return None, was_rate_limited
    except Exception as exc:  # noqa: BLE001 — any other network/parse failure is non-fatal
        # Some httpx exceptions (e.g. a bare ReadTimeout/ConnectError from
        # an underlying anyio timeout) stringify to "" — %s alone then logs
        # an empty, undiagnosable message. Always include the exception's
        # own type name so a future failure is actually diagnosable from
        # logs alone, without ad-hoc reproduction.
        logger.warning(
            "Overpass request to %s failed for bbox (%s,%s,%s,%s): %s: %s",
            url,
            south,
            west,
            north,
            east,
            type(exc).__name__,
            exc,
        )
        return None, False

    remark = payload.get("remark")
    if remark:
        logger.warning(
            "Overpass (%s) returned a remark for bbox (%s,%s,%s,%s): %s", url, south, west, north, east, remark
        )
        return None, False

    return payload, False


def _parse_element(element: dict) -> AmenityResult | None:
    """Parse one Overpass element into an :class:`AmenityResult`.

    Nodes carry ``lat``/``lon`` directly; ways and relations carry a
    ``center`` object instead (requested via ``out ... center`` in the
    query) — both are normalized to the same ``lat``/``lon`` fields here.
    Returns ``None`` for anything unparseable (missing coordinates, or
    tags that don't map to a category this project tracks) rather than
    raising — one malformed element shouldn't fail the whole batch.
    """
    tags = element.get("tags") or {}
    category = None
    for (key, value), mapped in _TAG_TO_CATEGORY.items():
        if tags.get(key) == value:
            category = mapped
            break
    if category is None:
        return None

    element_type = element.get("type")
    element_id = element.get("id")
    if element_type is None or element_id is None:
        return None

    if "lat" in element and "lon" in element:
        lat, lon = element["lat"], element["lon"]
    elif "center" in element and "lat" in element["center"] and "lon" in element["center"]:
        lat, lon = element["center"]["lat"], element["center"]["lon"]
    else:
        logger.debug("Overpass element %s/%s has no usable coordinates — skipping", element_type, element_id)
        return None

    try:
        lat, lon = float(lat), float(lon)
        element_id = int(element_id)
    except (TypeError, ValueError):
        return None

    return AmenityResult(
        osm_element_type=element_type,
        osm_element_id=element_id,
        category=category,
        name=tags.get("name"),
        lat=lat,
        lon=lon,
        tags=tags,
    )
