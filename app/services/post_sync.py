"""Markdown → database sync service.

Reads every ``*.md`` file under ``content/posts/``, validates YAML
frontmatter against :class:`~app.models.post_schema.PostFrontmatter`,
renders the body to HTML via ``markdown-it-py``, then upserts into the
``posts`` table.

Design rules (per AGENTS.md):
- **Framework-free**: no FastAPI, Jinja2, or sqladmin imports here.
- **Resilient**: a file that fails parsing/validation is skipped with an
  error log — one bad post must not abort the sync for all others.
- **Reconciling**: posts whose ``.md`` file has been deleted are removed
  from the DB on the next sync (files are source of truth).
- **Idempotent**: running sync twice with unchanged files produces no DB
  writes the second time.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from markdown_it import MarkdownIt
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.models.post_schema import PostFrontmatter
from app.utils.log_factory import get_logger

logger = get_logger(__name__)

# Single shared Markdown renderer — stateless, safe to reuse.
_md = MarkdownIt()

# Regex that splits the leading YAML frontmatter block (--- ... ---) from
# the rest of the file.  The frontmatter delimiters must be the very first
# line; trailing whitespace on the closing --- is allowed.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


async def sync_posts(
    content_dir: Path,
    session: AsyncSession,
) -> dict[str, int]:
    """Reconcile ``content_dir/*.md`` files with the ``posts`` table.

    Parameters
    ----------
    content_dir:
        Directory that contains the Markdown post files (``content/posts/``
        by default, but callers may pass any path — useful for tests).
    session:
        An open ``AsyncSession``.  The caller owns the transaction; this
        function does **not** commit or roll back.

    Returns
    -------
    dict with keys ``upserted``, ``deleted``, ``skipped`` counting what
    happened during this run.
    """
    md_files = sorted(content_dir.glob("*.md"))

    counts = {"upserted": 0, "deleted": 0, "skipped": 0}

    # ── 1. Parse + validate every file, build slug → parsed data map ────────
    parsed: dict[str, _ParsedPost] = {}
    for path in md_files:
        result = _parse_file(path)
        if result is None:
            counts["skipped"] += 1
            continue
        parsed[result.frontmatter.slug] = result

    # ── 2. Upsert all successfully parsed posts ──────────────────────────────
    for _slug, pp in parsed.items():
        await _upsert_post(session, pp)
        counts["upserted"] += 1

    # ── 3. Delete DB rows whose slug is no longer in the file set ────────────
    live_slugs = set(parsed.keys())
    deleted = await _delete_removed(session, live_slugs)
    counts["deleted"] = deleted

    logger.info(
        "Post sync complete — upserted=%d  deleted=%d  skipped=%d",
        counts["upserted"],
        counts["deleted"],
        counts["skipped"],
    )
    return counts


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


class _ParsedPost:
    """Intermediate representation of a successfully parsed Markdown file."""

    __slots__ = ("frontmatter", "body_markdown", "body_html")

    def __init__(self, frontmatter: PostFrontmatter, body_markdown: str, body_html: str) -> None:
        self.frontmatter = frontmatter
        self.body_markdown = body_markdown
        self.body_html = body_html


def _parse_file(path: Path) -> _ParsedPost | None:
    """Parse a single ``.md`` file.

    Returns ``None`` and logs an error if anything goes wrong, so the caller
    can skip this file and carry on.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Could not read %s: %s", path, exc)
        return None

    match = _FRONTMATTER_RE.match(raw)
    if not match:
        logger.error("No valid YAML frontmatter in %s — skipping", path)
        return None

    yaml_block, body_markdown = match.group(1), match.group(2).strip()

    try:
        raw_fm = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        logger.error("YAML parse error in %s: %s — skipping", path, exc)
        return None

    if not isinstance(raw_fm, dict):
        logger.error("Frontmatter in %s is not a YAML mapping — skipping", path)
        return None

    try:
        frontmatter = PostFrontmatter.model_validate(raw_fm)
    except ValidationError as exc:
        logger.error("Frontmatter validation failed for %s: %s — skipping", path, exc)
        return None

    body_html = _md.render(body_markdown)

    return _ParsedPost(frontmatter=frontmatter, body_markdown=body_markdown, body_html=body_html)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _upsert_post(session: AsyncSession, pp: _ParsedPost) -> None:
    """Insert or update a single post row by slug."""
    fm = pp.frontmatter

    # Fetch existing row (if any) by slug.
    result = await session.execute(select(Post).where(Post.slug == fm.slug))
    existing = result.scalar_one_or_none()

    tags_str = ",".join(fm.tags) if fm.tags else None

    if existing is None:
        post = Post(
            slug=fm.slug,
            title=fm.title,
            summary=fm.summary,
            body_markdown=pp.body_markdown,
            body_html=pp.body_html,
            published_date=fm.published_date,
            tags=tags_str,
            cover_image=fm.cover_image,
            is_draft=fm.draft,
        )
        session.add(post)
        logger.debug("Inserted post slug=%r", fm.slug)
    else:
        # Only touch the row if something actually changed — keeps sync
        # idempotent and avoids spurious `updated_at` bumps.
        changed = False
        fields: dict[str, object] = {
            "title": fm.title,
            "summary": fm.summary,
            "body_markdown": pp.body_markdown,
            "body_html": pp.body_html,
            "published_date": fm.published_date,
            "tags": tags_str,
            "cover_image": fm.cover_image,
            "is_draft": fm.draft,
        }
        for attr, value in fields.items():
            if getattr(existing, attr) != value:
                setattr(existing, attr, value)
                changed = True
        if changed:
            logger.debug("Updated post slug=%r", fm.slug)
        else:
            logger.debug("Post slug=%r unchanged — no write", fm.slug)


async def _delete_removed(session: AsyncSession, live_slugs: set[str]) -> int:
    """Delete any DB rows whose slug is not in ``live_slugs``.

    Returns the number of rows deleted.
    """
    # Fetch all slugs currently in the table.
    result = await session.execute(select(Post.slug))
    db_slugs = {row[0] for row in result.all()}

    orphaned = db_slugs - live_slugs
    if not orphaned:
        return 0

    await session.execute(delete(Post).where(Post.slug.in_(orphaned)))
    logger.info("Deleted %d removed post(s): %s", len(orphaned), sorted(orphaned))
    return len(orphaned)
