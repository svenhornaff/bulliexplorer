"""Unit tests for app/core/db.py — no DB running required.

These tests verify:
- The engine is created without opening a TCP connection (lazy init).
- get_engine() and get_session_factory() always return a non-None object.
- init_engine() accepts an explicit URL and replaces the singletons.
- dispose_engine() is idempotent (safe to call when no engine exists).
- get_db_session() yields an AsyncSession (structural check, no query).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import app.core.db as db_module
from app.core.db import (
    dispose_engine,
    get_db_session,
    get_engine,
    get_session_factory,
    init_engine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def reset_engine():
    """Ensure the module-level singletons are cleaned up after every test."""
    yield
    # Dispose without caring whether an engine exists — idempotent.
    await dispose_engine()
    # Also clear the session factory reference so tests start clean.
    db_module._async_session_factory = None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_init_engine_returns_async_engine():
    """init_engine() returns an AsyncEngine built from the given URL."""
    engine = init_engine("postgresql+psycopg://postgres:postgres@localhost:5433/bulliexplorer")
    assert isinstance(engine, AsyncEngine)


@pytest.mark.unit
def test_init_engine_does_not_connect():
    """Creating the engine must not open a TCP connection.

    We use a deliberately unreachable host — if init_engine() tried to
    connect, this would raise an exception.
    """
    # This must not raise even though the host does not exist.
    engine = init_engine("postgresql+psycopg://nowhere:5432/nodb")
    assert isinstance(engine, AsyncEngine)


@pytest.mark.unit
def test_get_engine_initialises_if_none():
    """get_engine() auto-initialises from settings when called before init_engine()."""
    # Ensure singletons are clear before this specific test.
    db_module._engine = None  # noqa: SLF001
    db_module._async_session_factory = None  # noqa: SLF001

    engine = get_engine()
    assert isinstance(engine, AsyncEngine)


@pytest.mark.unit
def test_get_session_factory_returns_sessionmaker():
    """get_session_factory() returns an async_sessionmaker instance."""
    init_engine("postgresql+psycopg://postgres:postgres@localhost:5433/bulliexplorer")
    factory = get_session_factory()
    assert isinstance(factory, async_sessionmaker)


@pytest.mark.unit
async def test_dispose_engine_is_idempotent():
    """dispose_engine() must not raise when called with no engine set."""
    db_module._engine = None  # noqa: SLF001
    await dispose_engine()  # should not raise


@pytest.mark.unit
async def test_dispose_engine_clears_singleton():
    """After dispose_engine(), the module-level engine is None."""
    init_engine("postgresql+psycopg://postgres:postgres@localhost:5433/bulliexplorer")
    assert db_module._engine is not None  # noqa: SLF001
    await dispose_engine()
    assert db_module._engine is None  # noqa: SLF001


@pytest.mark.unit
async def test_get_db_session_yields_async_session():
    """get_db_session() yields an AsyncSession (structural, no real query).

    We use an unreachable DB URL — the generator must produce a session
    object without actually connecting (connection happens on first query).
    """
    init_engine("postgresql+psycopg://nowhere:5432/nodb")
    gen = get_db_session()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    # Clean up: send an exception to trigger rollback path without querying.
    try:
        await gen.athrow(GeneratorExit)
    except (GeneratorExit, StopAsyncIteration):
        pass
