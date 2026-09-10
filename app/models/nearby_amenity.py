"""Nearby amenity model — auto-discovered, not authored.

Distinct from :class:`~app.models.point_of_interest.PointOfInterest`:
that model is *editorial* content (the author chose it, wrote a note about
it). This model is *derived* data — an Overpass query found it within a
buffer of the route's track. Conflating the two would mean a reader could
no longer tell "the author specifically recommends this" from "this
happens to exist nearby" (``docs/dev/gis_cycling_upgrade.md`` Phase 4).

Tied to ``route_id``, not ``post_id`` directly — amenities are a property
of the geography a route passes through, not of the post's own content.
"""

from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NearbyAmenity(Base):
    """An amenity discovered near a route via the Overpass API.

    ``osm_element_type``/``osm_element_id`` together uniquely identify the
    OpenStreetMap element this row was derived from (OSM IDs are only
    unique *within* their element type — a node and a way can share the
    same numeric id, so either column alone is not a valid key).
    """

    __tablename__ = "nearby_amenities"
    __table_args__ = (
        UniqueConstraint(
            "route_id",
            "osm_element_type",
            "osm_element_id",
            name="uq_nearby_amenities_route_osm_element",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    osm_element_type: Mapped[str] = mapped_column(String(10))
    osm_element_id: Mapped[int] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(50))
    name: Mapped[str | None] = mapped_column(String(255), default=None)
    location: Mapped[str] = mapped_column(Geometry("POINT", srid=4326))
    tags: Mapped[dict[str, str] | None] = mapped_column(JSONB, default=None)
