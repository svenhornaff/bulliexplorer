"""Smoke tests for Phase 3 template port.

Verifies that both the home page and post page:
- Return HTTP 200
- Contain the expected Clean Blog structural elements
- Preserve required content (title, nav brand, footer copyright)
- The post preview route renders the placeholder post correctly

No DB required — the home route uses an empty posts list and the post
preview route uses a hardcoded placeholder object.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
async def test_home_returns_200(client):
    resp = await client.get("/")
    assert resp.status_code == 200


@pytest.mark.unit
async def test_home_contains_site_name_in_nav(client):
    resp = await client.get("/")
    assert "BulliExplorer" in resp.text


@pytest.mark.unit
async def test_home_has_bootstrap_navbar(client):
    """Clean Blog nav structure is present."""
    resp = await client.get("/")
    assert 'id="mainNav"' in resp.text
    assert "navbar-brand" in resp.text


@pytest.mark.unit
async def test_home_has_masthead_header(client):
    """The hero/masthead header block renders."""
    resp = await client.get("/")
    assert "masthead" in resp.text
    assert "site-heading" in resp.text


@pytest.mark.unit
async def test_home_empty_state_message(client):
    """With no posts the empty-state text is shown."""
    resp = await client.get("/")
    assert "No posts yet" in resp.text


@pytest.mark.unit
async def test_home_links_clean_blog_css(client):
    resp = await client.get("/")
    assert "clean-blog.css" in resp.text


@pytest.mark.unit
async def test_home_links_clean_blog_js(client):
    resp = await client.get("/")
    assert "clean-blog.js" in resp.text


@pytest.mark.unit
async def test_home_has_footer_copyright(client):
    resp = await client.get("/")
    assert "BulliExplorer" in resp.text
    # Copyright symbol present (HTML entity or literal)
    assert ("&copy;" in resp.text) or ("©" in resp.text)


@pytest.mark.unit
async def test_post_preview_returns_200(client):
    resp = await client.get("/post-preview")
    assert resp.status_code == 200


@pytest.mark.unit
async def test_post_preview_has_masthead(client):
    """Post page masthead (post-heading) is present."""
    resp = await client.get("/post-preview")
    assert "post-heading" in resp.text
    assert "masthead" in resp.text


@pytest.mark.unit
async def test_post_preview_shows_title(client):
    resp = await client.get("/post-preview")
    assert "A Gravel Day in the Black Forest" in resp.text


@pytest.mark.unit
async def test_post_preview_shows_summary_as_subheading(client):
    resp = await client.get("/post-preview")
    assert "subheading" in resp.text
    assert "Single-track" in resp.text


@pytest.mark.unit
async def test_post_preview_shows_author_byline(client):
    resp = await client.get("/post-preview")
    assert "Sven" in resp.text


@pytest.mark.unit
async def test_post_preview_renders_body_html(client):
    resp = await client.get("/post-preview")
    assert "placeholder body content" in resp.text


@pytest.mark.unit
async def test_post_preview_shows_tags(client):
    resp = await client.get("/post-preview")
    assert "gravel" in resp.text
    assert "adventure" in resp.text


@pytest.mark.unit
async def test_post_preview_has_back_link(client):
    resp = await client.get("/post-preview")
    assert "Back to all posts" in resp.text


@pytest.mark.unit
async def test_post_preview_links_clean_blog_css(client):
    resp = await client.get("/post-preview")
    assert "clean-blog.css" in resp.text
