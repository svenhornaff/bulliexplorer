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
import dataclasses
import datetime
import itertools
import logging
import math
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import gpxpy
import httpx
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
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

# Extended backoff before the NEXT chunk in a sync run, triggered only by
# an explicit HTTP 429 from Overpass (fix_overpass_urban_density_timeout.md
# Phase 4) — distinct from _MIN_OVERPASS_INTERVAL above, which paces
# request *frequency* and is already applied on every chunk regardless.
# Observed in production: three large, dense-area chunks in a row (each
# returning thousands of features) tripped a 429 even though the 1 req/s
# pace was respected throughout — a cumulative-load throttle, not a
# frequency one. 45s sits between the two general public-API backoff
# conventions (RFC 6585 doesn't mandate a value, and no Retry-After header
# was present in the observed 429) — long enough to plausibly clear a
# short abuse-protection window, short enough not to make a large route's
# sync impractically slow if it recurs a few times in one run.
_RATE_LIMIT_BACKOFF_S: float = 45.0

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

# Anti-redundant-work protection (docs/dev/fix_amenity_resync_freshness.md)
# — distinct from the cooldown above, which is anti-*burst* protection on
# a much shorter timescale. A route whose amenity data was already
# attempted recently AND whose geometry hasn't changed since gets skipped
# here regardless of how long ago the cooldown window itself closed —
# real-world amenities (campsites, shelters, water points) don't
# meaningfully change hour to hour, but a route left untouched for months
# should still eventually re-check rather than trust data forever. Days,
# not minutes — a project-wide constant, not per-route (see that doc's
# "Explicitly out of scope").
_AMENITY_FRESHNESS_WINDOW = datetime.timedelta(days=7)

_KM_PER_DEGREE_LAT: float = 111.0


@dataclasses.dataclass
class AmenitySyncStatus:
    """In-progress/last-run amenity sync progress for one route.

    Operator visibility (``docs/dev/fix_incremental_amenity_writes.md``
    Phase 2): checking "is this route's sync working, and how far along
    is it" used to mean SSH + ``docker compose logs`` + manual ``grep``,
    every single time. This is in-memory, process-local state —
    deliberately not persisted: it's operator-facing progress for *this*
    process's current or most recent run, not a durable record (the
    actual result of a sync is the ``NearbyAmenity`` rows themselves,
    already durable). Reset to a fresh instance at the start of every
    sync attempt, so a route's status always reflects its latest run,
    never a stale one from before a restart carried over.
    """

    chunks_succeeded: int = 0
    chunks_failed: int = 0
    chunks_total: int = 0
    in_progress: bool = False
    last_attempt_at: datetime.datetime | None = None


# route_id -> AmenitySyncStatus. Process-local, not shared across workers
# — fine for this project's single-process deployment
# (``bulliexplorer-tech-concept.md``); a multi-worker deployment would
# need this moved to the DB or a shared cache, not attempted here since
# it isn't warranted by the current deployment shape.
_amenity_sync_status: dict[int, AmenitySyncStatus] = {}


def get_amenity_sync_status(route_id: int) -> AmenitySyncStatus | None:
    """Return the current/last-run amenity sync status for a route, or
    ``None`` if no sync has ever been attempted for it in this process's
    lifetime (e.g. right after a restart, before any sync has run).
    """
    return _amenity_sync_status.get(route_id)


