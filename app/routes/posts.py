"""Post list and single-post routes."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from geoalchemy2.shape import to_shape
from shapely.geometry import Point as ShapelyPoint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.models.nearby_amenity import NearbyAmenity
from app.models.point_of_interest import PointOfInterest
from app.models.post import Post
from app.models.route import Route
from app.services.seo import build_post_jsonld

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
    one. Trip-relevant metadata (distance/elevation gain/duration) for every
    listed post's route — not just the latest — is what
    docs/dev/bulliexplorer_experience_2027.md Phase 1's card redesign needs
    for the "more rides" grid, so routes for *all* listed posts are fetched
    with one ``IN``-scoped query — still "never an inner join" against
    ``Post``, same convention as ``post_detail``, and still exactly one
    extra round trip regardless of post count (was already a second query
    just for the latest post's route before this; now the same second query
    covers every post instead of only the first).
    """
    result = await db.execute(
        select(Post)
        .where(Post.is_draft == False)  # noqa: E712 — SQLAlchemy requires == not `is`
        .order_by(Post.published_date.desc())
    )
    posts = result.scalars().all()

    routes_by_post_id: dict[int, Route] = {}
    if posts:
        routes_result = await db.execute(select(Route).where(Route.post_id.in_([p.id for p in posts])))
        routes_by_post_id = {r.post_id: r for r in routes_result.scalars().all() if r.post_id is not None}

    latest_route = routes_by_post_id.get(posts[0].id) if posts else None

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "posts": posts,
            "latest_route": latest_route,
            "routes_by_post_id": routes_by_post_id,
            "year": datetime.now().year,
            # Homepage aggregate map (Phase 2b's final piece) — same
            # settings.tiles_url used by post_detail's own per-post map,
            # read into home-map.js via #explore-map's data-tiles-url
            # attribute rather than a second window.BULLIEXPLORER_*
            # inline-script payload (there's no other per-request data
            # this page's map needs baked in — the trip data itself
            # comes from a separate fetch to GET /trips.geojson).
            "tiles_url": get_settings().tiles_url,
        },
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

    # Auto-discovered amenities (Phase 4, gis_cycling_upgrade.md) are no
    # longer fetched or inlined here (docs/dev/review_17SEP2026.md F1) —
    # a route with 15k+ amenities blew the inline GeoJSON past 3.7MB
    # inside the HTML document itself, re-downloaded on every visit even
    # though the "Show nearby services" toggle defaults off. The template
    # only needs to know whether *any* amenities exist, to decide whether
    # to render the toggle at all — a cheap existence check, not the full
    # rows. The actual data is fetched lazily by the browser from
    # GET /posts/{slug}/amenities.geojson, only on first toggle check.
    has_amenities = False
    if route is not None:
        amenity_exists_result = await db.execute(
            select(NearbyAmenity.id).where(NearbyAmenity.route_id == route.id).limit(1)
        )
        has_amenities = amenity_exists_result.scalar_one_or_none() is not None

    # Convert to GeoJSON dicts for the template's inline JavaScript.
    # Jinja2's |tojson filter serialises these safely into <script> tags.
    route_geojson: dict[str, Any] | None = _route_to_geojson(route)
    pois_geojson: dict[str, Any] = _pois_to_geojson(list(pois))
    poi_category_chips: list[dict[str, str]] = _poi_category_chips(list(pois))

    # JSON-LD structured data (docs/dev/seo_beyond_basics.md Phase 3) —
    # BlogPosting always, Trip layered in only when `route` is not None.
    # Built here (not in the template) so app/services/seo.py stays
    # framework-free and independently unit-testable.
    jsonld = build_post_jsonld(post, route, settings.site_url, settings.legal_name or "Sven Hornaff")

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
            "poi_category_chips": poi_category_chips,
            "has_amenities": has_amenities,
            "amenities_geojson_url": f"/posts/{post.slug}/amenities.geojson" if has_amenities else None,
            "tiles_url": settings.tiles_url,
            "jsonld": jsonld,
            "year": datetime.now().year,
        },
    )


