"""Smoke tests for model imports and table metadata."""

from __future__ import annotations

import pytest

from app.models import Base, PointOfInterest, Post, Route


@pytest.mark.unit
def test_all_models_registered():
    """All models are discovered via Base.metadata (needed by Alembic)."""
    table_names = set(Base.metadata.tables.keys())
    assert "posts" in table_names
    assert "points_of_interest" in table_names
    assert "routes" in table_names


@pytest.mark.unit
def test_post_table_columns():
    columns = {c.name for c in Post.__table__.columns}
    assert "slug" in columns
    assert "title" in columns
    assert "body_markdown" in columns
    assert "published_date" in columns
    assert "is_draft" in columns
    assert "tags" in columns


@pytest.mark.unit
def test_point_of_interest_table_columns():
    columns = {c.name for c in PointOfInterest.__table__.columns}
    assert "name" in columns
    assert "category" in columns
    assert "post_id" in columns
    assert "location" in columns
    assert "notes" in columns


@pytest.mark.unit
def test_route_table_columns():
    columns = {c.name for c in Route.__table__.columns}
    assert "name" in columns
    assert "track" in columns
    assert "post_id" in columns
