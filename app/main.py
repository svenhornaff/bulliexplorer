"""BulliExplorer — application factory + lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.db import (
    dispose_engine,
    get_session_factory,
    init_engine,
    release_advisory_lock,
    try_acquire_advisory_lock,
)
from app.services.background_sync import cancel_amenity_sync_tasks, schedule_amenity_sync
from app.services.post_sync import SyncResult, sync_posts
from app.utils.log_factory import configure_logging, get_logger

BASE_DIR = Path(__file__).resolve().parent.parent
logger = get_logger(__name__)

# Arbitrary fixed key for the startup-sync advisory lock (F5,
# docs/dev/review_17SEP2026.md) — any 64-bit int works, this one has no
# meaning beyond being unlikely to collide with a future unrelated use of
# Postgres advisory locks in this app.
_STARTUP_SYNC_LOCK_KEY = 84625179


def _sentry_before_send(event: dict[str, object], hint: dict[str, object]) -> dict[str, object] | None:
    """Drop expected HTTP errors (404s) so they don't pollute Sentry.

    Parameters
    ----------
    event
        The Sentry event payload.
    hint
        Additional context, including the original exception via ``exc_info``.

    Returns
    -------
    dict or None
        The event to send, or ``None`` to drop it.
    """
    exc_info = hint.get("exc_info")
    if exc_info:
        exc_tuple = (exc_info[0], exc_info[1], exc_info[2]) if isinstance(exc_info, (list, tuple)) else None  # type: ignore[index]
        if exc_tuple is not None:
            exc = exc_tuple[1]
            # Both Starlette and FastAPI HTTPException have .status_code
            if hasattr(exc, "status_code") and exc.status_code == 404:  # noqa: PLR2004 — HTTP status code
                return None
    # Keep only method + a URL without credentials, query parameters or fragments.
    from urllib.parse import urlsplit, urlunsplit

    event.pop("user", None)
    event.pop("extra", None)
    event.pop("breadcrumbs", None)
    request = event.get("request")
    if isinstance(request, dict):
        clean_request = {}
        if "method" in request:
            clean_request["method"] = request["method"]
        url = request.get("url")
        if isinstance(url, str):
            try:
                parts = urlsplit(url)
                clean_request["url"] = urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))
            except ValueError:
                pass  # Malformed URLs are omitted rather than forwarded.
        event["request"] = clean_request
    # Exception messages can still contain application data: project-side
    # scrubbing remains required. Stack-frame locals are disabled at init.
    return event


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    logger.info("BulliExplorer starting up")

    # --- Sentry (error tracking) --------------------------------------------
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=0.0,
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            before_send=_sentry_before_send,  # type: ignore[arg-type] — Sentry Event is a TypedDict; our signature is compatible at runtime
        )
        logger.info("Sentry initialised (env=%s)", settings.app_env)
    else:
        logger.info("SENTRY_DSN not set — Sentry disabled")

    init_engine(settings.database_url)

    # Sync Markdown posts → DB on every startup so new/changed files are
    # picked up automatically without a manual step. Deliberately does
    # NOT include amenity discovery (Overpass) inline — that used to be
    # threaded through here and could block the app from ever reporting
    # healthy for several minutes on a route needing several retried/
    # split/rate-limited Overpass chunks. See
    # docs/dev/fix_startup_blocking_amenity_sync.md. Content sync itself
    # (this call) is fast and has no such failure mode — it stays
    # blocking, since a reader hitting a post needs it to actually exist.
    # Dockerfile runs `uvicorn --workers 2`; FastAPI's lifespan runs once
    # per worker process, not once per deploy, so without a lock, content
    # sync runs twice on every deploy — double parsing, double upserts
    # racing on the same rows, plus a race window where both workers can
    # read a stale `amenities_synced_at` before either commits (F5,
    # docs/dev/review_17SEP2026.md). pg_try_advisory_lock is non-blocking:
    # the first worker to reach here takes it and does the real sync; any
    # other worker sees it already held and skips straight through with
    # an empty SyncResult (no amenity_route_ids, so it schedules no
    # redundant amenity-discovery task either).
    content_dir = BASE_DIR / "content" / "posts"
    session_factory = get_session_factory()
    async with session_factory() as session:
        acquired_lock = await try_acquire_advisory_lock(session, _STARTUP_SYNC_LOCK_KEY)
        if acquired_lock:
            try:
                result = await sync_posts(content_dir, session)
                await session.commit()
            finally:
                await release_advisory_lock(session, _STARTUP_SYNC_LOCK_KEY)
        else:
            logger.info("Startup sync lock held by another worker — skipping")
            result = SyncResult()

    if settings.enable_amenity_discovery:
        schedule_amenity_sync(
            app.state,
            session_factory,
            result.amenity_route_ids,
            task_name="amenity_sync_startup",
        )

    yield
    logger.info("BulliExplorer shutting down")
    await cancel_amenity_sync_tasks(app.state)
    await dispose_engine()


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    configure_logging(json_output=settings.log_json)

    app = FastAPI(
        title="BulliExplorer",
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Static files & templates -------------------------------------------
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    # StaticFiles doesn't set Cache-Control on its own — only ETag/
    # Last-Modified, so browsers fall back to heuristic caching (which can
    # hold a stale CSS/JS file indefinitely with no revalidation, notably
    # in Safari). `no-cache` forces a conditional GET on every request;
    # ETag/Last-Modified are already there, so an unchanged file gets a
    # cheap 304, and a changed one (right after a deploy) is never served
    # stale.
    @app.middleware("http")
    async def _static_cache_headers(request, call_next):  # noqa: ANN001, ANN202 — Starlette's own untyped middleware signature
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # Store templates on app.state so routes can access them
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    # Canonical site origin available to every template without threading
    # it through each route's context dict (docs/dev/seo_beyond_basics.md
    # Phase 2/3) — used for canonical links, OG/Twitter URLs, and the
    # sitemap/feed/robots.txt routes' own absolute URLs (via get_settings()
    # directly, not this global).
    app.state.templates.env.globals["site_url"] = settings.site_url

    # --- Routers -------------------------------------------------------------
    from app.routes.home import router as home_router
    from app.routes.internal import _internal as internal_router
    from app.routes.internal import router as editor_router
    from app.routes.legal import LegalContentUnavailable
    from app.routes.legal import router as legal_router
    from app.routes.posts import router as posts_router
    from app.routes.seo import router as seo_router

    # /impressum and /datenschutz are HTML pages, not an API — a bare JSON
    # 503 body (FastAPI's HTTPException default) reads as a broken API
    # endpoint to a site visitor, not "content not published yet". Scoped
    # to this one exception type only: every other route's HTTPException
    # (health, webhook, future API routes) keeps rendering as JSON.
    @app.exception_handler(LegalContentUnavailable)
    async def _legal_content_unavailable(request: Request, exc: LegalContentUnavailable):  # noqa: ANN202 — Starlette's own untyped handler signature
        return app.state.templates.TemplateResponse(
            request=request,
            name="legal_unavailable.html",
            context={"title": exc.title},
            status_code=503,
        )

    app.include_router(legal_router)
    app.include_router(seo_router)
    app.include_router(home_router)
    app.include_router(posts_router)
    app.include_router(editor_router)
    app.include_router(internal_router)

    # --- Health endpoint -----------------------------------------------------
    @app.api_route("/health", methods=["GET", "HEAD"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
