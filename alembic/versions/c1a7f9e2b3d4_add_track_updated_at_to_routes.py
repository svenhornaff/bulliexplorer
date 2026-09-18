"""add track_updated_at to routes

Revision ID: c1a7f9e2b3d4
Revises: 4a7b4678b2db
Create Date: 2026-09-18 17:50:00.000000

docs/dev/fix_amenity_resync_freshness.md Phase 1 — the geometry-change
timestamp the amenity resync freshness check compares against
`amenities_synced_at`. Backfilled to "now" for every existing route
(deliberately conservative: treats every current route as if its
geometry just changed, so the freshness check starts from "not fresh
enough to skip" rather than trusting an unknown real history).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a7f9e2b3d4"
down_revision: str | Sequence[str] | None = "4a7b4678b2db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("routes", sa.Column("track_updated_at", sa.DateTime(timezone=True), nullable=True))
    # Backfill: existing routes' real geometry-change history is unknown,
    # so treat them all as "just changed" rather than guessing — see the
    # module docstring above and docs/dev/fix_amenity_resync_freshness.md
    # Phase 1.
    op.execute("UPDATE routes SET track_updated_at = now() WHERE track_updated_at IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("routes", "track_updated_at")
