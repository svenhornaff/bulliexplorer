"""Cover image processing at sync time (docs/dev/fix_lcp_image_and_static_cache.md
Finding 1).

Fetches a post's ``cover_image`` frontmatter URL once, resizes/converts
it via :mod:`app.services.image_processing`, and uploads the result
back to R2 — the same "resolve once, at sync time" pattern already used
for GPX parsing and Nominatim/Overpass lookups, never done live on a
page request.

Framework-free per AGENTS.md — no FastAPI/Jinja2 imports here. R2
access reuses the same boto3 client pattern as ``scripts/backup_db.py``
(``s3_endpoint_url``/``s3_access_key``/``s3_secret_key``/``s3_bucket``
Settings — the write-capable credentials, distinct from
``r2_access_key_id`` which is the browser-facing, editor-only value in
``app/routes/internal.py``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.image_processing import ImageProcessingError, process_cover_image
from app.utils.log_factory import get_logger
from app.utils.url_safety import is_allowed_r2_host

logger = get_logger(__name__)

_PROCESSED_COVER_PREFIX = "media/processed/"


@dataclass(frozen=True)
class CoverImageResult:
    """Outcome of resolving a post's cover image for one sync run.

    ``served_url`` is what gets stored in ``Post.cover_image`` (what
    readers actually receive); ``source_url`` is the raw frontmatter
    value, stored separately purely so the *next* sync can tell whether
    it changed at all without re-fetching/re-processing/re-uploading
    every single run — the same idempotency discipline
    ``fix_amenity_resync_freshness.md`` established for a different
    resync path, applied here from the start rather than found as a
    regression later.
    """

    served_url: str | None
    source_url: str | None
    width: int | None
    height: int | None


def _processed_key(slug: str, source_url: str) -> str:
    """Deterministic R2 object key for a post's processed cover image.

    Keyed by slug *and* a short hash of the source URL (not just slug)
    so a changed cover_image value naturally gets a different key rather
    than silently overwriting a previous, unrelated image under the same
    path — a defensive detail, not something currently exercised by any
    real post (frontmatter is source-controlled, not concurrently
    edited), but cheap to get right from the start.
    """
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]
    return f"{_PROCESSED_COVER_PREFIX}{slug}-{digest}.webp"


async def resolve_cover_image(
    *,
    slug: str,
    new_source_url: str | None,
    existing_source_url: str | None,
    existing_served_url: str | None,
    existing_width: int | None,
    existing_height: int | None,
    r2_public_url: str,
    s3_client: Any,
    s3_bucket: str,
    http_client: httpx.AsyncClient | None = None,
) -> CoverImageResult:
    """Resolve what a post's cover image fields should be for this sync.

    Idempotent by design: if ``new_source_url`` is unchanged from
    ``existing_source_url`` *and* a served URL already exists, this
    returns the existing values untouched — no fetch, no R2 write, no
    network activity at all for the common case of re-syncing a post
    whose cover image hasn't changed (every other frontmatter field
    edit, a typo fix in the body, anything).

    Degrades gracefully on any failure (fetch error, corrupt image,
    unconfigured R2 credentials, upload error): falls back to serving
    ``new_source_url`` unprocessed rather than losing the cover image
    entirely. A slower, unoptimized hero image beats a missing one.

    Parameters
    ----------
    slug:
        The post's slug — used to build a deterministic R2 object key.
    new_source_url:
        This sync's ``PostFrontmatter.cover_image`` value (``None`` if
        the post has no cover image at all).
    existing_source_url, existing_served_url, existing_width, existing_height:
        The post row's current values, from *before* this sync — read
        by the caller before this function runs, since ``_upsert_post``
        doesn't otherwise need to look the row up first for a new post.
    r2_public_url:
        ``Settings.r2_public_url`` — both the SSRF allowlist for
        fetching ``new_source_url`` and the base for building the
        processed image's served URL.
    s3_client:
        A boto3 S3 client already configured for the R2 endpoint, or
        ``None`` if R2 write credentials aren't configured (degrades to
        serving the original URL unprocessed, same as any other
        failure).
    s3_bucket:
        The bucket to upload the processed image into.
    http_client:
        Optional ``httpx.AsyncClient`` to reuse; a default is created
        and closed internally when ``None`` (test injection point, same
        convention as ``geo_sync._fetch_gpx_over_http``).

    Returns
    -------
    CoverImageResult
    """
    if not new_source_url:
        # Cover image removed from frontmatter entirely — clear every
        # field rather than leaving a stale processed image referenced.
        return CoverImageResult(served_url=None, source_url=None, width=None, height=None)

    if new_source_url == existing_source_url and existing_served_url:
        logger.debug("Cover image unchanged for slug=%r — skipping fetch/process/upload", slug)
        return CoverImageResult(
            served_url=existing_served_url,
            source_url=existing_source_url,
            width=existing_width,
            height=existing_height,
        )

    fallback = CoverImageResult(served_url=new_source_url, source_url=new_source_url, width=None, height=None)

    if not is_allowed_r2_host(new_source_url, r2_public_url):
        logger.warning(
            "cover_image host not allowed for slug=%r: %s (allowed host: %s) — serving unprocessed",
            slug,
            new_source_url,
            r2_public_url or "<none configured>",
        )
        return fallback

    if s3_client is None:
        logger.info("R2 write credentials not configured — serving cover_image for slug=%r unprocessed", slug)
        return fallback

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    try:
        response = await client.get(new_source_url)
        response.raise_for_status()
        original_bytes = response.content
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch cover_image for slug=%r: %s — serving unprocessed", slug, exc)
        return fallback
    finally:
        if owns_client:
            await client.aclose()

    try:
        webp_bytes, width, height = process_cover_image(original_bytes)
    except ImageProcessingError as exc:
        logger.warning("Failed to process cover_image for slug=%r: %s — serving unprocessed", slug, exc)
        return fallback

    key = _processed_key(slug, new_source_url)
    try:
        s3_client.put_object(Bucket=s3_bucket, Key=key, Body=webp_bytes, ContentType="image/webp")
    except Exception as exc:  # noqa: BLE001 — boto3 raises its own broad ClientError hierarchy; any failure here must degrade, not propagate
        logger.warning("Failed to upload processed cover_image for slug=%r: %s — serving unprocessed", slug, exc)
        return fallback

    served_url = f"{r2_public_url.rstrip('/')}/{key}"
    logger.info(
        "Processed cover_image for slug=%r: %d -> %d bytes, %dx%d",
        slug,
        len(original_bytes),
        len(webp_bytes),
        width,
        height,
    )
    return CoverImageResult(served_url=served_url, source_url=new_source_url, width=width, height=height)
