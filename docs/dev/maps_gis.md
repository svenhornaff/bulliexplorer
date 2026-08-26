# BulliExplorer — Maps & GIS

> Closes bucket #1 from `buckets.md`. Builds on decisions already made in
> this conversation: routes/POIs are **owned by the post** (0-1 route,
> 0-many points of interest per post), authored through Sveltia alongside
> the post itself — no separate `/routes/{slug}` or `/campsites/{slug}`
> pages in v1. See `editor_cms.md` for the CMS this extends and
> `post_and_backend.md` for the `Post` model this attaches to.

---

## What changed since the original schema

`app/models/campsite.py` and `app/models/route.py` have existed, untouched,
since the very first Alembic migration — no `slug`, no relationship to
`Post`, no timestamps, and (per this conversation) a scope that's grown from
"campsites" to "campsites, restaurants, hotels, gas stations, and whatever
else comes up." A dedicated `Campsite` table doesn't fit that anymore.

**Model change: `Campsite` → `PointOfInterest`, with a `category` field.**
One table, one enum-like column, extensible by adding a new category value
rather than a new migration every time a new POI type comes up.

---

## Data model

```python
# app/models/route.py — as actually implemented in Phase 1, plus new
# stats columns (this refactor) computed from the GPX during Phase 2 sync
class Route(Base):
    __tablename__ = "routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    track: Mapped[str] = mapped_column(Geometry("LINESTRING", srid=4326))
    # New: ride stats, computed once from the parsed GPX (Phase 2) —
    # every real GPX-viewer tool checked treats these as baseline, not
    # optional. Nullable: a route always has a name, but stats depend on
    # what the GPX actually contains (e.g. no timestamps = no duration).
    distance_km: Mapped[float | None] = mapped_column(default=None)
    elevation_gain_m: Mapped[float | None] = mapped_column(default=None)
    elevation_loss_m: Mapped[float | None] = mapped_column(default=None)
    duration_minutes: Mapped[float | None] = mapped_column(default=None)

# app/models/point_of_interest.py — as actually implemented in Phase 1
class PointOfInterest(Base):
    __tablename__ = "points_of_interest"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50))  # campsite, restaurant, hotel, gas_station, viewpoint, bike_shop, water_point, other
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    location: Mapped[str] = mapped_column(Geometry("POINT", srid=4326))
```

