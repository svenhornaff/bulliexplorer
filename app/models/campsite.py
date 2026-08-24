"""Campsite model — PostGIS PointField."""

from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Campsite(Base):
    __tablename__ = "campsites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    location: Mapped[str] = mapped_column(Geometry("POINT", srid=4326))
