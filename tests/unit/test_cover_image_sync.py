"""Unit tests for app/services/cover_image_sync.py
(docs/dev/fix_lcp_image_and_static_cache.md Finding 1).

No real R2/network involved — httpx uses a mock transport (same
convention as tests/unit/test_geo_sync.py's GPX-fetch tests) and boto3
is a plain MagicMock (AGENTS.md: mock boto3/S3 calls, don't hit real R2
in tests).
"""

from __future__ import annotations

import io
import logging
from unittest.mock import MagicMock

import httpx
import pytest
from PIL import Image

from app.services.cover_image_sync import resolve_cover_image

_R2_PUBLIC_URL = "https://pub-example.r2.dev"


def _make_jpeg_bytes(width: int = 2000, height: int = 1000) -> bytes:
    img = Image.new("RGB", (width, height), color=(50, 80, 120))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class _ImageTransport(httpx.AsyncBaseTransport):
    """Mock httpx transport that returns fixed image bytes."""

    def __init__(self, payload: bytes, status_code: int = 200) -> None:
        self._payload = payload
        self._status_code = status_code
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code, content=self._payload)


def _mock_s3_client() -> MagicMock:
    return MagicMock()


@pytest.mark.unit
async def test_resolve_cover_image_no_source_url_clears_everything():
    """A post whose cover_image was removed from frontmatter entirely —
    every field must be cleared, not left pointing at a now-orphaned
    processed image.
    """
    result = await resolve_cover_image(
        slug="test-post",
        new_source_url=None,
        existing_source_url="https://pub-example.r2.dev/media/old.jpg",
        existing_served_url="https://pub-example.r2.dev/media/processed/old.webp",
        existing_width=1600,
        existing_height=900,
        r2_public_url=_R2_PUBLIC_URL,
        s3_client=_mock_s3_client(),
        s3_bucket="bulliexplorer",
    )
    assert result.served_url is None
    assert result.source_url is None
    assert result.width is None
    assert result.height is None


@pytest.mark.unit
async def test_resolve_cover_image_unchanged_skips_fetch_and_upload():
    """The idempotency case the doc's own resync-freshness precedent
    established: an unchanged cover_image on a re-sync must not fetch,
    process, or upload anything at all.
    """
    transport = _ImageTransport(_make_jpeg_bytes())
    s3_client = _mock_s3_client()

    async with httpx.AsyncClient(transport=transport) as client:
        result = await resolve_cover_image(
            slug="test-post",
            new_source_url="https://pub-example.r2.dev/media/cover.jpg",
            existing_source_url="https://pub-example.r2.dev/media/cover.jpg",
            existing_served_url="https://pub-example.r2.dev/media/processed/cover-abc123.webp",
            existing_width=1600,
            existing_height=900,
            r2_public_url=_R2_PUBLIC_URL,
            s3_client=s3_client,
            s3_bucket="bulliexplorer",
            http_client=client,
        )

    assert result.served_url == "https://pub-example.r2.dev/media/processed/cover-abc123.webp"
    assert result.width == 1600
    assert result.height == 900
    assert len(transport.requests) == 0, "an unchanged cover image must never be re-fetched"
    s3_client.put_object.assert_not_called()


@pytest.mark.unit
async def test_resolve_cover_image_new_post_fetches_processes_and_uploads():
    """A brand-new post with a cover_image: fetched, resized/converted,
    uploaded to R2 under a deterministic key, served URL built from
    r2_public_url.
    """
    original = _make_jpeg_bytes(2400, 1200)
    transport = _ImageTransport(original)
    s3_client = _mock_s3_client()

    async with httpx.AsyncClient(transport=transport) as client:
        result = await resolve_cover_image(
            slug="new-post",
            new_source_url="https://pub-example.r2.dev/media/cover.jpg",
            existing_source_url=None,
            existing_served_url=None,
            existing_width=None,
            existing_height=None,
            r2_public_url=_R2_PUBLIC_URL,
            s3_client=s3_client,
            s3_bucket="bulliexplorer",
            http_client=client,
        )

    assert len(transport.requests) == 1
    s3_client.put_object.assert_called_once()
    call_kwargs = s3_client.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "bulliexplorer"
    assert call_kwargs["Key"].startswith("media/processed/new-post-")
    assert call_kwargs["Key"].endswith(".webp")
    assert call_kwargs["ContentType"] == "image/webp"
    assert result.served_url == f"{_R2_PUBLIC_URL}/{call_kwargs['Key']}"
    assert result.source_url == "https://pub-example.r2.dev/media/cover.jpg"
    assert result.width == 1800  # MAX_COVER_WIDTH
    assert result.height == 900


@pytest.mark.unit
async def test_resolve_cover_image_changed_url_reprocesses():
    """A post whose cover_image frontmatter value changed since the last
    sync must be re-fetched/re-processed/re-uploaded, not skipped —
    idempotency only applies to a genuinely unchanged value.
    """
    transport = _ImageTransport(_make_jpeg_bytes())
    s3_client = _mock_s3_client()

    async with httpx.AsyncClient(transport=transport) as client:
        result = await resolve_cover_image(
            slug="test-post",
            new_source_url="https://pub-example.r2.dev/media/new-cover.jpg",
            existing_source_url="https://pub-example.r2.dev/media/old-cover.jpg",
            existing_served_url="https://pub-example.r2.dev/media/processed/old-cover-xyz.webp",
            existing_width=1600,
            existing_height=900,
            r2_public_url=_R2_PUBLIC_URL,
            s3_client=s3_client,
            s3_bucket="bulliexplorer",
            http_client=client,
        )

    assert len(transport.requests) == 1
    s3_client.put_object.assert_called_once()
    assert result.source_url == "https://pub-example.r2.dev/media/new-cover.jpg"
    assert result.served_url != "https://pub-example.r2.dev/media/processed/old-cover-xyz.webp"


