"""Body-block splitting service (Phase 4, docs/dev/ui_ux_refresh.md §5.3).

Splits a post's raw Markdown body on inline marker lines —
``[[route-map]]``, ``[[gallery:<id>]]``, ``[[callout:<id>]]`` — each on its
own line, and renders the prose segments between markers to HTML via
``markdown-it-py``. The result is an ordered list of block dicts that
``post.html`` loops over and dispatches by ``type``.

A post with no markers at all degenerates to a single ``prose`` block. The
"post has route data but no explicit ``[[route-map]]`` marker" fallback—
mirroring the previous "always render body, then always append the
map" behaviour — is handled at render time in ``post.html``, not here (see
``build_body_blocks()``'s docstring for why), so existing posts need no
changes to keep rendering correctly.

Design rules (per AGENTS.md): framework-free — no FastAPI/Jinja2/sqladmin
imports here. Gallery/callout *content* comes from frontmatter
(``PostFrontmatter.galleries`` / ``.callouts``), resolved by marker id;
there is no separate DB table for galleries/callouts since they have no
existence independent of the post that defines them (unlike Route/POI,
which are already their own tables for other reasons — geo queries).
"""

from __future__ import annotations

import re
from typing import Any

from markdown_it import MarkdownIt

from app.models.post_schema import CalloutFrontmatter, GalleryFrontmatter
from app.utils.log_factory import get_logger

logger = get_logger(__name__)

# Matches a marker on its own line, e.g.:
#   [[route-map]]
#   [[gallery:coffee-stop]]
#   [[callout:tip-1]]
# Leading/trailing whitespace on the line is allowed; the id portion (after
# ``:``) is any non-``]`` text.
_MARKER_RE = re.compile(
    r"^[ \t]*\[\[(route-map|gallery:[^\]]+|callout:[^\]]+)\]\][ \t]*$",
    re.MULTILINE,
)

_md = MarkdownIt()


def build_body_blocks(
    body_markdown: str,
    galleries: list[GalleryFrontmatter],
    callouts: list[CalloutFrontmatter],
) -> list[dict[str, Any]]:
    """Build the ordered render-plan block list for a post body.

    Parameters
    ----------
    body_markdown:
        The post's raw Markdown body (frontmatter already stripped).
    galleries:
        Gallery blocks defined in this post's frontmatter, matched to
        ``[[gallery:<id>]]`` markers by ``id``.
    callouts:
        Callout blocks defined in this post's frontmatter, matched to
        ``[[callout:<id>]]`` markers by ``id``.

    Returns
    -------
    An ordered list of block dicts. Each has a ``type`` key of ``"prose"``,
    ``"route-map"``, ``"gallery"``, or ``"callout"``:

    - ``prose``: ``{"type": "prose", "html": <rendered markdown>}``
    - ``route-map``: ``{"type": "route-map"}`` — the template resolves the
      actual route/geojson data itself, unchanged from before this phase.
    - ``gallery``: ``{"type": "gallery", "id": ..., "images": [...]}`` —
      images carry ``src``/``alt``/``caption`` straight from frontmatter.
    - ``callout``: ``{"type": "callout", "id": ..., "variant": ...,
      "title": ..., "body": ...}``.

    An unknown marker id (references a gallery/callout not defined in this
    post's frontmatter) is logged and skipped — the surrounding prose is
    unaffected, matching the sync pipeline's "one bad post must not abort
    the sync" resilience rule scaled down to one bad marker.

    Deliberately does *not* know whether the post has a ``Route`` row —
    that's a presentation/geo concern, not a content-parsing one, and
    keeping it out keeps this service framework- and model-free. The
    "no explicit [[route-map]] marker but the post has a route" fallback
    is instead handled at render time in ``post.html``, so it also covers
    ``Post`` rows that never went through this function at all (e.g. a
    row inserted directly, or one that predates a migration backfill) —
    a sync-time-only fallback would silently miss those.
    """
    galleries_by_id = {g.id: g for g in galleries}
    callouts_by_id = {c.id: c for c in callouts}

    blocks: list[dict[str, Any]] = []

    pos = 0
    for match in _MARKER_RE.finditer(body_markdown):
        prose_segment = body_markdown[pos : match.start()].strip()
        if prose_segment:
            blocks.append({"type": "prose", "html": _md.render(prose_segment)})

        marker_body = match.group(1)
        if marker_body == "route-map":
            blocks.append({"type": "route-map"})
        elif marker_body.startswith("gallery:"):
            gallery_id = marker_body.removeprefix("gallery:")
            gallery = galleries_by_id.get(gallery_id)
            if gallery is None:
                logger.error("Unknown gallery id %r in marker — skipping", gallery_id)
            else:
                blocks.append(
                    {
                        "type": "gallery",
                        "id": gallery.id,
                        "images": [img.model_dump() for img in gallery.images],
                    }
                )
        elif marker_body.startswith("callout:"):
            callout_id = marker_body.removeprefix("callout:")
            callout = callouts_by_id.get(callout_id)
            if callout is None:
                logger.error("Unknown callout id %r in marker — skipping", callout_id)
            else:
                blocks.append(
                    {
                        "type": "callout",
                        "id": callout.id,
                        "variant": callout.variant,
                        "title": callout.title,
                        "body": callout.body,
                    }
                )

        pos = match.end()

    trailing = body_markdown[pos:].strip()
    if trailing:
        blocks.append({"type": "prose", "html": _md.render(trailing)})

    return blocks
