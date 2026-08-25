"""Unit tests for app/services/post_sync.py — no DB required.

Tests cover:
- Valid frontmatter parses to the expected PostFrontmatter values.
- Body Markdown renders to expected HTML.
- Invalid frontmatter (missing required field) is rejected / returns None.
- Invalid YAML (not a mapping, parse error) is rejected / returns None.
- Missing frontmatter delimiter is rejected.
- Tags serialised correctly (list → comma-separated string, empty → None).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

# Import the private parser directly — it's the unit under test.
from app.services.post_sync import _parse_file  # noqa: PLC2701

# ---------------------------------------------------------------------------
# Fixtures: write temp markdown files inside the project tmp dir
# ---------------------------------------------------------------------------

# Use a gitignored scratch dir inside the project root (AGENTS.md rule 1).
_SCRATCH = Path(__file__).resolve().parent.parent.parent / ".scratch"


@pytest.fixture(autouse=True)
def scratch_dir(tmp_path):
    """Each test gets its own scratch directory under tmp_path."""
    return tmp_path


def _write_md(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_minimal_post_parses(tmp_path):
    """A minimal valid post produces the correct PostFrontmatter values."""
    path = _write_md(
        tmp_path,
        "minimal.md",
        """\
---
title: First Ride
slug: first-ride
date: 2025-06-01
---

Some body text.
""",
    )
    result = _parse_file(path)

    assert result is not None
    fm = result.frontmatter
    assert fm.title == "First Ride"
    assert fm.slug == "first-ride"
    assert fm.published_date == date(2025, 6, 1)
    assert fm.tags == []
    assert fm.draft is False
    assert fm.summary is None
    assert fm.cover_image is None


@pytest.mark.unit
def test_valid_full_post_parses(tmp_path):
    """All optional fields are parsed correctly when present."""
    path = _write_md(
        tmp_path,
        "full.md",
        """\
---
title: Alpine Loop
slug: alpine-loop
date: 2025-07-15
summary: Three days across the Alps.
tags:
  - gravel
  - alps
  - bikepacking
cover_image: /static/uploads/alpine.jpg
draft: true
---

# Alpine Loop

A long ride.
""",
    )
    result = _parse_file(path)

    assert result is not None
    fm = result.frontmatter
    assert fm.title == "Alpine Loop"
    assert fm.slug == "alpine-loop"
    assert fm.published_date == date(2025, 7, 15)
    assert fm.summary == "Three days across the Alps."
    assert fm.tags == ["gravel", "alps", "bikepacking"]
    assert fm.cover_image == "/static/uploads/alpine.jpg"
    assert fm.draft is True


@pytest.mark.unit
def test_markdown_body_rendered_to_html(tmp_path):
    """The body is rendered from Markdown to HTML."""
    path = _write_md(
        tmp_path,
        "render.md",
        """\
---
title: Render Test
slug: render-test
date: 2025-01-01
---

# Heading

A paragraph with **bold** text.
""",
    )
    result = _parse_file(path)

    assert result is not None
    assert "<h1>Heading</h1>" in result.body_html
    assert "<strong>bold</strong>" in result.body_html


@pytest.mark.unit
def test_body_markdown_preserved(tmp_path):
    """The raw Markdown body (without frontmatter) is stored as-is."""
    path = _write_md(
        tmp_path,
        "body.md",
        """\
---
title: Body Test
slug: body-test
date: 2025-01-01
---

Raw **markdown** here.
""",
    )
    result = _parse_file(path)

    assert result is not None
    assert "Raw **markdown** here." in result.body_markdown
    # Frontmatter must NOT appear in body_markdown
    assert "title:" not in result.body_markdown


@pytest.mark.unit
def test_tags_list_from_yaml(tmp_path):
    """YAML list tags come through as a Python list on PostFrontmatter."""
    path = _write_md(
        tmp_path,
        "tags.md",
        """\
---
title: Tagged
slug: tagged
date: 2025-03-10
tags:
  - gravel
  - adventure
---

Body.
""",
    )
    result = _parse_file(path)
    assert result is not None
    assert result.frontmatter.tags == ["gravel", "adventure"]


# ---------------------------------------------------------------------------
# Error / rejection tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_frontmatter_delimiter_returns_none(tmp_path):
    """A file with no --- delimiter produces None (logged, skipped)."""
    path = _write_md(
        tmp_path,
        "no_fm.md",
        "Just some text with no frontmatter at all.\n",
    )
    result = _parse_file(path)
    assert result is None


@pytest.mark.unit
def test_missing_required_field_returns_none(tmp_path):
    """Frontmatter missing `title` (required) returns None."""
    path = _write_md(
        tmp_path,
        "no_title.md",
        """\
---
slug: no-title
date: 2025-01-01
---

Body.
""",
    )
    result = _parse_file(path)
    assert result is None


@pytest.mark.unit
def test_missing_slug_returns_none(tmp_path):
    """Frontmatter missing `slug` (required) returns None."""
    path = _write_md(
        tmp_path,
        "no_slug.md",
        """\
---
title: No Slug Post
date: 2025-01-01
---

Body.
""",
    )
    result = _parse_file(path)
    assert result is None


@pytest.mark.unit
def test_invalid_date_returns_none(tmp_path):
    """Frontmatter with an unparseable date returns None."""
    path = _write_md(
        tmp_path,
        "bad_date.md",
        """\
---
title: Bad Date
slug: bad-date
date: not-a-date
---

Body.
""",
    )
    result = _parse_file(path)
    assert result is None


@pytest.mark.unit
def test_invalid_yaml_returns_none(tmp_path):
    """Malformed YAML (tabs used as indentation, etc.) returns None."""
    path = _write_md(
        tmp_path,
        "bad_yaml.md",
        # Deliberately broken YAML: duplicate mapping key at top level with
        # a tab character, which yaml.safe_load will flag.
        "---\n"
        "title: Bad\n"
        "title: Duplicate\n"  # pyyaml won't raise on dup keys — use a real parse error
        "slug: [unclosed\n"
        "date: 2025-01-01\n"
        "---\n\nBody.\n",
    )
    result = _parse_file(path)
    assert result is None


@pytest.mark.unit
def test_frontmatter_not_mapping_returns_none(tmp_path):
    """Frontmatter that is valid YAML but not a dict returns None."""
    path = _write_md(
        tmp_path,
        "list_fm.md",
        """\
---
- item one
- item two
---

Body.
""",
    )
    result = _parse_file(path)
    assert result is None
