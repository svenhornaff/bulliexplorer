"""Geo sync service — GPX parsing and Route/PointOfInterest upsert/delete.

Extends the post sync pipeline (post_sync.py) to handle the geo data
embedded in a post's frontmatter: a GPX track → Route row, and manual
lat/lng POIs → PointOfInterest rows.

Design rules (per AGENTS.md):
- **Framework-free**: no FastAPI, Jinja2, or sqladmin imports.
- **Resilient**: a bad GPX or a missing file is skipped with an error log;
  it must not abort the sync for the post as a whole.
- **Reconciling**: if a post's frontmatter previously had a route/POIs and
  a later edit removes them, the now-orphaned DB rows are deleted.
- **Idempotent**: re-syncing unchanged content produces no DB writes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import gpxpy
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.point_of_interest import PointOfInterest
from app.models.post_schema import PoiFrontmatter, RouteFrontmatter
from app.models.route import Route

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


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
) -> None:
    """Replace all PointOfInterest rows for a post with the current list.

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
    """
    # Delete all existing POIs for this post, then re-insert the current set.
    # This avoids the complexity of diffing by name/position.
    await session.execute(delete(PointOfInterest).where(PointOfInterest.post_id == post_id))

    for poi_fm in pois_fm:
        point = _resolve_poi_location(poi_fm)
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_existing_route(session: AsyncSession, post_id: int) -> Route | None:
    """Return the Route row for ``post_id``, or ``None`` if absent."""
    result = await session.execute(select(Route).where(Route.post_id == post_id))
    return result.scalar_one_or_none()


def _resolve_poi_location(poi_fm: PoiFrontmatter) -> Point | None:
    """Return a Shapely Point if ``lat``/``lng`` are set, else ``None``.

    Phase 3 will add Nominatim resolution for ``place_query``; for now the
    manual override is the only path that produces a coordinate.
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
