"""GET /trips.geojson — the homepage's aggregate trip map data.

Phase 2b, Step 3 (docs/dev/bulliexplorer_experience_2027.md). Registered
at the app root (no prefix), same convention as app/routes/seo.py's
robots.txt/sitemap.xml/feed.xml — a conventional top-level data asset, not
nested under /posts.

This is the data contract for the not-yet-built homepage map section
(Phase 2b's final step). Its shape is a deliberate, direct answer to the
one concrete lesson from Phase 2b's performance spike: the spike's
stand-in payload (a real per-post amenities.geojson response) turned out
to be 6.4 MB, which was harmless there only because it loaded fully async
after paint. This endpoint has no such safety net once the real map
section exists, so its schema stays intentionally minimal — a
simplified/decimated route line and a handful of scalar properties per
post, nothing shaped like a per-post amenity dump.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from geoalchemy2.shape import to_shape
from shapely.geometry import Point as ShapelyPoint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.models.route import Route

logger = logging.getLogger(__name__)

router = APIRouter()

# Simplification tolerance for the aggregate map's route lines, in degrees
# (Shapely's simplify() operates in the geometry's own CRS units — our
# tracks are stored as WGS84 lon/lat, so this is degrees, not metres).
# ~0.01 degrees is ~1km at this project's latitudes — coarse enough to be
# pointless for a single trip page's own turn-by-turn map, but appropriate
# for a whole-Europe zoomed-out overview, which is this endpoint's only
# consumer. Not a guess: checked against the real production dataset
# while building this endpoint. An earlier, tighter 0.001 (~100m) value
# looked reasonable on the two shorter routes (695/16318 raw points) but
# left one long-distance route (dream-of-north, 63395 raw points) at 4822
# simplified coordinates — not "pointless for a whole-Europe view" at
# all. 0.01 brings that down to 841 while keeping the two shorter routes'
# shapes recognisable (feldberg: 695 -> 5, sunday-gravel-loop: 16318 -> 490).
_SIMPLIFY_TOLERANCE_DEGREES = 0.01

# Content changes only on a sync (post_sync.py), not per-request — a short
# max-age keeps the homepage map reasonably fresh without re-serializing
# this on every single load. Minutes, not the static-asset pattern's
# year-long immutable (fix_lcp_image_and_static_cache.md) — this data is
# far more volatile than a versioned asset, but nowhere near request-
# volatile either. Exact value is a placeholder pending real traffic
# patterns, per the doc's own "Caching" note.
_CACHE_CONTROL = "public, max-age=300"


@router.get("/trips.geojson")
async def trips_geojson(
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> JSONResponse:
    """Aggregate GeoJSON of every published post with a route or a POI.

    Powers the not-yet-built homepage "Explore the map" section (Phase 2b).
    Never 404s or errors on an empty site — an empty
    ``FeatureCollection`` is a valid, expected response; the frontend
    section itself is what decides not to render when there are zero
    features, not this endpoint.

    Returns
    -------
    JSONResponse
        A GeoJSON FeatureCollection. Features are ordered route-tier posts
        first, then poi_only-tier posts, each group newest-published-first.
        A post with neither a route nor any POI never appears. A route or
        POI with unparseable/invalid geometry is excluded and logged via
        ``logger.warning`` rather than surfaced as an error — this is an
        aggregate, discovery-oriented view where quietly excluding one bad
        row is correct, unlike a single post's own trip page (which never
        silently drops its map).
    """
    routed_result = await db.execute(
        select(Post, Route)
        .join(Route, Route.post_id == Post.id)
        .where(Post.is_draft == False)  # noqa: E712 — SQLAlchemy requires == not `is`
        .order_by(Post.published_date.desc())
    )
    routed_pairs = routed_result.all()
    routed_post_ids = [post.id for post, _ in routed_pairs]

    poi_result = await db.execute(
        select(Post, PointOfInterest)
        .join(PointOfInterest, PointOfInterest.post_id == Post.id)
        .where(
            Post.is_draft == False,  # noqa: E712 — SQLAlchemy requires == not `is`
            Post.id.notin_(routed_post_ids),
        )
        .order_by(Post.published_date.desc(), PointOfInterest.id.asc())
    )
    # One representative POI per post — the query above is ordered so a
    # given post's own POI rows sort together with the lowest-id POI
    # first, so "first occurrence wins" here reliably picks that lowest-id
    # POI, not an arbitrary one.
    poi_only_pairs: dict[int, tuple[Post, PointOfInterest]] = {}
    for post, poi in poi_result.all():
        if post.id not in poi_only_pairs:
            poi_only_pairs[post.id] = (post, poi)

    features: list[dict[str, Any]] = []
    for post, route in routed_pairs:
        feature = _route_feature(post, route)
        if feature is not None:
            features.append(feature)
    for post, poi in poi_only_pairs.values():
        feature = _poi_only_feature(post, poi)
        if feature is not None:
            features.append(feature)

    geojson = {"type": "FeatureCollection", "features": features}
    return JSONResponse(content=geojson, headers={"Cache-Control": _CACHE_CONTROL})


def _route_feature(post: Post, route: Route) -> dict[str, Any] | None:
    """Build a simplified LineString Feature for a routed post.

    Returns ``None`` (and logs a warning naming the post) when the
    route's geometry is missing or unparseable — excluded from this
    aggregate response per the doc's explicit empty/malformed-state
    handling.
    """
    if route.track is None:
        logger.warning("trips.geojson: route with no track geometry, post slug=%s", post.slug)
        return None
    try:
        shape = to_shape(route.track)  # type: ignore[arg-type] — WKBElement at runtime
        simplified = shape.simplify(_SIMPLIFY_TOLERANCE_DEGREES, preserve_topology=True)
        coordinates = list(simplified.coords)
        if len(coordinates) < 2:
            logger.warning(
                "trips.geojson: route simplifies to <2 coordinates, post slug=%s",
                post.slug,
            )
            return None
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coordinates},
            "properties": {
                "slug": post.slug,
                "title": post.title,
                "distance_km": route.distance_km,
                "elevation_gain_m": route.elevation_gain_m,
                "tier": "route",
            },
        }
    except Exception as exc:  # noqa: BLE001 — one bad route must not break the whole endpoint
        logger.warning("trips.geojson: route geometry parse error post slug=%s: %s", post.slug, exc)
        return None


def _poi_only_feature(post: Post, poi: PointOfInterest) -> dict[str, Any] | None:
    """Build a representative Point Feature for a POI-only post.

    Returns ``None`` (and logs a warning naming the post) when the POI's
    geometry is missing or unparseable.
    """
    if poi.location is None:
        logger.warning("trips.geojson: poi_only post with no POI location, post slug=%s", post.slug)
        return None
    try:
        shape = to_shape(poi.location)  # type: ignore[arg-type] — WKBElement at runtime
        assert isinstance(shape, ShapelyPoint)  # noqa: S101 — guaranteed by Geometry("POINT")
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [shape.x, shape.y]},
            "properties": {
                "slug": post.slug,
                "title": post.title,
                "tier": "poi_only",
            },
        }
    except Exception as exc:  # noqa: BLE001 — one bad POI must not break the whole endpoint
        logger.warning("trips.geojson: POI geometry parse error post slug=%s: %s", post.slug, exc)
        return None
