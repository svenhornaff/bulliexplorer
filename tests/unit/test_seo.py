"""Unit tests for app/services/seo.py — docs/dev/seo_beyond_basics.md.

Pure-function tests, no DB and no FastAPI app needed — mirrors the
framework-free design of the module itself. Fake Post/Route objects
carry only the attributes each builder actually reads.
"""

from __future__ import annotations

import datetime
import xml.etree.ElementTree as ET

import pytest

from app.models.post import Post
from app.models.route import Route
from app.services.seo import (
    AI_TRAINING_CRAWLERS,
    build_blog_posting_jsonld,
    build_feed_xml,
    build_post_jsonld,
    build_sitemap_xml,
    build_trip_jsonld,
    robots_txt,
)

SITE_URL = "https://bulliexplorer.com"


def _make_post(
    slug: str = "test-post",
    title: str = "Test Post",
    summary: str | None = "A test summary.",
    cover_image: str | None = None,
    published_date: datetime.date = datetime.date(2026, 6, 1),
    updated_at: datetime.datetime = datetime.datetime(2026, 6, 2, 10, 30, tzinfo=datetime.UTC),
) -> Post:
    """Build a real (unpersisted) Post ORM instance for these tests —
    same pattern as test_geo_sync.py's plain ``Route(...)`` fixtures:
    no DB round-trip needed, and using the real model keeps these tests
    type-checked against the actual builder signatures instead of a
    hand-rolled duck-typed stand-in.
    """
    return Post(
        slug=slug,
        title=title,
        summary=summary,
        body_markdown="placeholder",
        cover_image=cover_image,
        published_date=published_date,
        updated_at=updated_at,
    )


def _make_route(name: str = "Test Route", description: str | None = "A nice loop.") -> Route:
    """Build a real (unpersisted) Route ORM instance — omits the
    non-nullable ``track`` column, which is fine for a plain Python
    object that's never flushed to the DB.
    """
    return Route(name=name, description=description)


# ---------------------------------------------------------------------------
# Phase 1 — robots.txt
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_robots_txt_disallows_every_training_crawler():
    """Every AI training crawler (docs/dev/seo_beyond_basics.md Phase 0's
    operator decision) gets an explicit Disallow: / block."""
    content = robots_txt(SITE_URL)
    for bot in AI_TRAINING_CRAWLERS:
        assert f"User-agent: {bot}\nDisallow: /" in content


@pytest.mark.unit
def test_robots_txt_no_typos_in_known_bot_names():
    """Regression guard: a misspelled user-agent silently does nothing
    (Phase 1's own "Done when" criterion) — pin the exact,
    doc-specified set of training crawlers.
    """
    assert AI_TRAINING_CRAWLERS == (
        "GPTBot",
        "ClaudeBot",
        "Google-Extended",
        "CCBot",
        "Applebot-Extended",
    )


