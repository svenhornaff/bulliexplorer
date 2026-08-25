"""Home route — redirects to the post list."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.get("/")
async def home():
    """Redirect the bare root to the post list.

    A dedicated landing page can replace this redirect later once there is
    enough curated content to justify one (Phase 5+).
    """
    return RedirectResponse(url="/posts/", status_code=302)
