"""Shared fixtures for unit + integration tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    """Fresh FastAPI app instance per test."""
    return create_app()


@pytest.fixture
async def client(app):
    """Async test client — no real server needed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
