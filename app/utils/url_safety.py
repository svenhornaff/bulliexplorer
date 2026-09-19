"""Shared SSRF host-allowlist check for frontmatter-supplied URLs.

Originally added as ``geo_sync._is_allowed_gpx_host``
(docs/dev/security_review_owasp.md Phase 1) for ``RouteFrontmatter.
gpx_file``. Extracted here, unchanged in behaviour, when
docs/dev/fix_lcp_image_and_static_cache.md Finding 1 needed the
identical check for ``PostFrontmatter.cover_image`` — the same class of
risk (a plain string from Markdown frontmatter, fetched server-side
with no restriction would let whoever can write to ``content/posts/
*.md`` make the server fetch any URL: an internal Docker network
address, a cloud metadata endpoint, ``localhost`` on an unexpected
port), so it gets the identical fix rather than a second, subtly
different implementation.
"""

from __future__ import annotations

from urllib.parse import urlparse


def is_allowed_r2_host(url: str, r2_public_url: str) -> bool:
    """Whether ``url``'s host matches the configured R2 public URL's host.

    Parameters
    ----------
    url:
        A URL a post's frontmatter asked the server to fetch (a
        ``gpx_file`` or a ``cover_image`` value).
    r2_public_url:
        ``Settings.r2_public_url`` — the only allowed host is this
        value's own host.

    Returns
    -------
    bool
        ``True`` only when ``r2_public_url`` is non-empty, both URLs have
        a parseable host, and the two hosts match case-insensitively.
        **Fails closed**: an unconfigured ``r2_public_url`` (the
        ``Settings`` default) allows nothing, rather than trusting every
        host absent an explicit allowlist — the same "absence of a
        configured trust anchor means deny, not allow" posture
        ``AGENTS.md``'s "no working defaults for secrets" rule applies to
        credentials.
    """
    if not r2_public_url:
        return False
    allowed_host = urlparse(r2_public_url).hostname
    actual_host = urlparse(url).hostname
    if not allowed_host or not actual_host:
        return False
    return actual_host.lower() == allowed_host.lower()
