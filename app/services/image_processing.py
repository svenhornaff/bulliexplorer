"""Pure image-processing logic for post cover images.

docs/dev/fix_lcp_image_and_static_cache.md Finding 1: a real PageSpeed
Insights run found LCP 15.1s against an otherwise excellent metric
profile, with "Improve image delivery" flagging 2,531 KiB of potential
savings on the hero image — cover_image was a plain frontmatter URL
served exactly as uploaded (whatever a phone/camera produced), with no
resizing or format conversion anywhere in the pipeline.

Framework-free per AGENTS.md — no FastAPI/Jinja2 imports here, no R2/
network calls either (that orchestration lives in
app.services.cover_image_sync). Just: given raw image bytes, produce a
resized WebP version. Genuinely unit-testable without a browser or a
live PageSpeed run — the whole point of keeping this function pure.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

# Large enough for a genuine full-width desktop hero image, wasteful for
# a phone screen at full camera resolution (the doc's own framing) — a
# typical modern phone photo is 3000-4000px wide; this caps it to
# roughly what a hero image actually needs to render sharp at any
# realistic viewport.
MAX_COVER_WIDTH = 1800

# WebP quality — high enough that visual loss is not perceptible for a
# photographic hero image, still a large size reduction from an
# unprocessed camera JPEG.
_WEBP_QUALITY = 82


class ImageProcessingError(Exception):
    """Raised when the input bytes are not a decodable image.

    Callers (cover_image_sync.py) catch this and fall back to serving
    the original, unprocessed URL rather than losing the cover image
    entirely — a bad/corrupt upload degrades gracefully, the same
    posture as every other external-input path in this codebase (a
    malformed GPX file, an unreachable Overpass host).
    """


def process_cover_image(image_bytes: bytes, *, max_width: int = MAX_COVER_WIDTH) -> tuple[bytes, int, int]:
    """Resize (if needed) and convert an image to WebP.

    Parameters
    ----------
    image_bytes:
        Raw bytes of the original image, any Pillow-supported format
        (JPEG/PNG/WebP/HEIC-if-plugin-available/...).
    max_width:
        Upper bound on the output width in pixels. An input already
        narrower than this is only format-converted, never upscaled —
        resizing is a one-way size reduction, not a canvas-fit operation.

    Returns
    -------
    A ``(webp_bytes, width, height)`` tuple: the processed image's bytes
    and its final pixel dimensions (needed by the caller to store
    alongside the image for the page's ``<img width height>`` attributes
    — the doc's Finding 1 CLS improvement).

    Raises
    ------
    ImageProcessingError
        If ``image_bytes`` cannot be decoded as an image at all.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as original:
            original.load()  # force full decode now — Image.open() alone is lazy
            image = original
            if image.mode not in ("RGB", "RGBA"):
                # Flatten palette/CMYK/etc. modes to a mode WebP can encode
                # directly. RGBA is kept as-is (WebP supports alpha); a
                # photographic hero image is virtually always opaque
                # already, so this mostly normalises unusual source modes
                # (e.g. a PNG with a palette) without changing appearance.
                image = image.convert("RGBA" if "A" in image.mode else "RGB")

            if image.width > max_width:
                new_height = round(image.height * (max_width / image.width))
                image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="WEBP", quality=_WEBP_QUALITY)
            return buffer.getvalue(), image.width, image.height
    except UnidentifiedImageError as exc:
        raise ImageProcessingError(f"Could not decode image ({len(image_bytes)} bytes)") from exc
