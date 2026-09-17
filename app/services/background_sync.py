"""Background amenity-discovery task scheduling.

Shared by all three call sites that need to run Overpass-dependent
amenity discovery *without* blocking their own caller — the lifespan
startup, ``POST /internal/resync``, and the GitHub webhook handler. See
``docs/dev/fix_startup_blocking_amenity_sync.md`` for the incident and
design this exists to fix: amenity discovery was inline in
``sync_route``, in the one place (content sync) that's allowed to block
traffic entirely, and every resilience fix added to Overpass handling
(90s timeouts, mirror fallback, bbox splitting, 45s rate-limit backoff)
made that worst case slower, not just more reliable.

One shared driver + scheduling helper, used identically by all three
callers, so there's exactly one shutdown-cancellation code path to
reason about rather than three subtly different ones.

Design rules (per AGENTS.md): framework-free — no fastapi, jinja2, or
sqladmin imports. Callers pass in whatever object they use to hold task
references (typically FastAPI's ``app.state``, but this module only ever
touches it via ``getattr``/``setattr`` on a plain object, never imports
FastAPI itself).
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services.geo_sync import sync_route_amenities
from app.utils.log_factory import get_logger

logger = get_logger(__name__)

# Attribute name used on whatever state object callers pass in — a
# set[asyncio.Task], not a single slot, so concurrent callers (e.g. a
# resync and a webhook delivery landing close together) don't race each
# other and drop a task reference (fix_startup_blocking_amenity_sync.md
# Phase 3's concurrency note).
_TASK_SET_ATTR = "amenity_sync_tasks"


async def sync_amenities_for_routes(
    session_factory: async_sessionmaker,
    route_ids: list[int],
) -> None:
    """Run amenity discovery for every route id, in its own session.

    Runs in a fresh session (not the caller's, which has typically
    already committed and closed by the time this actually executes) —
    owns its own transaction and commits once per route, immediately
    after that route's sync, so one route's amenities are visible as
    soon as they're ready rather than held back by the whole batch.

    Errors are isolated per route: one route's Overpass failure (or any
    other exception) is logged and the loop continues — the existing
    best-effort philosophy (``sync_amenities`` already tolerates and
    logs its own failures) extended to apply across routes within one
    batch too, not just within one route's chunks.

    Parameters
    ----------
    session_factory:
        An ``async_sessionmaker`` (e.g. ``get_session_factory()``) — a
        factory, not an already-open session, since this may run well
        after the caller's own session has closed.
    route_ids:
        Route ids to sync amenities for, typically
        ``SyncResult.amenity_route_ids`` from a prior ``sync_posts()``
        call.
    """
    logger.info("Starting background amenity sync for %d route(s)", len(route_ids))
    synced = 0
    for route_id in route_ids:
        try:
            async with session_factory() as session:
                await sync_route_amenities(session, route_id)
                await session.commit()
            synced += 1
        except asyncio.CancelledError:
            # A redeploy/shutdown cancelling this task mid-route is
            # expected and not an error — the next startup or webhook
            # sync picks the remaining routes up again (amenities are
            # always resynced from scratch, no partial-route state to
            # lose). Propagate rather than swallow so the task's own
            # cancellation actually completes.
            logger.info(
                "Background amenity sync cancelled after %d/%d route(s) — a redeploy or shutdown interrupted it; "
                "the next sync picks up the rest",
                synced,
                len(route_ids),
            )
            raise
        except Exception:  # noqa: BLE001 — isolate one route's failure from the rest of the batch
            logger.exception("Background amenity sync failed for route_id=%d — continuing with the rest", route_id)
    logger.info("Background amenity sync complete — %d/%d route(s) succeeded", synced, len(route_ids))


def _log_task_exception(task: asyncio.Task) -> None:
    """Done-callback: log an unhandled exception instead of letting it
    vanish silently (a bare background task's exception is otherwise
    only ever reported as "Task exception was never retrieved" at GC
    time, with no useful context)."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background amenity sync task failed: %s: %s", type(exc).__name__, exc, exc_info=exc)


def schedule_amenity_sync(
    state: Any,
    session_factory: async_sessionmaker,
    route_ids: list[int],
    *,
    task_name: str,
) -> asyncio.Task | None:
    """Start :func:`sync_amenities_for_routes` as a tracked background task.

    Returns ``None`` (schedules nothing) if ``route_ids`` is empty — no
    point creating a task with nothing to do.

    The task is registered into ``state``'s task set (created on first
    use) and removes itself on completion via a done-callback, so
    ``state``'s set only ever holds genuinely in-flight tasks — safe to
    iterate at shutdown without accumulating finished ones.

    Parameters
    ----------
    state:
        Any object used to hold task references across calls —
        typically a FastAPI app's ``app.state``. Never imported or typed
        as FastAPI's ``State`` here; only ever touched via
        getattr/setattr, per this module's framework-free design rule.
    session_factory:
        Passed straight through to :func:`sync_amenities_for_routes`.
    route_ids:
        Passed straight through to :func:`sync_amenities_for_routes`.
    task_name:
        Passed to ``asyncio.create_task(..., name=...)`` — shows up in
        ``asyncio.all_tasks()`` and log output, distinguishing e.g. the
        startup task from a resync-triggered one.
    """
    if not route_ids:
        return None

    tasks: set[asyncio.Task] = getattr(state, _TASK_SET_ATTR, None) or set()
    setattr(state, _TASK_SET_ATTR, tasks)

    task = asyncio.create_task(sync_amenities_for_routes(session_factory, route_ids), name=task_name)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    task.add_done_callback(_log_task_exception)
    return task


async def cancel_amenity_sync_tasks(state: Any) -> None:
    """Cancel every still-running task registered via :func:`schedule_amenity_sync`.

    Call from the lifespan shutdown, before disposing the DB engine —
    an in-flight task holding a session against a disposed engine would
    raise confusingly rather than being cleanly interrupted.
    """
    tasks: set[asyncio.Task] = getattr(state, _TASK_SET_ATTR, None) or set()
    in_flight = [t for t in tasks if not t.done()]
    if not in_flight:
        return

    logger.info("Cancelling %d in-flight background amenity sync task(s) for shutdown", len(in_flight))
    for task in in_flight:
        task.cancel()
    # Wait for cancellation to actually complete (swallowing the
    # CancelledError each task raises in response) rather than letting
    # dispose_engine() race an in-flight session close.
    await asyncio.gather(*in_flight, return_exceptions=True)
