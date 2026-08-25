"""Point of interest model — replaces the original Campsite model.

One table for all POI types (campsites, restaurants, hotels, etc.),
differentiated by a ``category`` column. Each POI belongs to exactly one
:class:`~app.models.post.Post` (0-many relationship).
"""

from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PointOfInterest(Base):
    """A geo-located point of interest owned by a blog post."""

    __tablename__ = "points_of_interest"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    location: Mapped[str] = mapped_column(Geometry("POINT", srid=4326))