def get_all_amenity_sync_statuses() -> dict[int, AmenitySyncStatus]:
    """Return every route's current/last-run amenity sync status tracked
    in this process. Returns a shallow copy — callers must not mutate
    the tracker directly.
    """
    return dict(_amenity_sync_status)


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
) -> int | None:
    """Upsert or delete the Route row for a post.

    Deliberately does **not** touch Overpass/amenity discovery at all —
    see ``docs/dev/fix_startup_blocking_amenity_sync.md`` Phase 1. That
    was a design mistake this function used to make: a best-effort,
    already-designed-to-tolerate-failure enhancement (amenities) was
    inline in the one path (content sync) that's allowed to block
    startup/request/webhook handling entirely. Amenity discovery for a
    route this call upserted is the caller's responsibility now, via
    :func:`sync_route_amenities` — called separately, on its own
    schedule (typically a background task), using the route id this
    function returns.

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

    Returns
    -------
    int or None
        The route's id if a Route row exists for this post after this
        call (fresh insert or existing update), or ``None`` if there is
        no route (frontmatter had none, an existing row was deleted, or
        the GPX failed to parse). Callers use this to know which routes
        need amenity discovery.
    """
    existing = await _get_existing_route(session, post_id)

    if route_fm is None:
        # Route was removed from frontmatter — delete the orphaned row.
        if existing is not None:
            await session.delete(existing)
            logger.info("Deleted orphaned Route for post_id=%d", post_id)
        return None

    # Parse the GPX file.
    parsed = await _parse_gpx(route_fm.gpx_file, content_dir, http_client=http_client)
    if parsed is None:
        # Bad/missing GPX — skip, don't delete an existing row either;
        # treat as a transient error rather than a deliberate removal.
        logger.warning(
            "Skipping route upsert for post_id=%d — GPX could not be parsed",
            post_id,
        )
        return existing.id if existing is not None else None

    linestring, distance_km, elevation_gain_m, elevation_loss_m, duration_minutes, elevation_profile = parsed
    _check_tile_coverage(linestring, post_id, route_fm.name)

    if existing is None:
        now = datetime.datetime.now(datetime.UTC)
        route = Route(
            post_id=post_id,
            name=route_fm.name,
            description=route_fm.description,
            track=from_shape(linestring, srid=4326),
            distance_km=distance_km,
            elevation_gain_m=elevation_gain_m,
            elevation_loss_m=elevation_loss_m,
            duration_minutes=duration_minutes,
            elevation_profile=elevation_profile,
            # Initial insert counts as the geometry "just changed" — see
            # docs/dev/fix_amenity_resync_freshness.md Phase 1.
            track_updated_at=now,
        )
        session.add(route)
        logger.debug("Inserted Route for post_id=%d", post_id)
    else:
        route = existing
        changed = False
        updates: dict[str, object] = {
            "name": route_fm.name,
            "description": route_fm.description,
            "distance_km": distance_km,
            "elevation_gain_m": elevation_gain_m,
            "elevation_loss_m": elevation_loss_m,
            "duration_minutes": duration_minutes,
            "elevation_profile": elevation_profile,
        }
        for attr, value in updates.items():
            if getattr(existing, attr) != value:
                setattr(existing, attr, value)
                changed = True

        # Re-parse and compare geometry. Deliberately compares Shapely's
        # own `.wkb` on *both* sides (re-hydrating `existing.track` via
        # `to_shape` first) rather than the columns' raw `str()` forms —
        # `existing.track` round-trips through PostGIS as EWKB (SRID
        # embedded in the header, e.g. `0102000020e6100000...`) while a
        # freshly built `from_shape(...)` is plain WKB with no such header
        # (e.g. `010200000003000000...`), so those two string forms never
        # matched even for byte-identical geometry — a real, previously
        # silent bug that made this branch fire, and rewrite the row, on
        # every single re-sync regardless of whether the track actually
        # changed. Comparing via Shapely's own consistent encoding on both
        # sides is the actual apples-to-apples comparison this was always
        # meant to be — confirmed necessary while building the amenity
        # resync freshness check (docs/dev/fix_amenity_resync_freshness.md),
        # which depends on this branch only firing for genuine geometry
        # changes.
        existing_linestring = cast("LineString", to_shape(existing.track))  # type: ignore[arg-type] — WKBElement at runtime
        new_track = from_shape(linestring, srid=4326)
        if existing_linestring.wkb != linestring.wkb:
            existing.track = new_track  # type: ignore[assignment] — GeoAlchemy2 WKBElement is valid at runtime
            # Deliberately set only in this branch, not from the broader
            # `changed` flag above (which also fires for description/name
            # edits) — a prose-only edit must not look like a geometry
            # change, or the amenity resync freshness check
            # (docs/dev/fix_amenity_resync_freshness.md) is defeated.
            existing.track_updated_at = datetime.datetime.now(datetime.UTC)
            changed = True

        if changed:
            logger.debug("Updated Route for post_id=%d", post_id)
        else:
            logger.debug("Route for post_id=%d unchanged — no write", post_id)

    # Flush so route.id is populated for a fresh insert (an update already
    # has one) — the caller needs a real id back to schedule amenity
    # discovery against.
    await session.flush()
    return route.id


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


