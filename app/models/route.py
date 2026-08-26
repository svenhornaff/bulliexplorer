"""Route model — PostGIS LineStringField for GPX tracks.

Each route belongs to exactly one :class:`~app.models.post.Post`
(0-1 relationship, enforced by ``unique=True`` on ``post_id``).
"""

from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    track: Mapped[str] = mapped_column(Geometry("LINESTRING", srid=4326))

    # Ride stats computed from the GPX during sync (Phase 2).
    # Nullable because not all GPX files contain every field
    # (e.g. no timestamps → no duration).
    distance_km: Mapped[float | None] = mapped_column(Float, default=None)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, default=None)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float, default=None)
    duration_minutes: Mapped[float | None] = mapped_column(Float, default=None)
