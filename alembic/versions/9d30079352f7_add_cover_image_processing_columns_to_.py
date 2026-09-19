"""add cover image processing columns to posts

Revision ID: 9d30079352f7
Revises: c1a7f9e2b3d4
Create Date: 2026-09-19 18:49:01.527321

docs/dev/fix_lcp_image_and_static_cache.md Finding 1 — cover_image
becomes the SERVED (processed WebP) url; cover_image_source_url is the
raw frontmatter value, kept only so a re-sync can detect an unchanged
cover image without re-fetching/re-processing/re-uploading it every
run. width/height are the processed image's real pixel dimensions, for
explicit <img width height> attributes (a CLS improvement).

No backfill: existing posts' cover_image already holds whatever
unprocessed URL they had before this change shipped. The next sync of
each post (already scheduled to run on every deploy via the startup
sync) treats a currently-unset cover_image_source_url as "changed"
(NULL != any real url), so it naturally gets fetched/processed/
uploaded once, going forward — no explicit backfill script needed,
consistent with the doc's own "new/re-synced posts get the
optimization going forward" scope decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d30079352f7"
down_revision: str | Sequence[str] | None = "c1a7f9e2b3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("posts", sa.Column("cover_image_source_url", sa.String(length=512), nullable=True))
    op.add_column("posts", sa.Column("cover_image_width", sa.Integer(), nullable=True))
    op.add_column("posts", sa.Column("cover_image_height", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posts", "cover_image_height")
    op.drop_column("posts", "cover_image_width")
    op.drop_column("posts", "cover_image_source_url")
