"""SEO artifact builders — robots.txt, sitemap.xml, feed.xml, JSON-LD.

Framework-free per AGENTS.md: no FastAPI/Jinja2/sqladmin imports, and no
reach into ``app.core.config`` either — every function takes the values
it needs (``site_url``, ``author_name``) as plain arguments, so this
module stays trivially unit-testable in isolation and the caller (a
route module) stays the only place that knows about ``Settings``.

Implements docs/dev/seo_beyond_basics.md Phases 1-3. Deliberately does
NOT implement llms.txt, FAQPage, or HowTo schema — see that doc's
"Explicitly out of scope" section for why (llms.txt: ~10% adoption but
major AI crawlers empirically skip it; FAQPage/HowTo: deprecated by
Google as of 2026, not a stylistic omission).
"""

from __future__ import annotations

# bandit's B405 blacklists this import because ElementTree is unsafe for
# *parsing untrusted* XML (XXE etc.) — this module only ever *builds and
# serializes* XML from our own DB-sourced data via Element/SubElement/
# tostring, never parses external/untrusted input, so that risk doesn't
# apply here. Not worth a defusedxml dependency for a write-only use case
# (AGENTS.md: no new dependencies without a concrete need).
import xml.etree.ElementTree as ET  # nosec B405
from datetime import UTC, datetime, time
from email.utils import format_datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.post import Post
    from app.models.route import Route

# AI crawlers that train future models on crawled content, as distinct
# from a provider's separate real-time search/citation crawler (see the
# table in docs/dev/seo_beyond_basics.md's research summary). Operator
# decision (2026, see that doc's Phase 0): block training, allow
# citation — BulliExplorer's personal/non-commercial content should stay
# eligible to be cited when someone asks an AI assistant about a route,
# but not be folded into a future model's training set by default.
AI_TRAINING_CRAWLERS: tuple[str, ...] = (
    "GPTBot",
    "ClaudeBot",
    "Google-Extended",
    "CCBot",
    "Applebot-Extended",
)


def robots_txt(site_url: str) -> str:
    """Build robots.txt content per the training/search crawler split.

    Parameters
    ----------
    site_url:
        Canonical site origin, no trailing slash (e.g.
        ``https://bulliexplorer.com``), used to point crawlers at the
        sitemap.

    Returns
    -------
    str
        Complete robots.txt content, newline-terminated.
    """
    lines: list[str] = []
    for bot in AI_TRAINING_CRAWLERS:
        lines.append(f"User-agent: {bot}")
        lines.append("Disallow: /")
        lines.append("")
    # Search/citation crawlers (OAI-SearchBot, ChatGPT-User,
    # Claude-SearchBot, PerplexityBot, Googlebot, Bingbot, ...) get no
    # explicit rule here — deliberately, per docs/dev/
    # seo_beyond_basics.md Phase 1's scope: they fall through to the
    # generic allow-all block below, same as any conventional crawler.
    lines.append("User-agent: *")
    lines.append("Allow: /")
    lines.append("")
    lines.append(f"Sitemap: {site_url}/sitemap.xml")
    return "\n".join(lines) + "\n"


def _post_lastmod(post: Post) -> datetime:
    """Best-available "content last changed" timestamp for a post.

    ``updated_at`` (DB row's own onupdate timestamp) reflects the last
    sync that actually touched this row, which is a closer proxy for
    "content last changed" than ``published_date`` alone — a content-only
    resync (docs/dev/fix_amenity_resync_freshness.md's same distinction,
    applied here to posts rather than routes) bumps it even without a new
    publish date.
    """
    return post.updated_at


def build_sitemap_xml(posts: list[Post], site_url: str) -> str:
    """Build sitemap.xml for the homepage, post list, and every published post.

    Parameters
    ----------
    posts:
        Published posts only — callers must filter out drafts before
        calling this; this function does not re-check ``is_draft``.
    site_url:
        Canonical site origin, no trailing slash.

    Returns
    -------
    str
        A complete, standards-compliant sitemap.xml document.
    """
    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for path in ("/", "/posts/"):
        url_el = ET.SubElement(urlset, "url")
        ET.SubElement(url_el, "loc").text = f"{site_url}{path}"
    for post in posts:
        url_el = ET.SubElement(urlset, "url")
        ET.SubElement(url_el, "loc").text = f"{site_url}/posts/{post.slug}"
        ET.SubElement(url_el, "lastmod").text = _post_lastmod(post).isoformat()
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(urlset, encoding="unicode") + "\n"


