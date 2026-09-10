"""Internal / operational endpoints + editor redirect.

- ``GET /editor`` / ``GET /editor/`` — redirects to Sveltia CMS static page.
- ``POST /internal/resync`` — re-runs sync_posts; requires X-Resync-Token.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.security import APIKeyHeader

from app.core.config import get_settings
from app.core.db import get_db_session
from app.services.github_sync import fetch_and_write
from app.services.post_sync import sync_posts
from app.utils.log_factory import get_logger

logger = get_logger(__name__)

# Two routers: one for the editor redirect (no prefix), one for /internal/*.
router = APIRouter()
_internal = APIRouter(prefix="/internal")

_EDITOR_CONFIG_TEMPLATE = Path(__file__).resolve().parents[2] / "static" / "editor" / "config.yml"


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


@router.get("/editor/config.yml", response_class=PlainTextResponse)
async def editor_config() -> str:
    """Serve Sveltia's config.yml with the R2 media library block injected
    from server-side Settings — never from a git-tracked file.

    static/editor/config.yml (this file's on-disk template) stays free of
    any real credential values — it's a public static asset, permanently
    visible in git history the moment anything is written into it. The R2
    access_key_id/account_id are read from .env on the server (via
    Settings, never committed) and appended here at request time. If
    they're unset, the response is byte-identical to the static template —
    Sveltia falls back to git-based media uploads, exactly as it does
    today.

    index.html points Sveltia at this URL explicitly
    (<link rel="cms-config-url" href="/editor/config.yml">) rather than
    relying on Sveltia's same-directory default, since this route
    intentionally lives outside /static/ to avoid any routing precedence
    question against the StaticFiles mount.
    """
    settings = get_settings()
    base = _EDITOR_CONFIG_TEMPLATE.read_text()

    if settings.r2_access_key_id and settings.r2_account_id:
        r2_block = f"""
media_libraries:
  cloudflare_r2:
    access_key_id: {settings.r2_access_key_id}
    bucket: bulliexplorer
    account_id: {settings.r2_account_id}
    public_url: {settings.r2_public_url}
    prefix: media/
"""
        base += r2_block

    return base


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

    settings = get_settings()
    counts = await sync_posts(content_dir, db, enable_amenity_discovery=settings.enable_amenity_discovery)
    # get_db_session commits on clean exit — no explicit commit needed here.

    logger.info("Resync complete: %s", counts)
    return {"status": "ok", **counts}


# ---------------------------------------------------------------------------
# GitHub webhook endpoint
# ---------------------------------------------------------------------------

_DEVELOP_REF = "refs/heads/develop"


def _verify_github_signature(body: bytes, signature_header: str | None, secret: str) -> None:
    """Verify the X-Hub-Signature-256 header from GitHub.

    Raises 401 if the header is missing or the HMAC does not match.
    The raw request body is always read before parsing so the HMAC is
    computed over exactly what GitHub signed.

    Parameters
    ----------
    body:
        Raw request body bytes.
    signature_header:
        Value of the ``X-Hub-Signature-256`` header, e.g.
        ``"sha256=abc123..."``.
    secret:
        The ``WEBHOOK_SECRET`` from Settings.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed X-Hub-Signature-256 header",
        )
    expected = (
        "sha256="
        + hmac.new(
            secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )


@_internal.post("/webhook/github", status_code=status.HTTP_200_OK)
async def github_webhook(
    request: Request,
    db=Depends(get_db_session),  # noqa: B008 — FastAPI Depends pattern
) -> dict[str, object]:
    """Receive a GitHub push webhook and auto-publish content changes.

    Flow
    ----
    1. Verify ``X-Hub-Signature-256`` against ``WEBHOOK_SECRET`` — reject
       with 401 before reading the payload if the signature is wrong.
    2. Parse the JSON payload; ignore any push that is not to ``develop``.
    3. Fetch ``content/posts/`` from the GitHub Contents API using
       ``GITHUB_TOKEN``, pinned to the push's exact commit SHA (``after``)
       rather than the ``develop`` branch name — branch-based
       ``raw.githubusercontent.com`` URLs are CDN-cached for a few minutes
       keyed by URL, so two pushes to the same file within that window can
       have the second fetch served stale content from the first. A
       commit SHA is immutable, so the CDN can cache it forever safely.
    4. Write fetched files into the volume-mounted local directory.
    5. Run ``sync_posts()`` so the DB reflects the new/changed posts.

    Returns
    -------
    dict
        ``{"status": "ok"|"ignored", ...counts}``  or
        ``{"status": "ignored", "reason": "..."}`` for non-develop pushes.
    """
    import app.main as main_module

    settings = get_settings()
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    _verify_github_signature(body, signature, settings.webhook_secret)

    payload = await request.json()
    ref = payload.get("ref", "")

    if ref != _DEVELOP_REF:
        logger.info("Webhook: ignoring push to %s (not develop)", ref)
        return {"status": "ignored", "reason": f"push to {ref!r}, not develop"}

    # Pin the fetch to the push's exact commit SHA rather than the
    # `develop` branch name — see fetch_and_write's docstring for why.
    # Falls back to fetch_and_write's own branch-name default only if a
    # malformed payload is somehow missing `after`.
    commit_sha = payload.get("after")
    logger.info("Webhook: push to develop (%s) — fetching content from GitHub", commit_sha or "develop")

    fetch_kwargs = {"base_dir": main_module.BASE_DIR, "github_token": settings.github_token}
    if commit_sha:
        fetch_kwargs["ref"] = commit_sha
    fetch_counts = await fetch_and_write(**fetch_kwargs)

    content_dir = main_module.BASE_DIR / "content" / "posts"
    sync_counts = await sync_posts(content_dir, db, enable_amenity_discovery=settings.enable_amenity_discovery)

    logger.info("Webhook publish complete: fetch=%s sync=%s", fetch_counts, sync_counts)
    return {
        "status": "ok",
        "fetch": fetch_counts,
        "sync": sync_counts,
    }
