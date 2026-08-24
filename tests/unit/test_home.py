"""Home page route tests."""

from __future__ import annotations

import pytest


@pytest.mark.unit
async def test_home_returns_200(client):
    resp = await client.get("/")
    assert resp.status_code == 200


@pytest.mark.unit
async def test_home_contains_title(client):
    resp = await client.get("/")
    assert "BulliExplorer" in resp.text


@pytest.mark.unit
async def test_home_empty_state(client):
    resp = await client.get("/")
    assert "No posts yet" in resp.text