def build_feed_xml(posts: list[Post], site_url: str) -> str:
    """Build an RSS 2.0 feed.xml for every published post.

    Each item's description is the post's ``summary`` only — not the
    full rendered body — matching this project's existing minimization
    posture (docs/dev/DATA_PROCESSING.md's spirit applied to what's
    republished elsewhere, not just what's collected) rather than
    handing out full-text content for scraping/republishing by default.

    Parameters
    ----------
    posts:
        Published posts only, in the order they should appear in the
        feed (typically newest first) — callers must filter out drafts
        and choose the order; this function does not re-sort.
    site_url:
        Canonical site origin, no trailing slash.

    Returns
    -------
    str
        A complete, standards-compliant RSS 2.0 document. An empty
        ``posts`` list still produces a valid feed with zero ``<item>``
        elements, not an error.
    """
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "BulliExplorer"
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = "Gravel rides, campsites and routes — one van, endless roads."
    now = datetime.now(UTC)
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(now)
    for post in posts:
        item = ET.SubElement(channel, "item")
        post_url = f"{site_url}/posts/{post.slug}"
        ET.SubElement(item, "title").text = post.title
        ET.SubElement(item, "link").text = post_url
        guid = ET.SubElement(item, "guid")
        guid.text = post_url
        guid.set("isPermaLink", "true")
        ET.SubElement(item, "description").text = post.summary or ""
        # published_date is a date, not a datetime — RFC 2822 pubDate
        # needs a time component; midnight UTC on the published date is
        # the least-wrong choice available (the actual publish *time*
        # of day was never captured).
        published_at = datetime.combine(post.published_date, time.min, tzinfo=UTC)
        ET.SubElement(item, "pubDate").text = format_datetime(published_at)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n"


def build_blog_posting_jsonld(post: Post, site_url: str, author_name: str) -> dict[str, Any]:
    """Build a schema.org ``BlogPosting`` JSON-LD node for one post.

    Parameters
    ----------
    post:
        The post to describe.
    site_url:
        Canonical site origin, no trailing slash.
    author_name:
        Display name for the ``author`` property.

    Returns
    -------
    dict
        A JSON-LD-serializable ``BlogPosting`` node.
    """
    post_url = f"{site_url}/posts/{post.slug}"
    node: dict[str, Any] = {
        "@type": "BlogPosting",
        "@id": f"{post_url}#blogposting",
        "headline": post.title,
        "url": post_url,
        "mainEntityOfPage": post_url,
        "datePublished": post.published_date.isoformat(),
        "dateModified": _post_lastmod(post).isoformat(),
        "author": {"@type": "Person", "name": author_name},
    }
    if post.summary:
        node["description"] = post.summary
    if post.cover_image:
        node["image"] = post.cover_image
    return node


def build_trip_jsonld(post: Post, route: Route, site_url: str) -> dict[str, Any]:
    """Build a schema.org ``Trip`` JSON-LD node for a post's route.

    ``Trip`` (rather than a generic ``Article``) is the better semantic
    fit for itinerary/journey content per schema.org's own definition —
    see docs/dev/seo_beyond_basics.md's research summary. Only called
    for posts that actually have a ``Route``; never fabricates a Trip
    node for a post without one.

    Parameters
    ----------
    post:
        The post the route belongs to (used for the canonical URL).
    route:
        The route to describe.
    site_url:
        Canonical site origin, no trailing slash.

    Returns
    -------
    dict
        A JSON-LD-serializable ``Trip`` node.
    """
    post_url = f"{site_url}/posts/{post.slug}"
    node: dict[str, Any] = {
        "@type": "Trip",
        "@id": f"{post_url}#trip",
        "name": route.name,
        "url": post_url,
    }
    description = route.description or post.summary
    if description:
        node["description"] = description
    return node


def build_post_jsonld(post: Post, route: Route | None, site_url: str, author_name: str) -> dict[str, Any]:
    """Build the full JSON-LD ``@graph`` for a post detail page.

    Always includes a ``BlogPosting`` node. Adds a ``Trip`` node only
    when ``route`` is not ``None`` — a photo-only post with no GPX never
    gets a fabricated Trip claiming itinerary content it doesn't have.

    Parameters
    ----------
    post:
        The post to describe.
    route:
        The post's route, or ``None`` if it has no route.
    site_url:
        Canonical site origin, no trailing slash.
    author_name:
        Display name for the ``author`` property.

    Returns
    -------
    dict
        A single JSON-LD document with ``@context`` and an ``@graph``
        array containing one or two nodes, ready for
        ``{{ jsonld | tojson }}`` inside a ``<script
        type="application/ld+json">`` tag.
    """
    graph: list[dict[str, Any]] = [build_blog_posting_jsonld(post, site_url, author_name)]
    if route is not None:
        graph.append(build_trip_jsonld(post, route, site_url))
    return {"@context": "https://schema.org", "@graph": graph}
