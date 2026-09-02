"""Post list and single-post routes."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from geoalchemy2.shape import to_shape
from shapely.geometry import Point as ShapelyPoint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.models.route import Route

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts")


@router.get("/")
async def post_list(
    request: Request,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
):
    """List all published (non-draft) posts, newest first.

    The homepage (Phase 3, docs/dev/ui_ux_refresh.md §6.1) gives the latest
    post a larger hero treatment including its route stat chips, if it has
    one. The route is fetched with a second, separate optional query — same
    "never an inner join" convention as ``post_detail`` — only for the
    latest post, not joined across the whole list.
    """
    result = await db.execute(
        select(Post)
        .where(Post.is_draft == False)  # noqa: E712 — SQLAlchemy requires == not `is`
        .order_by(Post.published_date.desc())
    )
    posts = result.scalars().all()

    latest_route: Route | None = None
    if posts:
        route_result = await db.execute(select(Route).where(Route.post_id == posts[0].id))
        latest_route = route_result.scalar_one_or_none()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "home.html",
        {"posts": posts, "latest_route": latest_route, "year": datetime.now().year},
    )


@router.get("/{slug}")
async def post_detail(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
):
    """Render a single post, including optional route and POI data.

    Route and POI data are fetched with separate optional queries — never an
    inner join — so posts without geo data are never excluded.  Draft posts
    are visible in development, 404 in production.  Unknown slugs always 404.
    """
    result = await db.execute(select(Post).where(Post.slug == slug))
    post = result.scalar_one_or_none()

    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    settings = get_settings()
    if post.is_draft and settings.is_production:
        raise HTTPException(status_code=404, detail="Post not found")

    # ── Optional geo data (separate queries — LEFT JOIN semantics) ───────────
    route_result = await db.execute(select(Route).where(Route.post_id == post.id))
    route = route_result.scalar_one_or_none()

    poi_result = await db.execute(select(PointOfInterest).where(PointOfInterest.post_id == post.id))
    pois = poi_result.scalars().all()

    # Convert to GeoJSON dicts for the template's inline JavaScript.
    # Jinja2's |tojson filter serialises these safely into <script> tags.
    route_geojson: dict[str, Any] | None = _route_to_geojson(route)
    pois_geojson: dict[str, Any] = _pois_to_geojson(list(pois))

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "post.html",
        {
            "post": post,
            "route": route,
            "pois": pois,
            "route_geojson": route_geojson,
            "pois_geojson": pois_geojson,
            "tiles_url": settings.tiles_url,
            "year": datetime.now().year,
        },
    )


# ---------------------------------------------------------------------------
# GeoJSON conversion helpers — framework-free, pure Python
# ---------------------------------------------------------------------------


def _route_to_geojson(route: Route | None) -> dict[str, Any] | None:
    """Convert a Route's PostGIS track to a GeoJSON Feature dict.

    Returns ``None`` when there is no route or the track geometry is absent
    (e.g. a test fixture with ``track=None``).

    Parameters
    ----------
    route:
        Route ORM row, or ``None`` if the post has no route.

    Returns
    -------
    GeoJSON Feature dict, or ``None``.
    """
    if route is None or route.track is None:
        return None
    try:
        shape = to_shape(route.track)  # type: ignore[arg-type] — WKBElement at runtime
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": list(shape.coords)},
            "properties": {"name": route.name},
        }
    except Exception as exc:  # noqa: BLE001 — geometry parse failure must not 404 a post
        logger.warning("Route geometry parse error post_id=%s: %s", route.post_id, exc)
        return None


def _pois_to_geojson(pois: list[PointOfInterest]) -> dict[str, Any]:
    """Convert PointOfInterest rows to a GeoJSON FeatureCollection dict.

    POIs whose geometry cannot be parsed are skipped with a warning rather
    than aborting the page render.

    Parameters
    ----------
    pois:
        List of PointOfInterest ORM rows (may be empty).

    Returns
    -------
    GeoJSON FeatureCollection dict (``features`` may be empty).
    """
    features: list[dict[str, Any]] = []
    for poi in pois:
        if poi.location is None:
            continue
        try:
            _shape = to_shape(poi.location)  # type: ignore[arg-type] — WKBElement at runtime
            assert isinstance(_shape, ShapelyPoint)  # noqa: S101 — guaranteed by Geometry("POINT")
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [_shape.x, _shape.y]},
                    "properties": {
                        "name": poi.name,
                        "category": poi.category,
                        "notes": poi.notes or "",
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001 — skip one bad POI, don't 404 the page
            logger.warning("POI geometry parse error name=%r: %s", poi.name, exc)
            continue
    return {"type": "FeatureCollection", "features": features}
