"""Unit tests for app/services/background_sync.py.

Covers docs/dev/fix_startup_blocking_amenity_sync.md Phase 2/3's shared
scheduling/driver helper — no real asyncio.create_task lifecycle concerns
beyond what's exercised directly here (task creation, tracking, error
isolation, cancellation), no DB, no network.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.background_sync import (
    cancel_amenity_sync_tasks,
    schedule_amenity_sync,
    sync_amenities_for_routes,
)

# ---------------------------------------------------------------------------
# sync_amenities_for_routes — the actual per-route loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_sync_amenities_for_routes_calls_each_route_in_its_own_session():
    """Each route id gets its own session (opened via the factory, not
    a shared caller session — the whole point is this runs well after
    the caller's own session has closed) and is committed individually.
    """
    sessions_opened = []

    class _FakeSession:
        async def __aenter__(self):
            sessions_opened.append(self)
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            self.committed = True

    def _factory():
        return _FakeSession()

    with patch(
        "app.services.background_sync.sync_route_amenities", new_callable=AsyncMock
    ) as mock_sync_route_amenities:
        await sync_amenities_for_routes(_factory, [1, 2, 3])

    assert len(sessions_opened) == 3
    assert all(getattr(s, "committed", False) for s in sessions_opened)
    assert mock_sync_route_amenities.await_count == 3
    called_route_ids = [call.args[1] for call in mock_sync_route_amenities.await_args_list]
    assert called_route_ids == [1, 2, 3]


@pytest.mark.unit
async def test_sync_amenities_for_routes_isolates_one_routes_failure():
    """One route's sync raising must not abort the rest of the batch —
    the existing best-effort philosophy (sync_amenities already
    tolerates and logs its own failures) extended across routes too.
    """

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            pass

    def _factory():
        return _FakeSession()

    async def _fake_sync_route_amenities(session, route_id, **kwargs):
        if route_id == 2:
            raise RuntimeError("Overpass exploded")

    with patch(
        "app.services.background_sync.sync_route_amenities",
        side_effect=_fake_sync_route_amenities,
    ) as mock_sync_route_amenities:
        await sync_amenities_for_routes(_factory, [1, 2, 3])

    # All three routes were attempted despite route 2 raising.
    assert mock_sync_route_amenities.await_count == 3


@pytest.mark.unit
async def test_sync_amenities_for_routes_propagates_cancellation():
    """A CancelledError (redeploy/shutdown interrupting this task) must
    propagate, not be swallowed like a generic Exception \u2014 otherwise the
    task's own cancellation would never actually complete.
    """

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            pass

    def _factory():
        return _FakeSession()

    async def _fake_sync_route_amenities(session, route_id, **kwargs):
        raise asyncio.CancelledError

    with (
        patch(
            "app.services.background_sync.sync_route_amenities",
            side_effect=_fake_sync_route_amenities,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await sync_amenities_for_routes(_factory, [1])


# ---------------------------------------------------------------------------
# schedule_amenity_sync — task creation + tracking
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_schedule_amenity_sync_returns_none_for_empty_route_ids():
    """No point creating a task with nothing to do."""
    state = SimpleNamespace()
    task = schedule_amenity_sync(state, lambda: None, [], task_name="test")
    assert task is None
    assert not hasattr(state, "amenity_sync_tasks") or not state.amenity_sync_tasks


@pytest.mark.unit
async def test_schedule_amenity_sync_registers_task_on_state():
    """A non-empty route_ids list creates a task and registers it on the
    state object's task set — this is what makes it survive request/
    lifespan-scope exit without being garbage-collected.
    """
    state = SimpleNamespace()

    async def _fake_driver(*args, **kwargs):
        await asyncio.sleep(0)

    with patch("app.services.background_sync.sync_amenities_for_routes", side_effect=_fake_driver):
        task = schedule_amenity_sync(state, lambda: None, [1, 2], task_name="test_task")
        assert task is not None
        assert task in state.amenity_sync_tasks
        await task

    # The done-callback must have removed the finished task from the set.
    assert task not in state.amenity_sync_tasks


@pytest.mark.unit
async def test_schedule_amenity_sync_multiple_calls_dont_drop_references():
    """Concurrent callers (e.g. a resync and a webhook landing close
    together) must not overwrite each other's task reference \u2014 a set,
    not a single slot.
    """
    state = SimpleNamespace()

    async def _fake_driver(*args, **kwargs):
        await asyncio.sleep(0.01)

    with patch("app.services.background_sync.sync_amenities_for_routes", side_effect=_fake_driver):
        task_a = schedule_amenity_sync(state, lambda: None, [1], task_name="a")
        task_b = schedule_amenity_sync(state, lambda: None, [2], task_name="b")
        assert task_a is not None
        assert task_b is not None
        assert task_a in state.amenity_sync_tasks
        assert task_b in state.amenity_sync_tasks
        await asyncio.gather(task_a, task_b)


@pytest.mark.unit
async def test_schedule_amenity_sync_logs_unhandled_exception(caplog):
    """An unhandled exception in the background task must be logged via
    the done-callback, not silently vanish (a bare task's exception is
    otherwise only reported as "Task exception was never retrieved" at
    GC time, with no useful context).
    """
    state = SimpleNamespace()

    async def _fake_driver(*args, **kwargs):
        raise RuntimeError("boom")

    with (
        patch("app.services.background_sync.sync_amenities_for_routes", side_effect=_fake_driver),
        caplog.at_level("ERROR"),
    ):
        task = schedule_amenity_sync(state, lambda: None, [1], task_name="failing_task")
        assert task is not None
        with pytest.raises(RuntimeError):
            await task
        # Give the done-callback a tick to run.
        await asyncio.sleep(0)

    assert any("boom" in record.message or "RuntimeError" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# cancel_amenity_sync_tasks — shutdown path
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_cancel_amenity_sync_tasks_cancels_in_flight_tasks():
    """A still-running task must actually be cancelled (and awaited to
    completion) before this returns \u2014 the whole point is dispose_engine()
    never races an in-flight session.
    """
    state = SimpleNamespace()

    async def _long_running():
        await asyncio.sleep(10)

    task = asyncio.create_task(_long_running())
    state.amenity_sync_tasks = {task}

    await cancel_amenity_sync_tasks(state)

    assert task.cancelled() or task.done()


@pytest.mark.unit
async def test_cancel_amenity_sync_tasks_noop_with_no_tasks():
    """No tasks registered at all \u2014 must not raise."""
    state = SimpleNamespace()
    await cancel_amenity_sync_tasks(state)  # must not raise


@pytest.mark.unit
async def test_cancel_amenity_sync_tasks_ignores_already_done_tasks():
    """An already-finished task must not be cancelled (nothing to cancel)
    and must not cause an error.
    """
    state = SimpleNamespace()

    async def _quick():
        return None

    task = asyncio.create_task(_quick())
    await task
    state.amenity_sync_tasks = {task}

    await cancel_amenity_sync_tasks(state)  # must not raise
    assert task.done()
    assert not task.cancelled()
