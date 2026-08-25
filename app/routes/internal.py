"""Internal / operational endpoints + editor redirect.

- ``GET /editor`` / ``GET /editor/`` — redirects to Sveltia CMS static page.
- ``POST /internal/resync`` — re-runs sync_posts; requires X-Resync-Token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyHeader

from app.core.config import get_settings
from app.core.db import get_db_session
from app.services.post_sync import sync_posts
from app.utils.log_factory import get_logger

logger = get_logger(__name__)

# Two routers: one for the editor redirect (no prefix), one for /internal/*.
router = APIRouter()
_internal = APIRouter(prefix="/internal")


# ---------------------------------------------------------------------------
# Editor redirect
# ---------------------------------------------------------------------------


@router.get("/editor")
@router.get("/editor/")
async def editor_redirect() -> RedirectResponse:
    """Redirect /editor and /editor/ to the Sveltia CMS static index page.

    Sveltia CMS lives at ``/static/editor/index.html`` served by FastAPI's
    StaticFiles mount.  FastAPI StaticFiles does not serve directory indexes,
    so this one-line redirect makes ``/editor/`` a usable entry point without
    needing a Caddy rewrite rule.
    """
    return RedirectResponse(url="/static/editor/index.html", status_code=302)


# ---------------------------------------------------------------------------
# Resync endpoint
# ---------------------------------------------------------------------------

_TOKEN_HEADER = APIKeyHeader(name="X-Resync-Token", auto_error=False)


def _require_resync_token(token: str | None = Depends(_TOKEN_HEADER)) -> str:  # noqa: B008 — FastAPI Depends pattern
    """Dependency: reject requests missing or carrying the wrong resync token."""
    settings = get_settings()
    if not token or token != settings.resync_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Resync-Token header",
        )
    return token


@_internal.post("/resync", status_code=status.HTTP_200_OK)
async def resync(
    request: Request,
    db=Depends(get_db_session),  # noqa: B008 — FastAPI Depends pattern
    _token: str = Depends(_require_resync_token),  # noqa: B008 — FastAPI Depends pattern
) -> dict[str, object]:
    """Re-run ``sync_posts`` without restarting the container.

    Intended workflow on the server::

        git pull
        curl -X POST -H "X-Resync-Token: $RESYNC_TOKEN" \\
             https://bulliexplorer.com/internal/resync

    Returns
    -------
    dict
        ``{"status": "ok", "upserted": N, "deleted": N, "skipped": N}``
    """
    import app.main as main_module

    content_dir = main_module.BASE_DIR / "content" / "posts"
    logger.info("Manual resync triggered from %s", request.client)

    counts = await sync_posts(content_dir, db)
    # get_db_session commits on clean exit — no explicit commit needed here.

    logger.info("Resync complete: %s", counts)
    return {"status": "ok", **counts}
