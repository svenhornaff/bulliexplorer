"""Blog post model — Markdown content with Pydantic-validated frontmatter."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Post(Base):
    """A blog post stored in the database.

    Content is authored as Markdown files in ``content/posts/``, validated
    via :class:`PostFrontmatter`, then persisted here for querying, full-text
    search, and listing.
    """

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    body_markdown: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str] = mapped_column(Text, default="")
    # Ordered render plan for the post body (Phase 4, docs/dev/
    # ui_ux_refresh.md §5.3): a list of {"type": ..., ...} block dicts
    # ("prose", "gallery", "callout", "route-map") built at sync time from
    # body_markdown + frontmatter markers, replacing the single body_html
    # blob as the source templates render from. body_html is kept alongside
    # for one migration cycle (see AGENTS.md content-schema-sync rule) and
    # is planned for removal in Phase 5.
    body_blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Frontmatter metadata
    published_date: Mapped[date] = mapped_column(Date)
    tags: Mapped[str | None] = mapped_column(Text, default=None)  # comma-separated
    cover_image: Mapped[str | None] = mapped_column(String(512), default=None)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