@router.get("/{slug}/amenities.geojson")
async def post_amenities_geojson(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> JSONResponse:
    """Lazily-fetched amenity GeoJSON for a post's map (F1, review_17SEP2026.md).

    Split out of ``post_detail`` so the (potentially 15k+ row) amenity
    FeatureCollection is never inlined into the HTML document — the
    browser fetches this endpoint only on first "Show nearby services"
    toggle check, not on every page load. Carries an ``ETag`` derived
    from the route's ``amenities_synced_at`` (amenities only change on a
    sync), so a revalidating client gets a cheap 304 instead of
    re-transferring the same multi-MB payload.

    Parameters
    ----------
    slug:
        The post's slug.

    Returns
    -------
    JSONResponse
        A GeoJSON FeatureCollection (possibly empty) of the route's
        nearby amenities, with an ``ETag`` header set. 404 for an
        unknown slug or a post with no route.
    """
    result = await db.execute(select(Post).where(Post.slug == slug))
    post = result.scalar_one_or_none()

    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    settings = get_settings()
    if post.is_draft and settings.is_production:
        raise HTTPException(status_code=404, detail="Post not found")

    route_result = await db.execute(select(Route).where(Route.post_id == post.id))
    route = route_result.scalar_one_or_none()

    if route is None:
        raise HTTPException(status_code=404, detail="Post has no route")

    amenity_result = await db.execute(select(NearbyAmenity).where(NearbyAmenity.route_id == route.id))
    amenities = list(amenity_result.scalars().all())

    etag = f'"amenities-{route.id}-{route.amenities_synced_at.isoformat() if route.amenities_synced_at else "never"}"'
    return JSONResponse(content=_amenities_to_geojson(amenities), headers={"ETag": etag})


# ---------------------------------------------------------------------------
# GeoJSON conversion helpers — framework-free, pure Python
# ---------------------------------------------------------------------------


def _poi_category_chips(pois: list[PointOfInterest]) -> list[dict[str, str]]:
    """Build a deduplicated, order-preserving list of POI category chips.

    Powers the "Places along the way" chip row (Phase 3a,
    docs/dev/bulliexplorer_experience_2027.md) below the map. Mirrors
    ``categoryLabel()`` in ``static/js/post-map.js`` exactly — only the
    first word of a snake_case category is capitalised (e.g.
    ``gas_station`` -> "Gas station", not "Gas Station") — so the chip
    row reads consistently with the labels already shown in the map's
    own POI popups, rather than introducing a second, slightly different
    humanisation rule.

    Parameters
    ----------
    pois:
        List of PointOfInterest ORM rows (may be empty), in query order.

    Returns
    -------
    list[dict[str, str]]
        One dict per distinct category, in first-occurrence order, each
        with "category" (the raw slug, e.g. "bike_shop") and "label"
        (humanised, e.g. "Bike shop") keys. Empty list if ``pois`` is
        empty or every POI has a falsy category.
    """
    seen: set[str] = set()
    chips: list[dict[str, str]] = []
    for poi in pois:
        category = poi.category
        if not category or category in seen:
            continue
        seen.add(category)
        words = category.split("_")
        label = " ".join(word.capitalize() if i == 0 else word for i, word in enumerate(words))
        chips.append({"category": category, "label": label})
    return chips


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


def _amenities_to_geojson(amenities: list[NearbyAmenity]) -> dict[str, Any]:
    """Convert NearbyAmenity rows to a GeoJSON FeatureCollection dict.

    Same shape/error-handling convention as :func:`_pois_to_geojson` —
    auto-discovered amenities are rendered as their own map source/layer
    (Phase 4, ``docs/dev/gis_cycling_upgrade.md``), visually distinct from
    and toggled independently of curated PointOfInterest markers.

    Parameters
    ----------
    amenities:
        List of NearbyAmenity ORM rows (may be empty).

    Returns
    -------
    GeoJSON FeatureCollection dict (``features`` may be empty).
    """
    features: list[dict[str, Any]] = []
    for amenity in amenities:
        if amenity.location is None:
            continue
        try:
            _shape = to_shape(amenity.location)  # type: ignore[arg-type] — WKBElement at runtime
            assert isinstance(_shape, ShapelyPoint)  # noqa: S101 — guaranteed by Geometry("POINT")
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [_shape.x, _shape.y]},
                    "properties": {
                        "name": amenity.name or "",
                        "category": amenity.category,
                        # Raw OSM tags (fix_amenity_overlay_ux.md Phase 3)
                        # — already loaded, just not previously passed
                        # through to the browser. The frontend popup
                        # builder picks specific keys (website, phone,
                        # etc.) out of this dict conditionally; sending
                        # the whole dict here keeps this function
                        # data-agnostic about which OSM keys happen to be
                        # interesting today, rather than hardcoding a
                        # subset server-side that would need updating
                        # every time the frontend wants one more.
                        "tags": amenity.tags or {},
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001 — skip one bad amenity, don't 404 the page
            logger.warning("NearbyAmenity geometry parse error id=%r: %s", amenity.id, exc)
            continue
    return {"type": "FeatureCollection", "features": features}
