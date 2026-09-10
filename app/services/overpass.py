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
- Same discipline this project already applies to Nominatim: an
  identifying ``User-Agent``, and a request budget the caller can inject
  a client into for testing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

_OVERPASS_UA = "bulliexplorer/1.0 (https://github.com/svenhornaff/bulliexplorer)"

_OVERPASS_QL_TIMEOUT_S = 25
# Read timeout is intentionally a bit longer than the QL timeout above —
# giving Overpass room to actually hit *its own* timeout and return a
# clean (if partial) response, rather than us cutting the connection first
# and turning a would-be-parseable "remark" into a bare network error.
_HTTP_TIMEOUT_S = 35.0

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
        f'nwr["amenity"~"^(shelter|drinking_water|fuel)$"]({bbox});'
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
) -> list[AmenityResult] | None:
    """Query Overpass for amenities within a bounding box.

    Best-effort: returns ``None`` (not an empty list) on any failure, so
    the caller can distinguish "genuinely nothing nearby" from "we don't
    know, Overpass didn't answer" and preserve existing data in the
    latter case rather than wiping it.

    Parameters
    ----------
    south, west, north, east:
        Bounding box in EPSG:4326 degrees, Overpass QL's own
        ``south,west,north,east`` order.
    http_client:
        Optional ``httpx.AsyncClient``. When ``None`` a default client is
        created internally — pass an explicit client in tests to inject a
        mock transport, same pattern as ``geo_sync.py``'s Nominatim calls.

    Returns
    -------
    A list of :class:`AmenityResult` (possibly empty, if genuinely
    nothing was found), or ``None`` on any failure.
    """
    query = _build_query(south, west, north, east)

    _close_client = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": _OVERPASS_UA}, timeout=_HTTP_TIMEOUT_S)
        _close_client = True

    try:
        try:
            resp = await client.post(
                _OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": _OVERPASS_UA},
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 — any network/HTTP/parse failure is non-fatal
            # Some httpx exceptions (e.g. a bare ReadTimeout/ConnectError from
            # an underlying anyio timeout) stringify to "" — %s alone then
            # logs an empty, undiagnosable message. Always include the
            # exception's own type name so a future failure is actually
            # diagnosable from logs alone, without ad-hoc reproduction.
            logger.warning(
                "Overpass request failed for bbox (%s,%s,%s,%s): %s: %s",
                south,
                west,
                north,
                east,
                type(exc).__name__,
                exc,
            )
            return None

        # A 200 response can still carry a "remark" describing a timeout
        # or resource-limit issue server-side — results may be partial,
        # so treat it the same as a hard failure rather than silently
        # trusting an incomplete answer.
        remark = payload.get("remark")
        if remark:
            logger.warning("Overpass returned a remark for bbox (%s,%s,%s,%s): %s", south, west, north, east, remark)
            return None

        elements = payload.get("elements", [])
        results: list[AmenityResult] = []
        for element in elements:
            parsed = _parse_element(element)
            if parsed is not None:
                results.append(parsed)

        logger.info(
            "Overpass returned %d amenities for bbox (%s,%s,%s,%s)",
            len(results),
            south,
            west,
            north,
            east,
        )
        return results
    finally:
        if _close_client:
            await client.aclose()


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
