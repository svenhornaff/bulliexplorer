"""Pydantic schema for blog post frontmatter validation.

Every Markdown file in ``content/posts/`` must have YAML frontmatter that
validates against :class:`PostFrontmatter`. See AGENTS.md — any field change
here must be synced to existing posts and noted in CHANGELOG.md.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class PostFrontmatter(BaseModel):
    """Validates the YAML frontmatter block at the top of each Markdown post."""

    title: str
    slug: str
    summary: str | None = None
    published_date: date = Field(alias="date")
    tags: list[str] = Field(default_factory=list)
    cover_image: str | None = None
    draft: bool = False
