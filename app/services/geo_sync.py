"""Geo sync service — GPX parsing and Route/PointOfInterest upsert/delete.

Extends the post sync pipeline (post_sync.py) to handle the geo data
embedded in a post's frontmatter: a GPX track → Route row, and manual
lat/lng or geocoded POIs → PointOfInterest rows.

Design rules (per AGENTS.md):
- **Framework-free**: no FastAPI, Jinja2, or sqladmin imports.
- **Resilient**: a bad GPX, a missing file, or a failed geocode is skipped
  with a warning; it must not abort the sync for the post as a whole.
- **Reconciling**: if a post's frontmatter previously had a route/POIs and
  a later edit removes them, the now-orphaned DB rows are deleted.
- **Idempotent**: re-syncing unchanged content produces no DB writes.

Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/):
- Identify your application via ``User-Agent``.
- No more than 1 request per second — enforced by :data:`_MIN_REQUEST_INTERVAL`
  and the module-level :data:`_last_geocode_time` timestamp.

Overpass amenity discovery (Phase 4, ``docs/dev/gis_cycling_upgrade.md``):
- Auto-discovered, not authored — see :mod:`app.models.nearby_amenity`'s
  module docstring for why this is a separate table from PointOfInterest.
- Chunked by contiguous point-index groups along the route, not one query
  over the whole bounding box — a long route (this project's own "Dream
  of North" spans ~4,200 km / half of Scandinavia) would otherwise mean
  one Overpass query covering a huge, mostly-irrelevant area. Consecutive
  GPX points are geographically local to each other even when the whole
  route's *overall* span is huge, so splitting by index naturally follows
  the actual path — see :func:`_amenity_query_bboxes`.
- Same 1 req/s discipline as Nominatim, enforced independently (a
  different remote service, its own rate-limit clock).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import math
from pathlib import Path

import gpxpy
import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nearby_amenity import NearbyAmenity
from app.models.point_of_interest import PointOfInterest
from app.models.post_schema import PoiFrontmatter, RouteFrontmatter
from app.models.route import Route
from app.services.overpass import AmenityResult, query_nearby_amenities

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------

# Bounding box of the current PMTiles basemap extract (Europe, as of the
# gis coverage-refactor fix documented in docs/dev/maps_gis.md). Update
# this any time the tile file's actual coverage changes — see that doc
# for how the current extract was generated and why this exists.
_TILE_COVERAGE_BOUNDS = {
    "min_lat": 34.0,
    "max_lat": 72.0,
    "min_lon": -25.0,
    "max_lon": 45.0,
}


def _check_tile_coverage(linestring: LineString, post_id: int, route_name: str) -> None:
    """Warn (don't block) if a route falls outside the basemap's coverage.

    The route line and stats render correctly regardless — both are pure
    geometry/GPX math with no geography assumption (confirmed in
    maps_gis.md's table). Only the basemap tiles underneath would show a
    gray void for the out-of-coverage portion. This surfaces that risk in
    sync/deploy logs the moment a route is added, instead of a reader
    finding a gray map days or weeks later.

    Parameters
    ----------
    linestring:
        The route's parsed geometry — ``.bounds`` gives
        ``(min_lon, min_lat, max_lon, max_lat)`` for free.
    post_id:
        The post this route belongs to, for the log message.
    route_name:
        The route's display name, for the log message.
    """
    min_lon, min_lat, max_lon, max_lat = linestring.bounds
    bounds = _TILE_COVERAGE_BOUNDS
    if (
        min_lat < bounds["min_lat"]
        or max_lat > bounds["max_lat"]
        or min_lon < bounds["min_lon"]
        or max_lon > bounds["max_lon"]
    ):
        logger.warning(
            "Route %r (post_id=%d) extends outside the PMTiles basemap's "
            "coverage (lon %.4f..%.4f, lat %.4f..%.4f vs covered lon "
            "%.1f..%.1f, lat %.1f..%.1f) — the route line and stats will "
            "still render correctly, but the basemap tiles will show a "
            "gray void for the out-of-coverage portion.",
            route_name,
            post_id,
            min_lon,
            max_lon,
            min_lat,
            max_lat,
            bounds["min_lon"],
            bounds["max_lon"],
            bounds["min_lat"],
            bounds["max_lat"],
        )


# ---------------------------------------------------------------------------
# Nominatim constants and rate-limit state
# ---------------------------------------------------------------------------

_NOMINATIM_SEARCH_URL: str = "https://nominatim.openstreetmap.org/search"

# Nominatim usage policy requires a descriptive User-Agent.
_NOMINATIM_UA: str = "bulliexplorer/1.0 (https://github.com/svenhornaff/bulliexplorer)"

# Nominatim allows at most 1 request per second.
_MIN_REQUEST_INTERVAL: float = 1.0

# Last-request monotonic timestamp — updated after each Nominatim call so
# that consecutive geocoding calls in the same sync run are spaced correctly.
_last_geocode_time: float = 0.0

# Overpass usage policy (https://operations.osmfoundation.org/policies/overpass/)
# doesn't mandate an exact rate, but this project applies the same 1 req/s
# discipline it already uses for Nominatim — a separate clock, since these
# are two independent remote services.
_MIN_OVERPASS_INTERVAL: float = 1.0
_last_overpass_time: float = 0.0

# Buffer padding (km) around each query bbox — an "along-route service
# corridor" scale (water/fuel/camping a touring cyclist might detour a
# short way for), not "somewhere in the region".
_AMENITY_SEARCH_RADIUS_KM: float = 2.0

# Below this span (~111 km), a route's own bounding box plus buffer is a
# small enough area for a single Overpass query — covers this project's
# local rides (Kinzig Valley, Sunday Gravel Loop) with just one request.
_SINGLE_QUERY_MAX_SPAN_DEG: float = 1.0

# Hard cap on chunks/requests per route sync, regardless of route length —
# keeps sync time and Overpass load bounded even for an outlier route like
# "Dream of North" (~4,200 km / half of Scandinavia).
_MAX_AMENITY_QUERIES: int = 30

# Per-route cooldown against re-querying Overpass too often across separate
# sync runs (distinct from _MIN_OVERPASS_INTERVAL, which paces requests
# *within* one run). Without this, resyncing the same route a few times in
# quick succession — an author saving a long route's frontmatter repeatedly
# while drafting, or repeated webhook/manual resyncs — can fire dozens of
# requests at the public overpass-api.de instance in a short window and trip
# its abuse protection (observed in production: a burst of resyncs got the
# server's IP outright connection-refused for a period). 15 minutes is
# generous enough that no normal editing workflow hits it more than once.
_AMENITY_SYNC_COOLDOWN = datetime.timedelta(minutes=15)

_KM_PER_DEGREE_LAT: float = 111.0


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


async def sync_route(
    session: AsyncSession,
    post_id: int,
    route_fm: RouteFrontmatter | None,
    content_dir: Path,
    *,
    http_client: httpx.AsyncClient | None = None,
    enable_amenity_discovery: bool = False,
    overpass_client: httpx.AsyncClient | None = None,
) -> None:
    """Upsert or delete the Route row for a post.

    Parameters
    ----------
    session:
        Open ``AsyncSession``.  Caller owns the transaction.
    post_id:
        The integer PK of the ``posts`` row this route belongs to.
    route_fm:
        Parsed ``RouteFrontmatter`` from the post's YAML, or ``None`` if
        the post has no route.  When ``None``, any existing Route row for
        this ``post_id`` is deleted.
    content_dir:
        Directory used to resolve the ``gpx_file`` path when it is given
        as a relative path (ignored when ``gpx_file`` is an ``http(s)://``
        URL — R2-hosted GPX files, per ``media_storage_r2.md`` Phase 2).
    http_client:
        Optional ``httpx.AsyncClient`` used to fetch ``gpx_file`` when it
        is a URL.  When ``None`` a default client is created internally —
        pass an explicit client in tests to inject a mock transport.
    enable_amenity_discovery:
        Off by default (``Settings.enable_amenity_discovery``, threaded
        down from ``sync_posts``) — a new third-party network dependency
        (Overpass) on every route sync shouldn't turn on silently, and
        every existing caller/test needs zero changes while it's off.
    overpass_client:
        Optional ``httpx.AsyncClient`` used for the Overpass query when
        ``enable_amenity_discovery`` is on. When ``None`` a default client
        is created internally — pass an explicit client in tests to
        inject a mock transport. Separate from ``http_client`` (GPX
        fetching) since they're two independent remote services.
    """
    existing = await _get_existing_route(session, post_id)

    if route_fm is None:
        # Route was removed from frontmatter — delete the orphaned row.
        if existing is not None:
            await session.delete(existing)
            logger.info("Deleted orphaned Route for post_id=%d", post_id)
        return

    # Parse the GPX file.
    parsed = await _parse_gpx(route_fm.gpx_file, content_dir, http_client=http_client)
    if parsed is None:
        # Bad/missing GPX — skip, don't delete an existing row either;
        # treat as a transient error rather than a deliberate removal.
        logger.warning(
            "Skipping route upsert for post_id=%d — GPX could not be parsed",
            post_id,
        )
        return

    linestring, distance_km, elevation_gain_m, elevation_loss_m, duration_minutes = parsed
    _check_tile_coverage(linestring, post_id, route_fm.name)

    if existing is None:
        route = Route(
            post_id=post_id,
            name=route_fm.name,
            description=route_fm.description,
            track=from_shape(linestring, srid=4326),
            distance_km=distance_km,
            elevation_gain_m=elevation_gain_m,
            elevation_loss_m=elevation_loss_m,
            duration_minutes=duration_minutes,
        )
        session.add(route)
        logger.debug("Inserted Route for post_id=%d", post_id)
    else:
        changed = False
        updates: dict[str, object] = {
            "name": route_fm.name,
            "description": route_fm.description,
            "distance_km": distance_km,
            "elevation_gain_m": elevation_gain_m,
            "elevation_loss_m": elevation_loss_m,
            "duration_minutes": duration_minutes,
        }
        for attr, value in updates.items():
            if getattr(existing, attr) != value:
                setattr(existing, attr, value)
                changed = True

        # Re-parse and compare geometry (WKB bytes may differ on minor
        # float changes — compare the WKB hex strings as a proxy).
        new_track = from_shape(linestring, srid=4326)
        if str(existing.track) != str(new_track):
            existing.track = new_track  # type: ignore[assignment] — GeoAlchemy2 WKBElement is valid at runtime
            changed = True

        if changed:
            logger.debug("Updated Route for post_id=%d", post_id)
        else:
            logger.debug("Route for post_id=%d unchanged — no write", post_id)

    if enable_amenity_discovery:
        # Flush so route.id is populated for a fresh insert (an update
        # already has one). Needed before sync_amenities, which ties rows
        # to route_id.
        await session.flush()
        route_row = existing if existing is not None else route
        await sync_amenities(session, route_row, linestring, http_client=overpass_client)


def _amenity_query_bboxes(linestring: LineString) -> list[tuple[float, float, float, float]]:
    """Split a route's coordinates into Overpass query bboxes.

    Short/local routes (span below :data:`_SINGLE_QUERY_MAX_SPAN_DEG`) get
    one bbox covering the whole buffered envelope. Longer routes are split
    into up to :data:`_MAX_AMENITY_QUERIES` **contiguous** chunks by point
    index — not a uniform grid over the overall bounding box. Consecutive
    GPX points are geographically close to each other even when the
    route's *overall* span is huge (a long route winds through many local
    areas rather than covering one huge area uniformly), so an
    index-contiguous chunk's own local bbox stays small and relevant
    regardless of how far-flung the route as a whole is.

    Returns bboxes in Overpass QL's own ``(south, west, north, east)``
    order, each already padded by :data:`_AMENITY_SEARCH_RADIUS_KM`.
    """
    coords = list(linestring.coords)
    min_lon, min_lat, max_lon, max_lat = linestring.bounds
    overall_span = max(max_lat - min_lat, max_lon - min_lon)

    if overall_span <= _SINGLE_QUERY_MAX_SPAN_DEG:
        chunks = [coords]
    else:
        num_chunks = min(_MAX_AMENITY_QUERIES, math.ceil(overall_span / _SINGLE_QUERY_MAX_SPAN_DEG))
        chunk_size = math.ceil(len(coords) / num_chunks)
        chunks = [coords[i : i + chunk_size] for i in range(0, len(coords), chunk_size)]

    bboxes: list[tuple[float, float, float, float]] = []
    for chunk in chunks:
        if not chunk:
            continue
        lons = [c[0] for c in chunk]
        lats = [c[1] for c in chunk]
        bboxes.append(_buffered_bbox(min(lons), min(lats), max(lons), max(lats)))
    return bboxes


def _buffered_bbox(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
) -> tuple[float, float, float, float]:
    """Pad a lon/lat bbox by :data:`_AMENITY_SEARCH_RADIUS_KM` each side.

    Deliberately not a precise geodesic buffer — v1 uses a bounding-box +
    radius, not a precise along-the-track corridor
    (``docs/dev/gis_cycling_upgrade.md`` Phase 4). Returns
    ``(south, west, north, east)``, Overpass QL's own bbox order.
    """
    lat_buffer = _AMENITY_SEARCH_RADIUS_KM / _KM_PER_DEGREE_LAT
    # Longitude degrees shrink with cos(latitude); use the bbox's own
    # midpoint latitude so the buffer doesn't over/under-shoot at high
    # latitudes (this project's routes go as far north as ~71°N).
    mid_lat = (min_lat + max_lat) / 2
    lon_buffer = _AMENITY_SEARCH_RADIUS_KM / (_KM_PER_DEGREE_LAT * max(math.cos(math.radians(mid_lat)), 0.01))
    return (
        min_lat - lat_buffer,
        min_lon - lon_buffer,
        max_lat + lat_buffer,
        max_lon + lon_buffer,
    )


async def sync_amenities(
    session: AsyncSession,
    route: Route,
    linestring: LineString,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Discover and upsert :class:`NearbyAmenity` rows for a route.

    Best-effort, snapshot-replace semantics:

    - Queries Overpass in full **before** touching the DB. Existing
      amenities are only replaced once every chunk query has *succeeded*
      (partial success across chunks still preserves the old snapshot —
      an incomplete answer is worse than a stale one for derived data
      nobody manually edits).
    - A successful query with zero results legitimately clears old rows
      (the amenities genuinely aren't there any more, e.g. the route
      changed).
    - Deduplicates by ``(osm_element_type, osm_element_id)`` across
      chunks — the buffer padding means adjacent chunks' bboxes overlap,
      so the same OSM element can appear in more than one chunk's result.

    Parameters
    ----------
    session:
        Open ``AsyncSession``.  Caller owns the transaction.
    route:
        The just-upserted :class:`Route` row (``route.id`` must already be
        populated — caller flushes first for a fresh insert).
    linestring:
        The route's parsed geometry, used to build query bboxes.
    http_client:
        Optional ``httpx.AsyncClient`` used for Overpass requests.  When
        ``None`` a default client is created internally — pass an
        explicit client in tests to inject a mock transport.
    """
    global _last_overpass_time  # noqa: PLW0603 — module-level rate-limit timestamp

    now = datetime.datetime.now(datetime.UTC)
    if route.amenities_synced_at is not None:
        elapsed_since_last = now - route.amenities_synced_at
        if elapsed_since_last < _AMENITY_SYNC_COOLDOWN:
            logger.info(
                "Skipping Overpass amenity sync for route_id=%d — last attempt was %s ago "
                "(cooldown %s) — leaving existing NearbyAmenity rows untouched",
                route.id,
                elapsed_since_last,
                _AMENITY_SYNC_COOLDOWN,
            )
            return

    # Set on every *attempted* sync, success or failure — a failed attempt
    # still counts against the cooldown, since retrying a route that's
    # already failing fast (e.g. Overpass mid-outage) is exactly the burst
    # pattern this cooldown exists to prevent.
    route.amenities_synced_at = now

    bboxes = _amenity_query_bboxes(linestring)

    _close_client = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient()
        _close_client = True

    try:
        all_results: list[AmenityResult] = []
        # Sticky per-sync failover (docs/dev/gis_cycling_upgrade.md Phase
        # 5): once a chunk actually gets served by the mirror, subsequent
        # chunks in THIS sync try the mirror first too, rather than
        # wasting a round-trip re-proving an already-known-bad primary is
        # still down on every remaining chunk. Resets to the primary on
        # the next sync_amenities() call (a local variable, not module
        # state) — "for the rest of this sync run", not permanently.
        preferred_start = 0
        for south, west, north, east in bboxes:
            loop = asyncio.get_running_loop()
            elapsed = loop.time() - _last_overpass_time
            if elapsed < _MIN_OVERPASS_INTERVAL:
                await asyncio.sleep(_MIN_OVERPASS_INTERVAL - elapsed)
            _last_overpass_time = loop.time()

            result_meta: dict = {}
            chunk_results = await query_nearby_amenities(
                south, west, north, east, http_client=client, start_index=preferred_start, result_meta=result_meta
            )
            served_index = result_meta.get("served_index")
            if served_index is not None:
                preferred_start = served_index
            if chunk_results is None:
                # One chunk failed — the overall answer is incomplete.
                # Preserve whatever amenities already exist rather than
                # replace them with a partial result.
                logger.warning(
                    "Overpass amenity sync incomplete for route_id=%d (bbox %s,%s,%s,%s failed) — "
                    "leaving existing NearbyAmenity rows untouched",
                    route.id,
                    south,
                    west,
                    north,
                    east,
                )
                return
            all_results.extend(chunk_results)
    finally:
        if _close_client:
            await client.aclose()

    # Dedupe across chunks (overlapping buffers can return the same OSM
    # element from more than one chunk).
    deduped: dict[tuple[str, int], AmenityResult] = {}
    for result in all_results:
        deduped[(result.osm_element_type, result.osm_element_id)] = result

    # All chunk queries succeeded — safe to replace the snapshot now.
    await session.execute(delete(NearbyAmenity).where(NearbyAmenity.route_id == route.id))
    for result in deduped.values():
        amenity = NearbyAmenity(
            route_id=route.id,
            osm_element_type=result.osm_element_type,
            osm_element_id=result.osm_element_id,
            category=result.category,
            name=result.name,
            location=from_shape(Point(result.lon, result.lat), srid=4326),
            tags=result.tags,
        )
        session.add(amenity)

    logger.info("Synced %d NearbyAmenity rows for route_id=%d", len(deduped), route.id)


async def sync_pois(
    session: AsyncSession,
    post_id: int,
    pois_fm: list[PoiFrontmatter],
    *,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Replace all PointOfInterest rows for a post with the current list.

    POI coordinates come from one of two sources (in priority order):

    1. **Manual override** — explicit ``lat``/``lng`` in frontmatter.
    2. **Nominatim geocoding** — ``place_query`` text, resolved via the
       OpenStreetMap Nominatim API.  A geocoding failure skips that one POI
       and logs a warning rather than aborting the whole sync.

    Parameters
    ----------
    session:
        Open ``AsyncSession``.  Caller owns the transaction.
    post_id:
        The integer PK of the ``posts`` row.
    pois_fm:
        Current list of POIs from frontmatter (may be empty).  The full
        set of existing rows is replaced — delete-then-insert keeps the
        logic simple and correct for any combination of adds, edits, and
        removals.
    http_client:
        Optional ``httpx.AsyncClient`` used for Nominatim requests.  When
        ``None`` a default client is created internally — pass an explicit
        client in tests to inject a mock transport.
    """
    # Delete all existing POIs for this post, then re-insert the current set.
    await session.execute(delete(PointOfInterest).where(PointOfInterest.post_id == post_id))

    if not pois_fm:
        return

    # Only open an HTTP client when at least one POI actually needs geocoding.
    _needs_geocoding = any(p.place_query is not None and p.lat is None and p.lng is None for p in pois_fm)
    _close_client = False
    client: httpx.AsyncClient | None = http_client
    if _needs_geocoding and client is None:
        client = httpx.AsyncClient(headers={"User-Agent": _NOMINATIM_UA})
        _close_client = True

    try:
        for poi_fm in pois_fm:
            point = await _resolve_poi_location_with_geocoding(poi_fm, client)
            if point is None:
                logger.warning(
                    "POI %r for post_id=%d has no usable coordinates — skipping",
                    poi_fm.name,
                    post_id,
                )
                continue

            poi = PointOfInterest(
                post_id=post_id,
                name=poi_fm.name,
                category=poi_fm.category,
                notes=poi_fm.notes,
                location=from_shape(point, srid=4326),
            )
            session.add(poi)
            logger.debug("Upserted POI %r for post_id=%d", poi_fm.name, post_id)
    finally:
        if _close_client and client is not None:
            await client.aclose()


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------


async def _geocode(query: str, client: httpx.AsyncClient) -> tuple[float, float] | None:
    """Call the Nominatim search API and return ``(lat, lon)`` on success.

    Enforces the 1 req/s rate limit required by Nominatim's usage policy.
    Any network error, non-200 response, or empty result set is logged as a
    warning and returns ``None`` — the caller decides whether to skip or retry.

    Parameters
    ----------
    query:
        Free-text place name or address, e.g. ``"Café Sonnenberg, Freiburg"``.
    client:
        An open ``httpx.AsyncClient``.  The caller owns its lifetime.

    Returns
    -------
    ``(latitude, longitude)`` floats on success, or ``None`` on any failure.
    """
    global _last_geocode_time  # noqa: PLW0603 — module-level rate-limit timestamp

    # Enforce Nominatim's 1 req/s cap before each call.
    loop = asyncio.get_running_loop()
    elapsed = loop.time() - _last_geocode_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_geocode_time = loop.time()

    try:
        resp = await client.get(
            _NOMINATIM_SEARCH_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": _NOMINATIM_UA},
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as exc:  # noqa: BLE001 — any network/HTTP/parse failure is non-fatal
        logger.warning("Nominatim request failed for %r: %s — POI skipped", query, exc)
        return None

    if not results:
        logger.warning("Nominatim: no results for %r — POI skipped", query)
        return None

    try:
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Nominatim: malformed response for %r: %s — POI skipped", query, exc)
        return None


async def _resolve_poi_location_with_geocoding(
    poi_fm: PoiFrontmatter,
    client: httpx.AsyncClient | None,
) -> Point | None:
    """Return a Shapely Point for the POI, trying geocoding if manual coords absent.

    Priority order:
    1. If ``lat`` and ``lng`` are both set, use them directly — no network call.
    2. If only ``place_query`` is set and a ``client`` is available, geocode.
    3. Otherwise return ``None`` (caller logs a warning and skips this POI).

    Parameters
    ----------
    poi_fm:
        Parsed POI frontmatter.
    client:
        ``httpx.AsyncClient`` for geocoding, or ``None`` to skip it.
    """
    # Manual override always wins — no network call.
    manual = _resolve_poi_location(poi_fm)
    if manual is not None:
        return manual

    # Geocoding path — only when place_query is present and a client is provided.
    if poi_fm.place_query is not None and client is not None:
        coords = await _geocode(poi_fm.place_query, client)
        if coords is not None:
            lat, lon = coords
            return Point(lon, lat)  # Shapely/PostGIS: (lon, lat)

    return None


# ---------------------------------------------------------------------------
# Internal helpers (GPX + route)
# ---------------------------------------------------------------------------


async def _get_existing_route(session: AsyncSession, post_id: int) -> Route | None:
    """Return the Route row for ``post_id``, or ``None`` if absent."""
    result = await session.execute(select(Route).where(Route.post_id == post_id))
    return result.scalar_one_or_none()


def _resolve_poi_location(poi_fm: PoiFrontmatter) -> Point | None:
    """Return a Shapely Point if ``lat``/``lng`` are both set, else ``None``.

    This is the fast, sync, no-network path.  Geocoding lives in
    :func:`_resolve_poi_location_with_geocoding`.
    """
    if poi_fm.lat is not None and poi_fm.lng is not None:
        return Point(poi_fm.lng, poi_fm.lat)  # Shapely/PostGIS: (lon, lat)
    return None


def _resolve_gpx_path(gpx_file: str, content_dir: Path) -> Path:
    """Resolve a GPX file reference to an absolute Path.

    Sveltia's ``file`` widget stores uploads prefixed with ``public_folder``
    (configured as ``/static/uploads``), so the frontmatter value looks like
    ``/static/uploads/route.gpx``.  Paths that start with ``/static/`` are
    resolved relative to the *project root* (``content_dir.parent.parent``
    when ``content_dir`` is ``content/posts/``), not the filesystem root.

    For all other paths:

    - Absolute paths are used as-is.
    - Relative paths are resolved against ``content_dir``.

    Parameters
    ----------
    gpx_file:
        Value from ``RouteFrontmatter.gpx_file``.
    content_dir:
        Directory passed into ``sync_posts`` (usually ``content/posts/``).

    Returns
    -------
    Absolute Path (may or may not exist — caller must check).
    """
    p = Path(gpx_file)
    if p.is_absolute():
        # Sveltia public path: "/static/uploads/route.gpx"
        # → project_root/static/uploads/route.gpx
        relative = Path(gpx_file.lstrip("/"))
        if relative.parts and relative.parts[0] == "static":
            return (content_dir.parent.parent / relative).resolve()
        return p
    return (content_dir / gpx_file).resolve()


_GpxStats = tuple[LineString, float, float, float, float | None]


async def _fetch_gpx_over_http(url: str, http_client: httpx.AsyncClient | None) -> str | None:
    """Fetch a GPX file's raw text over HTTP(S).

    Parameters
    ----------
    url:
        The ``http://``/``https://`` URL to fetch (an R2 public URL, per
        ``media_storage_r2.md`` Phase 2).
    http_client:
        Optional ``httpx.AsyncClient`` to reuse. When ``None`` a default
        client is created and closed internally — pass an explicit client
        in tests to inject a mock transport.

    Returns
    -------
    The response body as text on a successful ``200``, or ``None`` on any
    network error or non-2xx status (logged, not raised).
    """
    client = http_client
    close_client = False
    if client is None:
        client = httpx.AsyncClient()
        close_client = True

    try:
        response = await client.get(url, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch GPX %s: %s", url, exc)
        return None
    finally:
        if close_client:
            await client.aclose()

    return response.text


async def _parse_gpx(
    gpx_file: str,
    content_dir: Path,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> _GpxStats | None:
    """Parse a GPX file and return geometry + ride statistics.

    Parameters
    ----------
    gpx_file:
        Path or URL to the GPX file. A value starting with ``http://`` or
        ``https://`` (an R2-hosted upload, per ``media_storage_r2.md``
        Phase 2) is fetched over HTTP; anything else is resolved via
        :func:`_resolve_gpx_path` and read from local disk.
    content_dir:
        Directory used to resolve relative paths. Ignored when
        ``gpx_file`` is a URL.
    http_client:
        Optional ``httpx.AsyncClient`` used when ``gpx_file`` is a URL.
        When ``None`` a default client is created internally — pass an
        explicit client in tests to inject a mock transport.

    Returns
    -------
    A 5-tuple ``(linestring, distance_km, elevation_gain_m, elevation_loss_m,
    duration_minutes)`` on success, or ``None`` on any error.
    ``duration_minutes`` is ``None`` when the GPX has no timestamps.
    """
    if gpx_file.startswith(("http://", "https://")):
        gpx_text = await _fetch_gpx_over_http(gpx_file, http_client)
        if gpx_text is None:
            return None
        source = gpx_file
    else:
        path = _resolve_gpx_path(gpx_file, content_dir)
        if not path.exists():
            logger.error("GPX file not found: %s", path)
            return None
        try:
            gpx_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to read GPX %s: %s", path, exc)
            return None
        source = path

    try:
        gpx = gpxpy.parse(gpx_text)
    except Exception as exc:  # noqa: BLE001 — gpxpy raises many exception types
        logger.error("Failed to parse GPX %s: %s", source, exc)
        return None

    # Collect all track points across all tracks and segments.
    coords: list[tuple[float, float]] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                coords.append((pt.longitude, pt.latitude))

    if len(coords) < 2:
        logger.error("GPX %s has fewer than 2 track points — cannot form a LineString", source)
        return None

    linestring = LineString(coords)

    # ── Ride statistics ──────────────────────────────────────────────────
    # gpxpy works in metres; convert to km for distance.
    distance_km = (gpx.length_2d() or 0.0) / 1000.0

    uphill, downhill = gpx.get_uphill_downhill()
    elevation_gain_m = uphill or 0.0
    elevation_loss_m = downhill or 0.0

    duration_seconds = gpx.get_duration()
    duration_minutes: float | None = duration_seconds / 60.0 if duration_seconds is not None else None

    return linestring, distance_km, elevation_gain_m, elevation_loss_m, duration_minutes