@pytest.mark.unit
async def test_resolve_cover_image_disallowed_host_falls_back_unprocessed(caplog):
    """A cover_image URL on a host that doesn't match r2_public_url is
    never fetched — same SSRF posture as gpx_file
    (docs/dev/security_review_owasp.md Phase 1) — and the reader still
    gets *something* (the original URL unprocessed), not a missing image.
    """
    transport = _ImageTransport(_make_jpeg_bytes())
    s3_client = _mock_s3_client()

    async with httpx.AsyncClient(transport=transport) as client:
        with caplog.at_level(logging.WARNING):
            result = await resolve_cover_image(
                slug="test-post",
                new_source_url="https://evil.example.com/cover.jpg",
                existing_source_url=None,
                existing_served_url=None,
                existing_width=None,
                existing_height=None,
                r2_public_url=_R2_PUBLIC_URL,
                s3_client=s3_client,
                s3_bucket="bulliexplorer",
                http_client=client,
            )

    assert len(transport.requests) == 0, "a disallowed host must never be fetched"
    s3_client.put_object.assert_not_called()
    assert result.served_url == "https://evil.example.com/cover.jpg"
    assert result.width is None
    assert any("not allowed" in record.message for record in caplog.records)


@pytest.mark.unit
async def test_resolve_cover_image_missing_s3_client_falls_back_unprocessed():
    """No R2 write credentials configured (s3_client=None, the default)
    — degrade to serving the original URL unprocessed, the same
    graceful-degradation posture as every other missing-credential path
    in this codebase, not a crash.
    """
    transport = _ImageTransport(_make_jpeg_bytes())

    async with httpx.AsyncClient(transport=transport) as client:
        result = await resolve_cover_image(
            slug="test-post",
            new_source_url="https://pub-example.r2.dev/media/cover.jpg",
            existing_source_url=None,
            existing_served_url=None,
            existing_width=None,
            existing_height=None,
            r2_public_url=_R2_PUBLIC_URL,
            s3_client=None,
            s3_bucket="bulliexplorer",
            http_client=client,
        )

    assert len(transport.requests) == 0, "must not even attempt a fetch when R2 write credentials are unconfigured"
    assert result.served_url == "https://pub-example.r2.dev/media/cover.jpg"


@pytest.mark.unit
async def test_resolve_cover_image_fetch_failure_falls_back_unprocessed():
    """A network error fetching the original degrades to the original
    URL, unprocessed — matches _parse_gpx's own failure posture.
    """

    class _ConnectErrorTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

    s3_client = _mock_s3_client()
    async with httpx.AsyncClient(transport=_ConnectErrorTransport()) as client:
        result = await resolve_cover_image(
            slug="test-post",
            new_source_url="https://pub-example.r2.dev/media/cover.jpg",
            existing_source_url=None,
            existing_served_url=None,
            existing_width=None,
            existing_height=None,
            r2_public_url=_R2_PUBLIC_URL,
            s3_client=s3_client,
            s3_bucket="bulliexplorer",
            http_client=client,
        )

    assert result.served_url == "https://pub-example.r2.dev/media/cover.jpg"
    assert result.width is None
    s3_client.put_object.assert_not_called()


@pytest.mark.unit
async def test_resolve_cover_image_corrupt_image_falls_back_unprocessed():
    """A fetched-but-undecodable image (a bad upload) degrades to the
    original URL, not a crash or a missing cover image.
    """
    transport = _ImageTransport(b"not a real image")
    s3_client = _mock_s3_client()

    async with httpx.AsyncClient(transport=transport) as client:
        result = await resolve_cover_image(
            slug="test-post",
            new_source_url="https://pub-example.r2.dev/media/cover.jpg",
            existing_source_url=None,
            existing_served_url=None,
            existing_width=None,
            existing_height=None,
            r2_public_url=_R2_PUBLIC_URL,
            s3_client=s3_client,
            s3_bucket="bulliexplorer",
            http_client=client,
        )

    assert result.served_url == "https://pub-example.r2.dev/media/cover.jpg"
    s3_client.put_object.assert_not_called()


@pytest.mark.unit
async def test_resolve_cover_image_upload_failure_falls_back_unprocessed():
    """A boto3 upload error (bucket unreachable, permission denied, ...)
    degrades to the original URL rather than propagating — a broken R2
    connection must not take down post syncing entirely.
    """
    transport = _ImageTransport(_make_jpeg_bytes())
    s3_client = _mock_s3_client()
    s3_client.put_object.side_effect = RuntimeError("simulated R2 failure")

    async with httpx.AsyncClient(transport=transport) as client:
        result = await resolve_cover_image(
            slug="test-post",
            new_source_url="https://pub-example.r2.dev/media/cover.jpg",
            existing_source_url=None,
            existing_served_url=None,
            existing_width=None,
            existing_height=None,
            r2_public_url=_R2_PUBLIC_URL,
            s3_client=s3_client,
            s3_bucket="bulliexplorer",
            http_client=client,
        )

    assert result.served_url == "https://pub-example.r2.dev/media/cover.jpg"
