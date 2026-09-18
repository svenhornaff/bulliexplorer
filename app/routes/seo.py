"""Root-level SEO endpoints — robots.txt, sitemap.xml, feed.xml.

Phases 1-2 of docs/dev/seo_beyond_basics.md. Registered at the app root
(no prefix) — these are conventional well-known paths crawlers/readers
expect at exactly ``/robots.txt``, ``/sitemap.xml``, ``/feed.xml``, not
nested under ``/posts``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.models.post import Post
from app.services.seo import build_feed_xml, build_sitemap_xml, robots_txt

router = APIRouter()


async def _published_posts(db: AsyncSession) -> list[Post]:
    """Published (non-draft) posts, newest first — shared by sitemap + feed."""
    result = await db.execute(
        select(Post)
        .where(Post.is_draft == False)  # noqa: E712 — SQLAlchemy requires == not `is`
        .order_by(Post.published_date.desc())
    )
    return list(result.scalars().all())


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> PlainTextResponse:
    """Serve robots.txt with the AI training/citation crawler split.

    See ``app.services.seo.AI_TRAINING_CRAWLERS`` for the operator
    decision this encodes (docs/dev/seo_beyond_basics.md Phase 0).
    """
    settings = get_settings()
    return PlainTextResponse(robots_txt(settings.site_url))


@router.get("/sitemap.xml")
async def sitemap(
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> Response:
    """Serve sitemap.xml for the homepage, post list, and every published post."""
    settings = get_settings()
    posts = await _published_posts(db)
    return Response(content=build_sitemap_xml(posts, settings.site_url), media_type="application/xml")


@router.get("/feed.xml")
async def feed(
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> Response:
    """Serve an RSS 2.0 feed.xml of every published post, newest first."""
    settings = get_settings()
    posts = await _published_posts(db)
    return Response(content=build_feed_xml(posts, settings.site_url), media_type="application/rss+xml")
