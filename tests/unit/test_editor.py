"""Smoke tests for the Phase 2 editor static files.

Verifies:
- static/editor/index.html exists and loads the Sveltia CDN bundle.
- static/editor/config.yml exists and contains the required field names
  matching PostFrontmatter's actual YAML keys.
- No route in app/routes/ shadows /editor/ or /static/editor/.
"""

from __future__ import annotations

import re
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
R2_CORS_JSON = BASE_DIR / "docs" / "dev" / "r2-cors.json"


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
def test_index_html_cms_config_url_has_explicit_type():
    """Regression guard: <link rel="cms-config-url"> must carry an explicit
    type="application/yaml" attribute.

    Root cause of a real bug (see commit 74fcfb7): Sveltia's fetchCmsConfig()
    reads `type` directly off the HTMLLinkElement, not the HTTP response's
    Content-Type header. A <link> with no type attribute reads back as ""
    (empty string, not undefined) in the DOM — fetchFile()'s
    `type = 'application/yaml'` default parameter only fires for undefined,
    so the empty string silently passes through and
    SUPPORTED_TYPES.includes("") is false. This fails before the config file
    is ever fetched — unrelated to its actual content, our dynamic
    /editor/config.yml route, or CORS, all of which can look completely
    correct while this one missing attribute breaks the editor outright.
    """
    content = INDEX_HTML.read_text()
    match = re.search(r'<link\s+rel="cms-config-url"[^>]*>', content)
    assert match, "index.html must have a cms-config-url <link> tag"
    assert 'type="application/yaml"' in match.group(0)


@pytest.mark.unit
def test_index_html_is_valid_html():
    content = INDEX_HTML.read_text()
    assert "<!doctype html>" in content.lower()
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
@pytest.mark.unit
def test_config_yml_backend_github():
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    backend = parsed["backend"]
    assert backend["name"] == "github"
    assert backend["repo"] == "svenhornaff/bulliexplorer"
    assert backend["branch"] == "develop"
    # PAT auth via the "Sign In with Token" button — no base_url, and
    # auth_type must be *absent* (not "token"). Sveltia's runtime validation
    # rejects any non-empty auth_type: "The backend.auth_type option must
    # be an empty string." This was the root cause of a real bug (see
    # commit bcaa640) — this assertion exists specifically to stop a future
    # change from reintroducing it.
    assert "base_url" not in backend
    assert "auth_type" not in backend


@pytest.mark.unit
async def test_editor_config_route_r2_unset(monkeypatch):
    """Phase 1 (media_storage_r2.md): with no R2_* env vars set, the dynamic
    /editor/config.yml route serves the static template byte-for-byte — no
    media_libraries block, Sveltia falls back to git-based uploads."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("RESYNC_TOKEN", "test-resync-token")
    # setenv (not delenv) — pydantic-settings only lets an env var beat
    # the .env file's value when the env var is actually *set*; deleting it
    # from os.environ falls through to whatever a real .env has on disk.
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "")
    monkeypatch.setenv("R2_ACCOUNT_ID", "")
    monkeypatch.setenv("R2_PUBLIC_URL", "")

    from app.core.config import get_settings

    get_settings.cache_clear()
    application = create_app()
    application.dependency_overrides[get_db_session] = _empty_db
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/editor/config.yml")
    get_settings.cache_clear()

    assert resp.status_code == 200
    assert resp.text == CONFIG_YML.read_text()
    parsed = yaml.safe_load(resp.text)
    assert "media_libraries" not in parsed, "no media_libraries key should be present when R2 is unconfigured"


@pytest.mark.unit
async def test_editor_config_route_r2_set(monkeypatch):
    """With R2_* env vars set, the media_libraries block is injected at
    request time — the Access Key ID/Account ID never touch a git-tracked
    file, only Settings sourced from .env on the server."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("RESYNC_TOKEN", "test-resync-token")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "a" * 64)
    monkeypatch.setenv("R2_ACCOUNT_ID", "d3ed4c9bdbdb6a47372d99e1f55e8013")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev")

    from app.core.config import get_settings

    get_settings.cache_clear()
    application = create_app()
    application.dependency_overrides[get_db_session] = _empty_db
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/editor/config.yml")
    get_settings.cache_clear()

    parsed = yaml.safe_load(resp.text)
    r2 = parsed["media_libraries"]["cloudflare_r2"]
    assert r2["bucket"] == "bulliexplorer"
    assert r2["prefix"] == "media/"
    assert r2["access_key_id"] == "a" * 64
    assert re.fullmatch(r"[0-9a-f]{32}", r2["account_id"])
    assert r2["public_url"].startswith("https://pub-")


@pytest.mark.unit
def test_config_yml_no_git_media_folder():
    """media_folder/public_folder must stay absent (media_storage_r2.md
    Phase 1-2) — R2 is the only media library, deliberately, so there's no
    git-vs-R2 picker and no way to accidentally upload back into git.
    Sveltia only requires media_folder when there's no cloud media library
    configured (its own parser/media.js), which is why this is safe.
    """
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    assert "media_folder" not in parsed
    assert "public_folder" not in parsed


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

    # Body-block fields added in Phase 4 (ui_ux_refresh.md §5.3) — must
    # match PostFrontmatter keys.
    assert "galleries" in fields
    assert "callouts" in fields


@pytest.mark.unit
def test_config_yml_gallery_image_has_mandatory_alt_field():
    """Alt text is enforced at the Pydantic level (GalleryImageFrontmatter);
    the CMS field must not be marked required: false, or authors could skip
    it there without ever hitting that validation.
    """
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    fields = parsed["collections"][0]["fields"]
    galleries_field = next(f for f in fields if f["name"] == "galleries")
    images_field = next(f for f in galleries_field["fields"] if f["name"] == "images")
    alt_field = next(f for f in images_field["fields"] if f["name"] == "alt")
    assert alt_field.get("required") is not False


@pytest.mark.unit
def test_config_yml_gallery_images_have_no_field_level_git_folder():
    """Gallery images used to have their own field-level media_folder/
    public_folder pointing at a git-backed subfolder — independent of the
    top-level default, so it survived even after that was removed. Removed
    in the same pass (media_storage_r2.md) so R2 is genuinely the only
    option for every upload path, not just the top-level default.
    """
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    fields = parsed["collections"][0]["fields"]
    galleries_field = next(f for f in fields if f["name"] == "galleries")
    images_field = next(f for f in galleries_field["fields"] if f["name"] == "images")
    src_field = next(f for f in images_field["fields"] if f["name"] == "src")
    assert "media_folder" not in src_field
    assert "public_folder" not in src_field


@pytest.mark.unit
def test_config_yml_callout_variant_defaults_to_tip():
    parsed = yaml.safe_load(CONFIG_YML.read_text())
    fields = parsed["collections"][0]["fields"]
    callouts_field = next(f for f in fields if f["name"] == "callouts")
    variant_field = next(f for f in callouts_field["fields"] if f["name"] == "variant")
    assert variant_field.get("default") == "tip"


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
