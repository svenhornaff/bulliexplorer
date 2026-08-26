"""Smoke tests for the Phase 2 editor static files.

Verifies:
- static/editor/index.html exists and loads the Sveltia CDN bundle.
- static/editor/config.yml exists and contains the required field names
  matching PostFrontmatter's actual YAML keys.
- No route in app/routes/ shadows /editor/ or /static/editor/.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Result

from app.core.db import get_db_session
from app.main import create_app

BASE_DIR = Path(__file__).resolve().parents[2]
INDEX_HTML = BASE_DIR / "static" / "editor" / "index.html"
CONFIG_YML = BASE_DIR / "static" / "editor" / "config.yml"


# ---------------------------------------------------------------------------
# Fixture — app with empty mock DB (needed for routes that use get_db_session)
# ---------------------------------------------------------------------------


async def _empty_db():
    session = AsyncMock()
    mock_result = MagicMock(spec=Result)
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    yield session


@pytest.fixture
async def mock_client():
    """App client with DB overridden — no real DB needed."""
    application = create_app()
    application.dependency_overrides[get_db_session] = _empty_db
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Static file tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_html_exists():
    assert INDEX_HTML.exists(), "static/editor/index.html must exist"


@pytest.mark.unit
def test_index_html_loads_sveltia_cdn():
    """index.html must load the Sveltia CMS bundle from the CDN."""
    content = INDEX_HTML.read_text()
    assert "cdn.jsdelivr.net" in content
    assert "sveltia-cms" in content


@pytest.mark.unit
def test_index_html_is_valid_html():
    content = INDEX_HTML.read_text()
    assert "<!DOCTYPE html>" in content
    assert "<html" in content
    assert "<script" in content


@pytest.mark.unit
def test_config_yml_exists():
    assert CONFIG_YML.exists(), "static/editor/config.yml must exist"


@pytest.mark.unit
def test_config_yml_is_valid_yaml():
    content = CONFIG_YML.read_text()
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)


@pytest.mark.unit
def test_config_yml_backend_github():
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    backend = parsed["backend"]
    assert backend["name"] == "github"
    assert backend["repo"] == "svenhornaff/bulliexplorer"
    assert backend["branch"] == "develop"
    # PAT auth — no base_url needed, auth_type must be token to suppress
    # the default OAuth button (which points at Netlify and returns 404).
    assert "base_url" not in backend
    assert backend.get("auth_type") == "token"


@pytest.mark.unit
def test_config_yml_media_folder():
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    assert parsed["media_folder"] == "static/uploads"
    assert parsed["public_folder"] == "/static/uploads"


@pytest.mark.unit
def test_config_yml_posts_collection():
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    collections = parsed["collections"]
    assert len(collections) == 1
    posts = collections[0]
    assert posts["name"] == "posts"
    assert posts["folder"] == "content/posts"
    assert posts["create"] is True


@pytest.mark.unit
def test_config_yml_date_field_uses_datetime_widget():
    """Sveltia deprecated the 'date' widget — must use 'datetime' with time_format: false."""
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    fields = parsed["collections"][0]["fields"]
    date_field = next(f for f in fields if f["name"] == "date")
    assert date_field["widget"] == "datetime", "Use widget: datetime (date widget is deprecated)"
    assert date_field.get("time_format") is False, "Set time_format: false for date-only output"


@pytest.mark.unit
def test_config_yml_field_names_match_frontmatter():
    """Field names in config.yml must match the actual YAML keys in *.md files,
    not the Python field names in PostFrontmatter.

    Critical: 'date' not 'published_date'; 'draft' not 'is_draft'.
    """
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    fields = {f["name"] for f in parsed["collections"][0]["fields"]}

    # Must use 'date' — the actual frontmatter key (PostFrontmatter aliases it)
    assert "date" in fields, "'date' must be used, not 'published_date'"
    assert "published_date" not in fields

    # Must use 'draft' — the actual frontmatter key (Post model stores as is_draft)
    assert "draft" in fields, "'draft' must be used, not 'is_draft'"
    assert "is_draft" not in fields

    # Other required fields
    assert "title" in fields
    assert "slug" in fields
    assert "summary" in fields
    assert "cover_image" in fields
    assert "tags" in fields
    assert "body" in fields

    # Geo fields added in Phase 3 (maps_gis.md) — must match PostFrontmatter keys.
    assert "route" in fields
    assert "points_of_interest" in fields


@pytest.mark.unit
def test_config_yml_draft_defaults_to_true():
    """New posts must default to draft=true so they never go live by accident."""
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    fields = parsed["collections"][0]["fields"]
    draft_field = next(f for f in fields if f["name"] == "draft")
    assert draft_field.get("default") is True


@pytest.mark.unit
async def test_editor_bare_redirect(mock_client):
    """GET /editor (no trailing slash) also redirects."""
    resp = await mock_client.get("/editor", follow_redirects=False)
    assert resp.status_code in (301, 302)


@pytest.mark.unit
async def test_editor_redirect(mock_client):
    """GET /editor/ redirects to /static/editor/index.html."""
    resp = await mock_client.get("/editor/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/static/editor/index.html"


@pytest.mark.unit
async def test_editor_redirect_followed(mock_client):
    """Following the redirect serves the Sveltia index page."""
    resp = await mock_client.get("/editor/", follow_redirects=True)
    assert resp.status_code == 200
    assert "sveltia-cms" in resp.text
