"""Unit tests for app/services/image_processing.py
(docs/dev/fix_lcp_image_and_static_cache.md Finding 1).

Pure image-processing logic, no mocking needed — a real Pillow-built
image in memory is genuinely testable without a browser or a live
PageSpeed run, exactly the reasoning the doc itself gives for scoping
this function's tests this way.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.image_processing import (
    MAX_COVER_WIDTH,
    ImageProcessingError,
    process_cover_image,
)


def _make_jpeg(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color=(120, 160, 90))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.mark.unit
def test_process_cover_image_resizes_wide_image_down_to_max_width():
    """A real phone-camera-shaped photo (wider than MAX_COVER_WIDTH) is
    resized down, preserving aspect ratio.
    """
    original = _make_jpeg(3000, 2000)
    webp_bytes, width, height = process_cover_image(original)

    assert width == MAX_COVER_WIDTH
    assert height == round(2000 * (MAX_COVER_WIDTH / 3000))
    assert len(webp_bytes) < len(original), "a resized+recompressed image must be smaller, not larger"


@pytest.mark.unit
def test_process_cover_image_never_upscales_a_narrower_image():
    """An image already narrower than MAX_COVER_WIDTH is only format-
    converted, never upscaled — resizing is a one-way size reduction,
    not a canvas-fit operation (the function's own docstring).
    """
    original = _make_jpeg(800, 600)
    _webp_bytes, width, height = process_cover_image(original)

    assert width == 800
    assert height == 600


@pytest.mark.unit
def test_process_cover_image_output_is_valid_webp():
    """Output bytes have the real WebP RIFF/WEBP container signature —
    checked directly, not inferred from the function not raising.
    """
    original = _make_jpeg(1000, 500)
    webp_bytes, _width, _height = process_cover_image(original)

    assert webp_bytes[:4] == b"RIFF"
    assert webp_bytes[8:12] == b"WEBP"


@pytest.mark.unit
def test_process_cover_image_handles_rgba_png():
    """A PNG with an alpha channel is preserved (WebP supports alpha),
    not silently flattened to black/white — a real, plausible input
    format, not just JPEG.
    """
    img = Image.new("RGBA", (500, 400), color=(10, 20, 30, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    original = buf.getvalue()

    webp_bytes, width, height = process_cover_image(original)
    assert width == 500
    assert height == 400
    with Image.open(io.BytesIO(webp_bytes)) as decoded:
        assert decoded.mode == "RGBA"


@pytest.mark.unit
def test_process_cover_image_raises_on_corrupt_input():
    """Genuinely undecodable bytes raise ImageProcessingError — the
    caller (cover_image_sync.py) is expected to catch this and fall back
    to serving the original URL unprocessed, not crash the sync.
    """
    with pytest.raises(ImageProcessingError):
        process_cover_image(b"not an image at all")


@pytest.mark.unit
def test_process_cover_image_respects_custom_max_width():
    original = _make_jpeg(2000, 1000)
    _webp_bytes, width, height = process_cover_image(original, max_width=600)
    assert width == 600
    assert height == 300
