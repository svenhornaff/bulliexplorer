"""Route model — PostGIS LineStringField for GPX tracks.

Each route belongs to exactly one :class:`~app.models.post.Post`
(0-1 relationship, enforced by ``unique=True`` on ``post_id``).
"""

from __future__ import annotations

import datetime

from geoalchemy2 import Geometry
from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
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

    # Downsampled [distance_km, elevation_m] pairs for the elevation
    # profile chart (docs/dev/elevation_profile_chart.md Tier 1). None
    # when the GPX has no elevation values at all (some bike-computer
    # recordings omit them) — the template gates the chart on this being
    # present, not on an all-zero flat line.
    elevation_profile: Mapped[list[list[float]] | None] = mapped_column(JSON, default=None)

    # Set on every *attempted* amenity sync (success or failure), never on
    # the route sync itself — this is a per-route cooldown against
    # re-querying Overpass's public instance too often, not a "data is
    # fresh" marker. A resync within the cooldown window skips Overpass
    # entirely and leaves existing NearbyAmenity rows untouched (see
    # geo_sync.py's sync_amenities and docs/dev/gis_cycling_upgrade.md's
    # Phase 4 follow-up).
    amenities_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Set only when the route's actual *geometry* changes — on initial
    # insert, and in geo_sync.py's sync_route update branch, only inside
    # the specific `if str(existing.track) != str(new_track):` comparison,
    # never by the broader `changed` flag that also fires for
    # description/name-only edits. Deliberately a separate signal from
    # `amenities_synced_at` above: this is a "did the physical path move"
    # marker, that one is a "when did we last ask Overpass about it"
    # marker — the amenity-resync freshness check (docs/dev/
    # fix_amenity_resync_freshness.md) compares the two rather than
    # collapsing them into one flag, so a prose-only edit never looks
    # like a geometry change and defeats the freshness skip.
    track_updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