async def sync_route_amenities(
    session: AsyncSession,
    route_id: int,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Load a Route by id and run amenity discovery for it.

    Public entry point for callers that only have a route id, not an
    in-memory ``Route`` + parsed ``linestring`` — typically the
    background-task path (``docs/dev/fix_startup_blocking_amenity_sync.md``
    Phase 2/3): by the time amenity discovery actually runs, the content-
    sync session that upserted the route has already committed and
    closed, so the original ``Route`` ORM object and its in-memory
    ``linestring`` are gone. Re-fetching by id in the caller's own
    session is the only correct option here — the geometry itself is
    durable (it's a DB column), only the in-memory Python objects aren't.

    Tests that already have an in-memory ``Route`` + ``linestring`` (e.g.
    right after building both without a round-trip) should call
    :func:`sync_amenities` directly instead — that's still the lower-
    level primitive this function delegates to.

    Parameters
    ----------
    session:
        Open ``AsyncSession``.  Note that :func:`sync_amenities` commits
        its own writes per-chunk as it goes (see that function's
        docstring, ``docs/dev/fix_incremental_amenity_writes.md``) — this
        function does not add any transaction semantics of its own on
        top of that.
    route_id:
        The ``Route.id`` to sync amenities for.
    http_client:
        Optional ``httpx.AsyncClient`` used for Overpass requests, passed
        straight through to :func:`sync_amenities`.
    """
    route = await session.get(Route, route_id)
    if route is None:
        # The route was deleted (e.g. by a later post edit) between being
        # scheduled for amenity discovery and this call actually running
        # — entirely possible for the background-task path, where some
        # time passes between scheduling and execution. Nothing to sync.
        logger.warning("sync_route_amenities: route_id=%d no longer exists — skipping", route_id)
        return
    # to_shape()'s return type is the generic BaseGeometry — Route.track is
    # always a LINESTRING column (see app/models/route.py), so this is a
    # safe narrowing, not an assumption specific to this call site.
    linestring = cast("LineString", to_shape(route.track))  # type: ignore[arg-type] — WKBElement at runtime
    await sync_amenities(session, route, linestring, http_client=http_client)


async def sync_amenities(
    session: AsyncSession,
    route: Route,
    linestring: LineString,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Discover and upsert :class:`NearbyAmenity` rows for a route.

    Best-effort, **per-chunk incremental** write semantics
    (``docs/dev/fix_incremental_amenity_writes.md``) — a deliberate change
    from the original all-or-nothing design (queue every chunk's results
    in memory, write once only if every chunk succeeds). That design made
    sense for a typical route (a handful of chunks, high per-chunk
    reliability) but actively withheld real, already-fetched data
    indefinitely for a route needing many chunks against an unreliable
    free public API (Dream of North, ~30 chunks) — the probability of a
    fully clean run across 30 chunks is low enough that "wait for one"
    isn't a plan, and there was no existing good snapshot being protected
    in the first place for a route that had never once completed a full
    run.

    The core safety property is preserved, just scoped to the chunk
    instead of the whole route: a *failed* chunk never deletes or
    inserts anything for its own bbox this run, and never touches any
    other chunk's data. As each chunk *succeeds*, this function commits
    its own transaction immediately — deliberately, not left to the
    caller, since the whole point is that a reader (or an operator
    checking progress via a separate DB connection) can see a chunk's
    amenities the moment that chunk finishes, not only once every chunk
    in the route has. A caller that wraps this in a larger transaction of
    its own should know amenity writes commit independently, not
    atomically with the rest of that caller's work.

    Per successful chunk:

    - **Upsert by natural key** (``route_id``, ``osm_element_type``,
      ``osm_element_id`` — the DB's own ``uq_nearby_amenities_route_osm_
      element`` constraint) rather than blind insert. Adjacent chunks'
      buffer-padded bboxes overlap by design, so the same OSM element can
      legitimately be returned by more than one chunk; upserting means a
      second chunk re-reporting it updates the row in place instead of
      violating the unique constraint or creating a duplicate.
    - **Delete scoped to that chunk's own bbox**: existing rows whose
      ``location`` falls within this chunk's bbox but that this chunk's
      *fresh* result didn't return are deleted — this is what lets a
      genuinely-gone amenity actually disappear, at the granularity data
      arrives at, without requiring a perfect whole-route run to ever
      clean anything up. A row just outside this chunk's bbox (covered by
      a different chunk) is never touched by this delete.

    Parameters
    ----------
    session:
        Open ``AsyncSession``.  Caller owns the transaction for anything
        *other* than amenity writes — this function commits its own
        per-chunk writes directly (see above).
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

        # Freshness check (docs/dev/fix_amenity_resync_freshness.md) — is
        # the *most recent attempt* (success or failure, same acceptance
        # as the cooldown above; a route rarely completes every chunk
        # cleanly, see that doc's "Interaction with partial failures")
        # both recent enough AND for geometry that hasn't since changed?
        # `route.track_updated_at` is only ever bumped by a genuine
        # geometry change (sync_route's track-comparison branch, or
        # initial insert) — never by a content-only edit — so this can
        # never mask a real physical-path change, regardless of how the
        # two timestamps happen to compare.
        # `track_updated_at` is None only for a row that predates both
        # this column and its migration backfill (shouldn't happen in
        # practice — see docs/dev/fix_amenity_resync_freshness.md Phase
        # 1's backfill) — treated as "unknown, therefore not provably
        # unchanged" rather than assumed fresh, same conservative default
        # the backfill itself uses.
        track_updated_at = route.track_updated_at
        geometry_unchanged_since_last_sync = (
            track_updated_at is not None and track_updated_at <= route.amenities_synced_at
        )
        is_fresh = geometry_unchanged_since_last_sync and elapsed_since_last < _AMENITY_FRESHNESS_WINDOW
        if track_updated_at is not None and is_fresh:
            logger.info(
                "Amenity data for route_id=%d still fresh (synced %s ago, geometry unchanged since %s ago) — skipping",
                route.id,
                elapsed_since_last,
                now - track_updated_at,
            )
            return

    # Set (and committed) on every *attempted* sync, success or failure —
    # a failed attempt still counts against the cooldown, since retrying a
    # route that's already failing fast (e.g. Overpass mid-outage) is
    # exactly the burst pattern this cooldown exists to prevent. Committed
    # up front, before any chunk runs, so a crash mid-sync still leaves
    # the cooldown correctly started rather than retriable immediately.
    route.amenities_synced_at = now
    await session.commit()

    bboxes = _amenity_query_bboxes(linestring)

    # Operator visibility (fix_incremental_amenity_writes.md Phase 2) —
    # a fresh status object for this run, replacing whatever was tracked
    # from a previous run for this route, so status always reflects the
    # latest attempt.
    status = AmenitySyncStatus(chunks_total=len(bboxes), in_progress=True, last_attempt_at=now)
    _amenity_sync_status[route.id] = status

    _close_client = False
    client = http_client
    if client is None:
        # No timeout= needed here — overpass.py sets timeout=HTTP_TIMEOUT_S
        # directly on its own client.post() call, per request, regardless
        # of how the caller's client is configured. See
        # fix_overpass_urban_density_timeout.md "Root cause, corrected
        # (again)" for why the fix belongs there and not here.
        client = httpx.AsyncClient()
        _close_client = True

    chunks_succeeded = 0
    chunks_failed = 0
    try:
        # Sticky per-sync failover (docs/dev/gis_cycling_upgrade.md Phase
        # 5): once a chunk actually gets served by the mirror, subsequent
        # chunks in THIS sync try the mirror first too, rather than
        # wasting a round-trip re-proving an already-known-bad primary is
        # still down on every remaining chunk. Resets to the primary on
        # the next sync_amenities() call (a local variable, not module
        # state) — "for the rest of this sync run", not permanently.
        preferred_start = 0
        # Set once this sync run actually observes a 429 (see
        # _RATE_LIMIT_BACKOFF_S above) — sync-run-scoped, same pattern as
        # preferred_start, not module state: a rate limit hit during one
        # sync shouldn't extend the wait for an unrelated later sync.
        rate_limited_this_run = False
        for south, west, north, east in bboxes:
            loop = asyncio.get_running_loop()
            if rate_limited_this_run:
                logger.warning(
                    "received 429, backing off %.0fs before next chunk (route_id=%d)",
                    _RATE_LIMIT_BACKOFF_S,
                    route.id,
                )
                await asyncio.sleep(_RATE_LIMIT_BACKOFF_S)
                rate_limited_this_run = False
            else:
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
            if result_meta.get("rate_limited"):
                rate_limited_this_run = True
            if chunk_results is None:
                # This one chunk failed — touch nothing for its bbox this
                # run (no delete, no insert/update), but every other
                # chunk's already-written data in this same run is
                # unaffected. Continue to the next chunk rather than
                # aborting the whole route.
                chunks_failed += 1
                status.chunks_failed = chunks_failed
                logger.warning(
                    "Overpass amenity sync incomplete for route_id=%d (bbox %s,%s,%s,%s failed) — "
                    "leaving existing NearbyAmenity rows for this bbox untouched, continuing with "
                    "remaining chunks",
                    route.id,
                    south,
                    west,
                    north,
                    east,
                )
                continue

            await _write_amenity_chunk(session, route.id, south, west, north, east, chunk_results)
            chunks_succeeded += 1
            status.chunks_succeeded = chunks_succeeded
            status.chunks_failed = chunks_failed
    finally:
        if _close_client:
            await client.aclose()
        status.chunks_succeeded = chunks_succeeded
        status.chunks_failed = chunks_failed
        status.in_progress = False

    logger.info(
        "Amenity sync for route_id=%d complete — %d/%d chunk(s) succeeded and were written",
        route.id,
        chunks_succeeded,
        chunks_succeeded + chunks_failed,
    )


async def _write_amenity_chunk(
    session: AsyncSession,
    route_id: int,
    south: float,
    west: float,
    north: float,
    east: float,
    chunk_results: list[AmenityResult],
) -> None:
    """Write one successful chunk's results, then commit immediately.

    Deletes existing rows within this chunk's own bbox that this fresh
    result didn't return (genuinely-stale cleanup, scoped to what this
    query actually covers), then upserts what the chunk returned by its
    natural key. Adjacent chunks' bboxes overlap by design (buffer
    padding) — that overlap is exactly why the delete is scoped to *this*
    bbox only, never the whole route: a row belonging to a neighboring
    chunk's bbox that this chunk didn't happen to return this time must
    not be deleted by this chunk's write.

    Deduplicates ``chunk_results`` by ``(osm_element_type, osm_element_id)``
    first — Overpass can return the same element more than once within a
    single response for elements spanning the query's edge.
    """
    deduped: dict[tuple[str, int], AmenityResult] = {}
    for result in chunk_results:
        deduped[(result.osm_element_type, result.osm_element_id)] = result

    envelope = func.ST_MakeEnvelope(west, south, east, north, 4326)
    fresh_keys = {(result.osm_element_type, result.osm_element_id) for result in deduped.values()}

    stale_query = select(NearbyAmenity.osm_element_type, NearbyAmenity.osm_element_id).where(
        NearbyAmenity.route_id == route_id,
        func.ST_Within(NearbyAmenity.location, envelope),
    )
    existing_in_bbox = (await session.execute(stale_query)).all()
    stale_keys = [(t, i) for t, i in existing_in_bbox if (t, i) not in fresh_keys]
    if stale_keys:
        await session.execute(
            delete(NearbyAmenity).where(
                NearbyAmenity.route_id == route_id,
                func.ST_Within(NearbyAmenity.location, envelope),
                tuple_(NearbyAmenity.osm_element_type, NearbyAmenity.osm_element_id).in_(stale_keys),
            )
        )

    for result in deduped.values():
        stmt = pg_insert(NearbyAmenity).values(
            route_id=route_id,
            osm_element_type=result.osm_element_type,
            osm_element_id=result.osm_element_id,
            category=result.category,
            name=result.name,
            location=from_shape(Point(result.lon, result.lat), srid=4326),
            tags=result.tags,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_nearby_amenities_route_osm_element",
            set_={
                "category": stmt.excluded.category,
                "name": stmt.excluded.name,
                "location": stmt.excluded.location,
                "tags": stmt.excluded.tags,
            },
        )
        await session.execute(stmt)

    await session.commit()
    logger.info(
        "Wrote %d amenity row(s) for route_id=%d, bbox (%s,%s,%s,%s) — %d stale row(s) removed",
        len(deduped),
        route_id,
        south,
        west,
        north,
        east,
        len(stale_keys),
    )


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


_GpxStats = tuple[LineString, float, float, float, float | None, list[list[float]] | None]

_MAX_ELEVATION_PROFILE_POINTS = 300


def _downsample_elevation_profile(
    points: Sequence[tuple[float, float, float | None]],
    max_points: int = _MAX_ELEVATION_PROFILE_POINTS,
) -> list[list[float]] | None:
    """Downsample raw (lon, lat, elevation) track points to a fixed-size
    distance/elevation profile for the chart.

    Uses fixed-interval resampling by cumulative 2D distance (not by point
    index) so the shape of the profile is faithful even when a GPX has an
    uneven point density along the track. Never upsamples: a route
    recorded at a lower point count than ``max_points`` is passed through
    unchanged, only ever capped, never padded.

    Parameters
    ----------
    points:
        ``(lon, lat, elevation_m)`` tuples in track order.  ``elevation_m``
        may be ``None`` per-point for a partially-tagged GPX.
    max_points:
        Upper bound on the returned profile's length.

    Returns
    -------
    A list of ``[distance_km, elevation_m]`` pairs, or ``None`` if fewer
    than 2 points have elevation data at all (nothing meaningful to plot).
    """
    usable = [(lon, lat, elev) for lon, lat, elev in points if elev is not None]
    if len(usable) < 2:
        return None

    # Cumulative 2D distance in km along the *usable* points, using the
    # same planar-degrees-to-metres approximation gpxpy itself uses
    # internally for length_2d() (adequate at ride-track scale; this is a
    # chart shape, not a survey-grade distance figure — distance_km on
    # the Route row, computed by gpxpy directly, remains authoritative).
    cumulative_km = [0.0]
    for (lon1, lat1, _), (lon2, lat2, _) in itertools.pairwise(usable):
        mean_lat_rad = math.radians((lat1 + lat2) / 2.0)
        dx_km = (lon2 - lon1) * 111.320 * math.cos(mean_lat_rad)
        dy_km = (lat2 - lat1) * 110.574
        cumulative_km.append(cumulative_km[-1] + math.hypot(dx_km, dy_km))

    total_km = cumulative_km[-1]
    if len(usable) <= max_points or total_km <= 0:
        return [[round(d, 3), round(elev, 1)] for d, (_, _, elev) in zip(cumulative_km, usable, strict=True)]

    # Resample at N equal cumulative-distance steps, each step taking the
    # elevation of the nearest source point at or after that distance.
    profile: list[list[float]] = []
    step_km = total_km / (max_points - 1)
    source_idx = 0
    for step in range(max_points):
        target_km = step * step_km
        while source_idx < len(cumulative_km) - 1 and cumulative_km[source_idx] < target_km:
            source_idx += 1
        profile.append([round(target_km, 3), round(usable[source_idx][2], 1)])
    return profile


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
    A 6-tuple ``(linestring, distance_km, elevation_gain_m, elevation_loss_m,
    duration_minutes, elevation_profile)`` on success, or ``None`` on any
    error. ``duration_minutes`` is ``None`` when the GPX has no timestamps;
    ``elevation_profile`` is ``None`` when the GPX has fewer than 2 points
    with elevation data.
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

    # Collect all track points across all tracks and segments. elev is
    # per-point (not every recorder tags every point) — kept alongside
    # lon/lat in the same single walk, no second pass over gpx.tracks.
    coords: list[tuple[float, float]] = []
    points_with_elevation: list[tuple[float, float, float | None]] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                coords.append((pt.longitude, pt.latitude))
                points_with_elevation.append((pt.longitude, pt.latitude, pt.elevation))

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

    elevation_profile = _downsample_elevation_profile(points_with_elevation)

    return linestring, distance_km, elevation_gain_m, elevation_loss_m, duration_minutes, elevation_profile
