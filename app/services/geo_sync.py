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
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import gpxpy
import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.point_of_interest import PointOfInterest
from app.models.post_schema import PoiFrontmatter, RouteFrontmatter
from app.models.route import Route

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


async def sync_route(
    session: AsyncSession,
    post_id: int,
    route_fm: RouteFrontmatter | None,
    content_dir: Path,
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
        as a relative path.
    """
    existing = await _get_existing_route(session, post_id)

    if route_fm is None:
        # Route was removed from frontmatter — delete the orphaned row.
        if existing is not None:
            await session.delete(existing)
            logger.info("Deleted orphaned Route for post_id=%d", post_id)
        return

    # Parse the GPX file.
    parsed = _parse_gpx(route_fm.gpx_file, content_dir)
    if parsed is None:
        # Bad/missing GPX — skip, don't delete an existing row either;
        # treat as a transient error rather than a deliberate removal.
        logger.warning(
            "Skipping route upsert for post_id=%d — GPX could not be parsed",
            post_id,
        )
        return

    linestring, distance_km, elevation_gain_m, elevation_loss_m, duration_minutes = parsed

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

    return float(results[0]["lat"]), float(results[0]["lon"])


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

    If ``gpx_file`` is already absolute, use it as-is.  Otherwise resolve
    relative to ``content_dir``.

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
        return p
    return (content_dir / gpx_file).resolve()


_GpxStats = tuple[LineString, float, float, float, float | None]


def _parse_gpx(gpx_file: str, content_dir: Path) -> _GpxStats | None:
    """Parse a GPX file and return geometry + ride statistics.

    Parameters
    ----------
    gpx_file:
        Path to the GPX file, resolved via :func:`_resolve_gpx_path`.
    content_dir:
        Directory used to resolve relative paths.

    Returns
    -------
    A 5-tuple ``(linestring, distance_km, elevation_gain_m, elevation_loss_m,
    duration_minutes)`` on success, or ``None`` on any error.
    ``duration_minutes`` is ``None`` when the GPX has no timestamps.
    """
    path = _resolve_gpx_path(gpx_file, content_dir)
    if not path.exists():
        logger.error("GPX file not found: %s", path)
        return None

    try:
        with path.open(encoding="utf-8") as fh:
            gpx = gpxpy.parse(fh)
    except Exception as exc:  # noqa: BLE001 — gpxpy raises many exception types
        logger.error("Failed to parse GPX %s: %s", path, exc)
        return None

    # Collect all track points across all tracks and segments.
    coords: list[tuple[float, float]] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                coords.append((pt.longitude, pt.latitude))

    if len(coords) < 2:
        logger.error("GPX %s has fewer than 2 track points — cannot form a LineString", path)
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
