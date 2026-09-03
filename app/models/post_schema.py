"""Pydantic schema for blog post frontmatter validation.

Every Markdown file in ``content/posts/`` must have YAML frontmatter that
validates against :class:`PostFrontmatter`. See AGENTS.md — any field change
here must be synced to existing posts and noted in CHANGELOG.md.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class RouteFrontmatter(BaseModel):
    """Frontmatter block describing a GPX-backed route for this post.

    The ``gpx_file`` value is resolved relative to the ``content_dir``
    that ``sync_posts`` receives — typically the same directory as the
    Markdown file itself.
    """

    name: str
    gpx_file: str
    description: str | None = None


class GalleryImageFrontmatter(BaseModel):
    """One image within a gallery block.

    ``alt`` is mandatory — enforced here at the schema level (Phase 4,
    docs/dev/ui_ux_refresh.md §5.3) rather than left as a template
    convention that can be silently skipped.
    """

    src: str
    alt: str
    caption: str | None = None


class GalleryFrontmatter(BaseModel):
    """A named gallery block, placed in the body via ``[[gallery:<id>]]``."""

    id: str
    images: list[GalleryImageFrontmatter]


class CalloutFrontmatter(BaseModel):
    """A named callout (tip/warning aside), placed via ``[[callout:<id>]]``."""

    id: str
    variant: str = "tip"
    title: str | None = None
    body: str


class PoiFrontmatter(BaseModel):
    """One point of interest listed in the post's frontmatter.

    Either ``place_query`` (resolved in Phase 3 via Nominatim) or an
    explicit ``lat``/``lng`` pair must ultimately be available for the row
    to be written.  If neither is provided the POI is skipped with a
    warning (not a hard error).
    """

    name: str
    category: str
    place_query: str | None = None
    lat: float | None = None
    lng: float | None = None
    notes: str | None = None


class PostFrontmatter(BaseModel):
    """Validates the YAML frontmatter block at the top of each Markdown post."""

    title: str
    slug: str
    summary: str | None = None
    published_date: date = Field(alias="date")
    tags: list[str] = Field(default_factory=list)
    cover_image: str | None = None
    draft: bool = False

    # Optional geo fields — maps are never mandatory.
    route: RouteFrontmatter | None = None
    points_of_interest: list[PoiFrontmatter] = Field(default_factory=list)

    # Optional body-block content (Phase 4, docs/dev/ui_ux_refresh.md §5.3).
    # Placed in the body via [[gallery:<id>]] / [[callout:<id>]] markers;
    # an entry defined here but never referenced by a marker is simply
    # unused, not an error.
    galleries: list[GalleryFrontmatter] = Field(default_factory=list)
    callouts: list[CalloutFrontmatter] = Field(default_factory=list)