`Route.post_id` is nullable + `unique=True` — enforces the 0-1
relationship at the database level (a route either doesn't exist for a
post, or there's exactly one). `PointOfInterest.post_id` is a plain
non-nullable FK — a POI row only ever exists because it belongs to a
specific post; "zero POIs" is simply zero rows, nothing to make nullable.
Confirmed against the actual Phase 1 migration and models — this is not
a proposal, it's what's already running.

---

## Authoring: three real options, not just "type coordinates"

This was the open question from "how is this doable with Sveltia" — worth
laying out the actual alternatives rather than defaulting to the first one
that works.

### Option A: Raw lat/lng number fields (what was proposed first)
Type two numbers per POI, copied from Google Maps/OSM by hand. Works, zero
new code, but genuinely tedious — the actual friction point worth solving.

### Option B: Geocode by name/address — recommended
Author types a place name or address ("Café Sonnenberg, Freiburg") into a
single text field. A server-side geocoding step — during the same sync that
already parses Markdown and GPX — resolves it to coordinates via
**Nominatim** (OpenStreetMap's free geocoding API, no key required, rate
limits are a non-issue at this volume). Raw lat/lng fields stay available
as an optional manual override for when geocoding gets it wrong or the spot
has no clean address (a wild campsite, a trailhead).

This is better authoring UX than Option A *and* less implementation work
than a map-click widget — no new CMS-side code at all, just a small
addition to the existing sync service.

### Option C: Custom Sveltia widget, MapLibre click-to-pin
Genuinely possible (Sveltia supports registering custom widgets), would
give the best authoring experience — but real JavaScript work, and a
maintenance surface of its own. **Deferred** — revisit only if Option B's
occasional bad geocode/manual-override friction turns out to matter in
practice, not pre-built on spec.

**One thing that isn't actually a problem, worth naming explicitly:** the
*route* itself was never a coordinate-typing problem — GPX files come from
a bike computer, phone app, or Strava/Garmin export, recorded during the
ride and uploaded after. Authoring friction only ever applied to POIs, not
the track.

### Also considered and set aside: SQLAdmin for POI entry
The *original* tech concept doc envisioned SQLAdmin as where structured
geo data gets entered. That made more sense under the "independent,
reusable entity" relationship model — this conversation explicitly chose
"owned by the post" instead, which makes editing a POI alongside its post
in Sveltia the more natural fit than a separate admin panel. Not wrong,
just answers a question that got settled differently.

---

## Sveltia config

```yaml
collections:
  - name: "posts"
    folder: "content/posts"
    fields:
      # ...existing title/summary/cover_image/tags/is_draft/body fields...

      - label: "Route (GPX)"
        name: "route"
        widget: "object"
        required: false
        fields:
          - { label: "Route name", name: "name", widget: "string" }
          - label: "GPX file"
            name: "gpx_file"
            widget: "file"
            accept: ".gpx,application/gpx+xml"
          - { label: "Description", name: "description", widget: "text", required: false }

      - label: "Points of interest"
        name: "points_of_interest"
        widget: "list"
        required: false
        fields:
          - { label: "Name", name: "name", widget: "string" }
          - label: "Category"
            name: "category"
            widget: "select"
            options:
              - { label: "Campsite", value: "campsite" }
              - { label: "Restaurant", value: "restaurant" }
              - { label: "Hotel", value: "hotel" }
              - { label: "Gas station", value: "gas_station" }
              - { label: "Viewpoint", value: "viewpoint" }
              - { label: "Bike shop", value: "bike_shop" }
              - { label: "Water point", value: "water_point" }
              - { label: "Other", value: "other" }
          - label: "Place name or address"
            name: "place_query"
            widget: "string"
            hint: "Geocoded automatically on publish. Leave coordinates below blank unless this needs a manual override."
          - { label: "Latitude (manual override)", name: "lat", widget: "number", value_type: "float", required: false }
          - { label: "Longitude (manual override)", name: "lng", widget: "number", value_type: "float", required: false }
          - { label: "Notes", name: "notes", widget: "text", required: false }
```

---

## Basemap tiles

**Protomaps + PMTiles**, self-hosted — a single static tile file served via
HTTP range requests, no tile-server process to run. Extract a regional
bounding box (Black Forest / Germany, not the full ~107GB world file) to
keep it small. Host the `.pmtiles` file on the R2 bucket already planned
for media — consistent with existing infra, no new storage account.
MapLibre reads it via the `pmtiles` JS plugin (`addProtocol`), same pattern
already decided when MapLibre itself was chosen over Leaflet/Mapbox.

---

## Phased implementation plan

### Phase 1 — Schema migration

**Scope**
- [x] New Alembic migration: rename/replace `campsites` → `points_of_interest`
  with `category` column; add `post_id` FK to both `routes` (unique) and
  `points_of_interest` (plain FK).
- [x] `app/models/point_of_interest.py` replaces `app/models/campsite.py`.
- [x] Update `app/models/route.py` with the new `post_id` column.

**Done when**
- [x] `alembic upgrade head` runs clean on a fresh DB and on the existing dev
  DB (test both — a rename migration is exactly the kind that works on
  one and silently corrupts the other).
- [x] Existing `Post`/`Route`/`PointOfInterest` unit tests (updated for the
  new fields) pass.

**Left over**
None.

**Summary**
Replaced `app/models/campsite.py` with `app/models/point_of_interest.py` —
a single table for all POI types differentiated by a `category` column
(`campsite`, `restaurant`, `hotel`, etc.). Added `post_id` FK to `Route`
(unique — enforces 0-1 relationship) and `PointOfInterest` (plain FK —
0-many). Alembic migration drops `campsites`, creates
`points_of_interest`, and adds `post_id` to `routes`. Verified on both
the existing dev DB and a fresh DB. Added `shapely` dependency for
geometry round-trip testing. Four new integration tests verify
`LineString`/`Point` round-trips through PostGIS, the unique constraint
on `Route.post_id`, and multiple POIs per post. Updated all existing
integration test fixtures to respect the new FK ordering.

**Recommended next steps**
- Phase 2 needs `gpxpy` added and `post_sync.py` extended to parse GPX
  files from frontmatter and upsert `Route`/`PointOfInterest` rows.
- The Sveltia CMS config (`static/editor/config.yml`) will need the new
  `route` and `points_of_interest` fields added — that’s Phase 2 scope.
- The `PostFrontmatter` Pydantic schema will need optional route/POI
  fields — also Phase 2.

### Phase 2 — GPX parsing + sync

**Scope**
- [x] `uv add gpxpy`.
- [x] `PostFrontmatter` (Pydantic): `route` and `points_of_interest` fields
  are genuinely optional (`| None` / default empty list) — not "usually
  absent by convention," an enforced requirement. This is what makes
  "maps are never mandatory" a guarantee rather than a hope.
- [x] Extend `app/services/post_sync.py` (or a sibling service, framework-free
  per `AGENTS.md`) to: read the `route.gpx_file` path from frontmatter if
  present, parse it into a `LINESTRING`, upsert the `Route` row tied to
  `post_id`.
- [x] **Compute ride stats during the same parse**: `distance_km`,
  `elevation_gain_m`, `elevation_loss_m` from the track's geometry/
  elevation data, `duration_minutes` if the GPX has timestamps (many
  don't — leave `None` rather than guessing). `gpxpy` exposes these
  directly (`length_2d()`, `get_uphill_downhill()`, `get_duration()`) —
  no extra parsing pass, same data already being read for the geometry.
- [x] Same extension point handles `points_of_interest` — for now, geocoding
  not yet wired (Phase 3), so start with the **manual lat/lng override**
  path working end to end first.
- [x] **Reconciliation, not just insertion**: if a post's frontmatter
  previously had a `route`/`points_of_interest` and a later edit removes
  it, sync must delete the now-orphaned `Route`/`PointOfInterest` rows —
  the existing "files are the source of truth" reconciliation `post_sync.py`
  already does for whole deleted posts has to apply *within* a still-
  existing post's route/POI fields too, not just be assumed to follow
  along for free.

**Done when**
- [x] A fixture post with a GPX file + manual-coordinate POIs syncs correctly
  — `Route` and `PointOfInterest` rows exist, geometry round-trips through
  PostGIS correctly (this was flagged back in `AGENTS.md` as the part of
  the stack most likely to break silently — still true here).
- [x] Computed stats on the fixture route match values independently
  calculated from the same GPX (e.g. via a known-good external tool) —
  don't just assert the fields are non-null, assert they're *correct*.
- [x] A post with no route/POIs (the two existing real posts) still syncs
  unaffected — this must be fully backward compatible. **Add this as an
  explicit regression test**, not an assumption — this is the single most
  common case (every post today) and deserves its own test, not just the
  absence of a failure.
- [x] A fixture post that *had* a route, then has it removed from frontmatter
  and is re-synced: confirm the `Route` row is actually deleted, not left
  orphaned.

**Left over**
None.

**Summary**
Added `gpxpy` dependency and `RouteFrontmatter`/`PoiFrontmatter` Pydantic
models to `post_schema.py`, making route and POI fields genuinely optional
on every post. Added four stats columns (`distance_km`, `elevation_gain_m`,
`elevation_loss_m`, `duration_minutes`) to `Route` via a new Alembic
migration. Created `app/services/geo_sync.py` — a framework-free sibling
to `post_sync.py` — that parses GPX files with `gpxpy`, computes ride stats
in the same pass, upserts `Route` rows, and delete-then-reinserts
`PointOfInterest` rows (manual lat/lng path only; geocoding is Phase 3).
Extended `post_sync.py` to call the geo sync after flushing each post's
row, and updated `_delete_removed` to explicitly cascade child-row
deletion (no DB-level CASCADE on the FKs). 29 new tests (14 unit, 8
geo-sync integration, plus model column assertions) cover all four "Done
when" criteria; `make ci` green at 94.86% coverage.

**Recommended next steps**
- Phase 3 (Geocoding): add the Nominatim client to `geo_sync.py`;
  `_resolve_poi_location` already returns `None` for the `place_query`-only
  path — Phase 3 just needs to fill that branch in. Respect the 1 req/s
  rate limit and `User-Agent` header requirement.
- The Sveltia CMS config (`static/editor/config.yml`) still needs the
  `route` and `points_of_interest` collection fields added — was called
  out in Phase 1 recommended next steps but is not in Phase 2 or 3 scope
  bullets; should be addressed before Phase 5 (Frontend rendering) so
  authors can actually create geo content via the CMS.
- GPX path resolution currently requires the file to live in the same
  directory as the `.md` file (`content_dir`). Sveltia's `file` widget
  will upload to `media_folder` (`static/uploads/`) — Phase 5 will need
  to align the path convention or adjust `_resolve_gpx_path` accordingly.
- `_delete_removed` now explicitly deletes Route and POI child rows before
  deleting posts to work around the missing CASCADE. Consider adding
  `ondelete="CASCADE"` to the FK columns in a future migration to
  simplify this path (low priority — the explicit approach is readable).

### Phase 3 — Geocoding

**Scope**
- Small Nominatim client (`httpx`, already a dependency) in the sync
  service: if `place_query` is set and `lat`/`lng` are blank, geocode and
  fill them in; if `lat`/`lng` are explicitly set, skip geocoding entirely
  (manual override always wins).
- Respect Nominatim's usage policy: identify via `User-Agent`, cap request
  rate (trivial at this content volume, but do it correctly rather than
  assuming volume stays low forever).
- Log (not crash) on a failed/ambiguous geocode — a POI that fails to
  resolve should skip that one POI, not break the whole post sync, same
  "one broken thing doesn't take down the batch" principle already
  established for post frontmatter validation.

**Done when**
- A fixture POI with only `place_query` set resolves to correct
  coordinates.
- A fixture POI with manual `lat`/`lng` set is *not* geocoded (network
  call never happens — verify via a mock that asserts zero calls).
- A deliberately bad `place_query` ("asdkfjasldkfj") fails gracefully —
  POI skipped, sync continues, logged.

### Phase 4 — Basemap setup

**Scope**
- Generate/extract the regional PMTiles file (Protomaps' extraction
  tooling, one-time, not app code).
- Upload to R2, confirm it's reachable via the `pmtiles` protocol from a
  local MapLibre test page.

**Done when**
- A minimal standalone HTML page (not yet wired into the app) renders the
  regional basemap correctly via MapLibre + PMTiles from the R2 URL.

### Phase 5 — Frontend rendering

**Scope**
- Route/POI data reaches the template via the existing post-detail route
  in `app/routes/posts.py` — **extend the query with a `LEFT JOIN` (or a
  separate optional query), never an inner join / eager `joinedload` that
  defaults to inner-join semantics.** An inner join here would silently
  exclude every post without a route from the page — an easy mistake to
  make without thinking about it directly, worth stating as a hard
  requirement rather than trusting it to come out right by accident.
- `templates/post.html`: conditionally render a MapLibre map, guarded
  explicitly — `{% if post.route %}` / `{% if post.points_of_interest %}`,
  not an assumption that `None`/an empty list renders harmlessly by
  default. Shows the route line and POI markers, color/icon-coded by
  `category`.
- **Stats row alongside the map**: distance, elevation gain/loss, and
  duration (if available) from the Phase-2-computed `Route` fields — e.g.
  "68 km · 1,240m climbed." This is the cheap, near-free half of the
  elevation-profile research finding — display the numbers now.

**Done when**
- The real post created earlier in this project (`sunday-gravel-loop` or
  `kinzig-valley-loop`) can have a route/POIs added through Sveltia and
  renders correctly on the live post page, including the stats row — this
  is the actual end-to-end proof, not a synthetic fixture.
- A post with no route/POIs renders exactly as it does today — zero
  regression for existing content. Verify this against the `/posts/`
  **list** page too, not just individual post pages — confirm the join
  change in the list query doesn't drop or duplicate routeless posts.

---

## Explicitly deferred

- **Interactive elevation profile chart** (hover-synced with the map —
  what every GPX-viewer tool checked during research does, beyond the
  plain stats row). Real additional scope: a charting library or custom
  SVG, plus per-point elevation data threaded through to the frontend
  (the stats row only needs aggregate totals, a chart needs the full
  series). Worth its own phase later, deliberately not bundled into
  Phase 5 — the stats numbers are the near-free 80% of the value; the
  chart is the expensive 20%.
- **Discovery map** (`/map`, all routes/POIs across every post at once) —
  genuinely valuable, but a separate feature from "impact on a blog post."
  Revisit once there are enough posts with routes to make one worthwhile.
- **Custom map-click widget in Sveltia** (Option C above) — only if
  Option B's manual-override friction proves real in practice.
- **Geometry simplification** for large/many tracks — not a concern at
  current content volume; revisit if load times degrade.
- **Route/POI reuse across multiple posts** — ruled out by the
  owned-by-post decision; revisit only if that decision is revisited.

---

## Explicitly out of scope for this doc

Two items surfaced during "modern blog 2026" research that are real but
belong to other buckets from `buckets.md`, not here — noted so they're not
lost, not folded in where they don't fit:

- **`llms.txt`** (AI-crawler discovery file) — checked current guidance:
  Google's May 2026 AI-Search documentation explicitly excludes it from
  helping AI Overviews/AI Mode, and adoption studies show no correlation
  with AI citation frequency. Cheap if ever wanted, not urgent, and it's
  an SEO/syndication-bucket item (#4), unrelated to maps.
- **Dark mode** — came up repeatedly in the same research as a genuine
  2026 reader expectation. A UI/UX-bucket item (#2), not a maps concern.