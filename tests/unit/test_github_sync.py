"""Unit tests for app/services/github_sync.py — no real network calls.

All httpx requests are mocked.  Tests verify:
- Files returned by the GitHub API are written to the correct local paths.
- Files present locally but absent from GitHub are deleted (reconciliation).
- A 404 from the API (directory doesn't exist yet) is handled gracefully.
- .gitkeep files are never written.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.github_sync import fetch_and_write

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.content = b"file content"
    resp.raise_for_status = MagicMock(side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}"))
    return resp


def _dir_listing(filenames: list[str]) -> list[dict]:
    return [
        {
            "type": "file",
            "name": name,
            "sha": f"sha-{name}",
            "download_url": f"https://raw.githubusercontent.com/test/{name}",
        }
        for name in filenames
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_writes_post_file(tmp_path):
    """A .md file in content/posts on GitHub is written locally."""
    listing = _dir_listing(["my-post.md"])
    empty_listing: list = []

    async def mock_get(url, **kwargs):
        if "content/posts" in url and "raw.githubusercontent" not in url:
            return _mock_response(200, listing)
        if "static/uploads" in url and "raw.githubusercontent" not in url:
            return _mock_response(200, empty_listing)
        # download_url fetch
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"# My Post\n\nBody."
        resp.raise_for_status = MagicMock()
        return resp

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=mock_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.github_sync.httpx.AsyncClient", return_value=mock_client):
        counts = await fetch_and_write(tmp_path, github_token="tok")  # noqa: S106 — test sentinel

    assert counts["fetched"] == 1
    written = tmp_path / "content" / "posts" / "my-post.md"
    assert written.exists()
    assert written.read_bytes() == b"# My Post\n\nBody."


@pytest.mark.unit
async def test_fetch_deletes_orphaned_local_file(tmp_path):
    """A local file no longer in GitHub is deleted on sync."""
    # Create a local file that isn't in the GitHub listing.
    posts_dir = tmp_path / "content" / "posts"
    posts_dir.mkdir(parents=True)
    orphan = posts_dir / "old-post.md"
    orphan.write_text("old content")

    empty_listing: list = []

    async def mock_get(url, **kwargs):
        if "raw.githubusercontent" in url:
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b"new"
            resp.raise_for_status = MagicMock()
            return resp
        return _mock_response(200, empty_listing)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=mock_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.github_sync.httpx.AsyncClient", return_value=mock_client):
        counts = await fetch_and_write(tmp_path, github_token="tok")  # noqa: S106 — test sentinel

    assert counts["deleted"] == 1
    assert not orphan.exists()


@pytest.mark.unit
async def test_fetch_404_directory_skipped_gracefully(tmp_path):
    """A 404 from GitHub (directory not yet in repo) is handled without error."""

    async def mock_get(url, **kwargs):
        return _mock_response(404, {"message": "Not Found"})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=mock_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.github_sync.httpx.AsyncClient", return_value=mock_client):
        counts = await fetch_and_write(tmp_path, github_token="tok")  # noqa: S106 — test sentinel

    assert counts["fetched"] == 0
    assert counts["deleted"] == 0


@pytest.mark.unit
async def test_fetch_skips_gitkeep(tmp_path):
    """.gitkeep files are never written locally."""
    listing = _dir_listing([".gitkeep"])
    empty_listing: list = []

    async def mock_get(url, **kwargs):
        if "raw.githubusercontent" in url:
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b""
            resp.raise_for_status = MagicMock()
            return resp
        if "content/posts" in url:
            return _mock_response(200, listing)
        return _mock_response(200, empty_listing)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=mock_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.github_sync.httpx.AsyncClient", return_value=mock_client):
        counts = await fetch_and_write(tmp_path, github_token="tok")  # noqa: S106 — test sentinel

    assert counts["fetched"] == 0
    assert not (tmp_path / "content" / "posts" / ".gitkeep").exists()


@pytest.mark.unit
async def test_fetch_creates_local_dir_if_missing(tmp_path):
    """Local directories are created if they don't exist yet."""
    listing = _dir_listing(["new-post.md"])
    empty_listing: list = []

    async def mock_get(url, **kwargs):
        if "raw.githubusercontent" in url:
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b"content"
            resp.raise_for_status = MagicMock()
            return resp
        if "content/posts" in url:
            return _mock_response(200, listing)
        return _mock_response(200, empty_listing)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=mock_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # Neither content/posts nor static/uploads exist under tmp_path.
    assert not (tmp_path / "content").exists()

    with patch("app.services.github_sync.httpx.AsyncClient", return_value=mock_client):
        await fetch_and_write(tmp_path, github_token="tok")  # noqa: S106 — test sentinel

    assert (tmp_path / "content" / "posts" / "new-post.md").exists()
