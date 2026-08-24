"""Tests for blog post frontmatter Pydantic schema."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.post_schema import PostFrontmatter


@pytest.mark.unit
def test_valid_frontmatter_minimal():
    fm = PostFrontmatter(title="First Ride", slug="first-ride", date="2025-06-01")
    assert fm.title == "First Ride"
    assert fm.slug == "first-ride"
    assert fm.published_date == date(2025, 6, 1)
    assert fm.tags == []
    assert fm.draft is False
    assert fm.summary is None
    assert fm.cover_image is None


@pytest.mark.unit
def test_valid_frontmatter_full():
    fm = PostFrontmatter(
        title="Alpine Loop",
        slug="alpine-loop",
        date="2025-07-15",
        summary="Three days across the Alps.",
        tags=["gravel", "alps", "bikepacking"],
        cover_image="/static/uploads/alpine.jpg",
        draft=True,
    )
    assert fm.published_date == date(2025, 7, 15)
    assert fm.tags == ["gravel", "alps", "bikepacking"]
    assert fm.draft is True
    assert fm.cover_image == "/static/uploads/alpine.jpg"


@pytest.mark.unit
def test_frontmatter_missing_required_fields():
    with pytest.raises(Exception):  # noqa: B017
        PostFrontmatter(slug="no-title", date="2025-01-01")  # type: ignore[call-arg]


@pytest.mark.unit
def test_frontmatter_invalid_date():
    with pytest.raises(Exception):  # noqa: B017
        PostFrontmatter(title="Bad Date", slug="bad-date", date="not-a-date")
