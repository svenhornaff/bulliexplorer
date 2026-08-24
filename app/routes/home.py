"""Home page route — blog landing page."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def home(request: Request):
    """Render the blog home / landing page."""
    templates = request.app.state.templates

    # TODO: query published posts from DB, ordered by date desc
    posts: list = []

    return templates.TemplateResponse(
        request,
        "home.html",
        {"posts": posts, "year": datetime.now().year},
    )
