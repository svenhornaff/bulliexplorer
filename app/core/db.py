"""Async database engine + session factory.

Usage
-----
- ``engine`` and ``async_session_factory`` are module-level singletons
  initialised lazily: *importing* this module does not open any connection.
  The engine is created on first import; the actual TCP connection happens
  only when a query is executed.
- Call ``init_engine(url)`` from the FastAPI lifespan to (re-)initialise
  with a specific URL (useful for tests that need to swap the URL).
- Call ``dispose_engine()`` from the lifespan shutdown to release the pool.
- Use ``get_db_session()`` as a FastAPI dependency in route handlers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.utils.log_factory import get_logger

logger = get_logger(__name__)

# Module-level engine + factory — replaced by init_engine() if called.
# Created lazily (no TCP connection) from the default settings URL.
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str | None = None) -> AsyncEngine:
    """Create (or replace) the async engine and session factory.

    Safe to call multiple times — each call replaces the previous singletons.
    Does **not** open a connection; the pool connects on first query.
    """
    global _engine, _async_session_factory  # noqa: PLW0603

    resolved_url = url or get_settings().database_url
    logger.info("Initialising async database engine")

    _engine = create_async_engine(
        resolved_url,
        # Echo SQL only when explicitly requested via env/settings.
        echo=False,
        # pool_pre_ping sends a lightweight SELECT 1 before handing a
        # connection from the pool — catches stale connections cleanly.
        pool_pre_ping=True,
    )
    _async_session_factory = async_sessionmaker(
        bind=_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    return _engine


async def dispose_engine() -> None:
    """Dispose the connection pool — call from the lifespan shutdown."""
    global _engine  # noqa: PLW0603

    if _engine is not None:
        logger.info("Disposing async database engine")
        await _engine.dispose()
        _engine = None


def get_engine() -> AsyncEngine:
    """Return the current engine, initialising it if not yet done."""
    if _engine is None:
        init_engine()
    assert _engine is not None  # noqa: S101 — guaranteed by init_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory, initialising the engine if needed."""
    if _async_session_factory is None:
        init_engine()
    assert _async_session_factory is not None  # noqa: S101
    return _async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency — yields a transactional ``AsyncSession``.

    Usage::

        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db_session)):
            result = await db.execute(text("SELECT 1"))
            ...

    The session is committed on clean exit and rolled back on exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
