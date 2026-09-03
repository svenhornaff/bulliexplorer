"""Unit tests for app.services.post_blocks.build_body_blocks.

No DB needed — this service is framework-free and pure (body_markdown +
frontmatter-derived gallery/callout definitions in, an ordered block list
out).
"""

from __future__ import annotations

import pytest

from app.models.post_schema import (
    CalloutFrontmatter,
    GalleryFrontmatter,
    GalleryImageFrontmatter,
)
from app.services.post_blocks import build_body_blocks


@pytest.mark.unit
def test_no_markers_produces_single_prose_block():
    blocks = build_body_blocks("Just some *prose*, no markers at all.", [], [])
    assert len(blocks) == 1
    assert blocks[0]["type"] == "prose"
    assert "<em>prose</em>" in blocks[0]["html"]


@pytest.mark.unit
def test_empty_body_produces_no_blocks():
    assert build_body_blocks("", [], []) == []
    assert build_body_blocks("   \n  \n", [], []) == []


@pytest.mark.unit
def test_route_map_marker_produces_route_map_block_in_place():
    body = "Intro text.\n\n[[route-map]]\n\nOutro text."
    blocks = build_body_blocks(body, [], [])
    assert [b["type"] for b in blocks] == ["prose", "route-map", "prose"]
    assert "Intro text" in blocks[0]["html"]
    assert "Outro text" in blocks[2]["html"]


@pytest.mark.unit
def test_gallery_marker_resolves_images_from_frontmatter():
    gallery = GalleryFrontmatter(
        id="coffee-stop",
        images=[
            GalleryImageFrontmatter(src="/static/uploads/a.jpg", alt="A rider at a cafe"),
            GalleryImageFrontmatter(src="/static/uploads/b.jpg", alt="Espresso cup", caption="The good stuff"),
        ],
    )
    body = "Before.\n\n[[gallery:coffee-stop]]\n\nAfter."
    blocks = build_body_blocks(body, [gallery], [])
    assert [b["type"] for b in blocks] == ["prose", "gallery", "prose"]
    gallery_block = blocks[1]
    assert gallery_block["id"] == "coffee-stop"
    assert gallery_block["images"][0]["alt"] == "A rider at a cafe"
    assert gallery_block["images"][1]["caption"] == "The good stuff"


@pytest.mark.unit
def test_callout_marker_resolves_content_from_frontmatter():
    callout = CalloutFrontmatter(id="tip-1", variant="warning", title="Watch out", body="Loose gravel on the descent.")
    body = "[[callout:tip-1]]"
    blocks = build_body_blocks(body, [], [callout])
    assert blocks == [
        {
            "type": "callout",
            "id": "tip-1",
            "variant": "warning",
            "title": "Watch out",
            "body": "Loose gravel on the descent.",
        }
    ]


@pytest.mark.unit
def test_callout_defaults_variant_to_tip_and_title_to_none():
    callout = CalloutFrontmatter(id="tip-1", body="Just a note.")
    blocks = build_body_blocks("[[callout:tip-1]]", [], [callout])
    assert blocks[0]["variant"] == "tip"
    assert blocks[0]["title"] is None


@pytest.mark.unit
def test_unknown_gallery_id_is_skipped_not_raised(caplog):
    body = "Text.\n\n[[gallery:does-not-exist]]\n\nMore text."
    blocks = build_body_blocks(body, [], [])
    # The unknown-marker gap produces no gallery block, but surrounding
    # prose on either side still renders — one bad marker never aborts
    # the whole body.
    assert [b["type"] for b in blocks] == ["prose", "prose"]
    assert "Unknown gallery id" in caplog.text


@pytest.mark.unit
def test_unknown_callout_id_is_skipped_not_raised(caplog):
    blocks = build_body_blocks("[[callout:missing]]", [], [])
    assert blocks == []
    assert "Unknown callout id" in caplog.text


@pytest.mark.unit
def test_marker_must_be_on_its_own_line():
    """A marker embedded mid-sentence is not a marker — it's just text."""
    body = "See the map here: [[route-map]] for details."
    blocks = build_body_blocks(body, [], [])
    assert len(blocks) == 1
    assert blocks[0]["type"] == "prose"
    assert "[[route-map]]" in blocks[0]["html"]


@pytest.mark.unit
def test_multiple_markers_in_order():
    gallery = GalleryFrontmatter(id="g1", images=[GalleryImageFrontmatter(src="/a.jpg", alt="a")])
    callout = CalloutFrontmatter(id="c1", body="note")
    body = "\n".join(
        [
            "Start.",
            "",
            "[[gallery:g1]]",
            "",
            "Middle.",
            "",
            "[[callout:c1]]",
            "",
            "[[route-map]]",
            "",
            "End.",
        ]
    )
    blocks = build_body_blocks(body, [gallery], [callout])
    assert [b["type"] for b in blocks] == [
        "prose",
        "gallery",
        "prose",
        "callout",
        "route-map",
        "prose",
    ]