@pytest.mark.unit
def test_robots_txt_allows_generic_user_agent():
    """A generic User-agent: * Allow: / block covers every crawler not
    explicitly blocked above — including search/citation crawlers
    (OAI-SearchBot, ChatGPT-User, Claude-SearchBot, PerplexityBot,
    Googlebot, Bingbot), which deliberately get no explicit rule of
    their own (Phase 1's scope).
    """
    content = robots_txt(SITE_URL)
    assert "User-agent: *\nAllow: /" in content
    for search_bot in ("OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "PerplexityBot", "Googlebot", "Bingbot"):
        assert search_bot not in content


@pytest.mark.unit
def test_robots_txt_includes_sitemap_directive():
    content = robots_txt(SITE_URL)
    assert "Sitemap: https://bulliexplorer.com/sitemap.xml" in content


@pytest.mark.unit
def test_robots_txt_training_crawlers_never_in_the_allow_list():
    """No training crawler must ever end up disallowed *and* allowed —
    the generic block must not accidentally also name a training bot.
    """
    content = robots_txt(SITE_URL)
    for bot in AI_TRAINING_CRAWLERS:
        assert f"User-agent: {bot}\nAllow: /" not in content


# ---------------------------------------------------------------------------
# Phase 2 — sitemap.xml
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sitemap_includes_static_pages():
    xml_str = build_sitemap_xml([], SITE_URL)
    root = ET.fromstring(xml_str)  # noqa: S314 — trusted, self-produced XML in a test
    locs = [el.text for el in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert f"{SITE_URL}/" in locs
    assert f"{SITE_URL}/posts/" in locs


@pytest.mark.unit
def test_sitemap_includes_every_post():
    posts = [_make_post(slug="post-one"), _make_post(slug="post-two")]
    xml_str = build_sitemap_xml(posts, SITE_URL)
    root = ET.fromstring(xml_str)  # noqa: S314
    locs = [el.text for el in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert f"{SITE_URL}/posts/post-one" in locs
    assert f"{SITE_URL}/posts/post-two" in locs


@pytest.mark.unit
def test_sitemap_lastmod_comes_from_updated_at_not_published_date():
    """lastmod must reflect when the row was actually last synced, not
    the original publish date — a content-only resync bumps updated_at
    without a new published_date.
    """
    post = _make_post(
        published_date=datetime.date(2026, 1, 1),
        updated_at=datetime.datetime(2026, 6, 15, 9, 0, tzinfo=datetime.UTC),
    )
    xml_str = build_sitemap_xml([post], SITE_URL)
    assert post.updated_at.isoformat() in xml_str
    assert "2026-01-01" not in xml_str


@pytest.mark.unit
def test_sitemap_valid_with_zero_posts():
    """An empty posts list still produces valid, parseable XML."""
    xml_str = build_sitemap_xml([], SITE_URL)
    root = ET.fromstring(xml_str)  # noqa: S314
    assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"


# ---------------------------------------------------------------------------
# Phase 2 — feed.xml (RSS 2.0)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_feed_valid_with_zero_posts():
    xml_str = build_feed_xml([], SITE_URL)
    root = ET.fromstring(xml_str)  # noqa: S314
    assert root.tag == "rss"
    channel = root.find("channel")
    assert channel is not None
    assert channel.find("item") is None


@pytest.mark.unit
def test_feed_item_has_title_link_guid_pubdate_description():
    post = _make_post(slug="dream-of-north", title="Dream of North", summary="71°10′ N and beyond.")
    xml_str = build_feed_xml([post], SITE_URL)
    root = ET.fromstring(xml_str)  # noqa: S314
    item = root.find("./channel/item")
    assert item is not None
    assert item.findtext("title") == "Dream of North"
    assert item.findtext("link") == f"{SITE_URL}/posts/dream-of-north"
    guid = item.find("guid")
    assert guid is not None
    assert guid.text == f"{SITE_URL}/posts/dream-of-north"
    assert guid.get("isPermaLink") == "true"
    assert item.findtext("description") == "71°10′ N and beyond."
    assert item.findtext("pubDate") is not None


@pytest.mark.unit
def test_feed_item_description_falls_back_to_empty_string_without_summary():
    post = _make_post(summary=None)
    xml_str = build_feed_xml([post], SITE_URL)
    root = ET.fromstring(xml_str)  # noqa: S314
    description_el = root.find("./channel/item/description")
    assert description_el is not None
    assert description_el.text in (None, "")


@pytest.mark.unit
def test_feed_escapes_special_characters_in_title():
    """A post title containing XML-special characters must not break
    the feed's well-formedness — ElementTree escapes text content on
    serialization, this pins that it actually round-trips.
    """
    post = _make_post(title='Gravel & <Mud> "Adventures"')
    xml_str = build_feed_xml([post], SITE_URL)
    root = ET.fromstring(xml_str)  # noqa: S314 — this parse succeeding is the assertion
    assert root.findtext("./channel/item/title") == 'Gravel & <Mud> "Adventures"'


# ---------------------------------------------------------------------------
# Phase 3 — JSON-LD
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_blog_posting_has_required_fields():
    post = _make_post()
    node = build_blog_posting_jsonld(post, SITE_URL, "Sven Hornaff")
    assert node["@type"] == "BlogPosting"
    assert node["headline"] == post.title
    assert node["datePublished"] == post.published_date.isoformat()
    assert node["dateModified"] == post.updated_at.isoformat()
    assert node["author"] == {"@type": "Person", "name": "Sven Hornaff"}
    assert node["url"] == f"{SITE_URL}/posts/{post.slug}"


@pytest.mark.unit
def test_blog_posting_omits_image_when_no_cover_image():
    post = _make_post(cover_image=None)
    node = build_blog_posting_jsonld(post, SITE_URL, "Sven Hornaff")
    assert "image" not in node


@pytest.mark.unit
def test_blog_posting_includes_image_when_cover_image_present():
    post = _make_post(cover_image="https://example.com/cover.png")
    node = build_blog_posting_jsonld(post, SITE_URL, "Sven Hornaff")
    assert node["image"] == "https://example.com/cover.png"


@pytest.mark.unit
def test_trip_jsonld_fields():
    post = _make_post()
    route = _make_route(name="NC4200", description="A long ride north.")
    node = build_trip_jsonld(post, route, SITE_URL)
    assert node["@type"] == "Trip"
    assert node["name"] == "NC4200"
    assert node["description"] == "A long ride north."
    assert node["url"] == f"{SITE_URL}/posts/{post.slug}"


@pytest.mark.unit
def test_trip_jsonld_falls_back_to_post_summary_when_route_has_no_description():
    post = _make_post(summary="Post-level summary.")
    route = _make_route(description=None)
    node = build_trip_jsonld(post, route, SITE_URL)
    assert node["description"] == "Post-level summary."


@pytest.mark.unit
def test_post_jsonld_includes_trip_when_route_present():
    post = _make_post()
    route = _make_route()
    graph = build_post_jsonld(post, route, SITE_URL, "Sven Hornaff")
    assert graph["@context"] == "https://schema.org"
    types = [node["@type"] for node in graph["@graph"]]
    assert types == ["BlogPosting", "Trip"]


@pytest.mark.unit
def test_post_jsonld_omits_trip_when_route_is_none():
    """A post with no route (e.g. a photo-only post) must never get a
    fabricated Trip node claiming itinerary content it doesn't have.
    """
    post = _make_post()
    graph = build_post_jsonld(post, None, SITE_URL, "Sven Hornaff")
    types = [node["@type"] for node in graph["@graph"]]
    assert types == ["BlogPosting"]
