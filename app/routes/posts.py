"""Post list and single-post routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.models.post import Post

router = APIRouter(prefix="/posts")


@router.get("/")
async def post_list(
    request: Request,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
):
    """List all published (non-draft) posts, newest first."""
    result = await db.execute(
        select(Post)
        .where(Post.is_draft == False)  # noqa: E712 — SQLAlchemy requires == not `is`
        .order_by(Post.published_date.desc())
    )
    posts = result.scalars().all()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "home.html",
        {"posts": posts, "year": datetime.now().year},
    )


@router.get("/{slug}")
async def post_detail(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
):
    """Render a single post.

    Draft posts are visible in development, 404 in production.
    Unknown slugs always 404.
    """
    result = await db.execute(select(Post).where(Post.slug == slug))
    post = result.scalar_one_or_none()

    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    settings = get_settings()
    if post.is_draft and settings.is_production:
        raise HTTPException(status_code=404, detail="Post not found")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "post.html",
        {"post": post, "year": datetime.now().year},
    )
