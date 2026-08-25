"""Home page route — blog landing page."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def home(request: Request):
    """Render the blog home / landing page."""
    templates = request.app.state.templates

    # TODO: query published posts from DB, ordered by date desc (Phase 4)
    posts: list = []

    return templates.TemplateResponse(
        request,
        "home.html",
        {"posts": posts, "year": datetime.now().year},
    )


class _PlaceholderPost:
    """Minimal post-like object for smoke-testing the post template.

    Removed in Phase 4 when the real route and DB query replace this.
    """

    slug = "placeholder-post"
    title = "A Gravel Day in the Black Forest"
    summary = "Single-track, mud, and a very questionable coffee stop."
    published_date = date(2025, 8, 24)
    cover_image = None
    tags = "gravel,adventure"
    body_html = (
        "<p>This is placeholder body content for template smoke-testing.</p>"
        "<p>Real content loads from the database in Phase 4.</p>"
    )


@router.get("/post-preview")
async def post_preview(request: Request):
    """Temporary route — renders post.html with a placeholder post object.

    Used only to verify the Phase 3 template during development.
    Removed in Phase 4 and replaced by GET /posts/{slug}.
    """
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "post.html",
        {"post": _PlaceholderPost(), "year": datetime.now().year},
    )
