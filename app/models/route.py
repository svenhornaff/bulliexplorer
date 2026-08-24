"""Route model — PostGIS LineStringField for GPX tracks."""

from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    track: Mapped[str] = mapped_column(Geometry("LINESTRING", srid=4326))
