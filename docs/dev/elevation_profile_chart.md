# Elevation profile chart

> New feature, not a fix — first concept doc in this family that isn't
> chasing a production incident. Two independent tiers: a real, useful
> chart on its own (Tier 1), and an optional Komoot-style interactive
> sync with the map on top (Tier 2). Tier 1 alone is a complete,
> shippable feature — Tier 2 is additive, not required to make Tier 1
> worthwhile.

---

## What's genuinely missing, checked against the actual code

`geo_sync.py`'s GPX parsing calls `gpx.get_uphill_downhill()` — two
aggregate numbers (total ascent, total descent), already shown in the
ride-stats row. Per-point elevation is available in the parsed GPX
object at that moment but is **never persisted** — `Route.track` is
declared `Geometry("LINESTRING", srid=4326)`, a plain 2D line, no Z
dimension. There's nothing to chart yet; this needs a real, if small,
data path, not just frontend work on top of what exists.

**Good news on scale, learned the hard way from the amenity overlay**:
a distance/elevation profile is only ever as detailed as it needs to be
for a chart to look smooth — a few hundred points is plenty regardless
of whether the route is 25km or 4,247km. Unlike amenities, this payload
doesn't grow with route complexity once downsampled, so the 3.7MB
inlining mistake from `fix_amenity_overlay_performance.md` isn't a risk
here by construction — no lazy-loading endpoint needed, inlining
alongside `ROUTE_GEOJSON` is fine.

## Design

**Storage**: a new `elevation_profile` column on `Route` — a JSON array
of `[distance_km, elevation_m]` pairs, computed once during sync
(`geo_sync.py` already has the parsed GPX object in hand at exactly the
point `get_uphill_downhill()` is called) and downsampled to a fixed cap
(e.g. 300 points) regardless of the source track's actual point count.
A plain JSON column, not a new table — this is always a small, bounded,
whole-route blob, never something needing per-point querying or joins
the way `NearbyAmenity` genuinely did.

**Downsampling**: simple fixed-interval resampling — divide the route
into N equal distance segments, take (or average) the elevation at each
boundary. Good enough for a smooth-looking chart; this doesn't need
Douglas-Peucker-style shape-preserving simplification, which solves a
different problem (preserving geometric detail) than this one (a
readable line chart).

**Charting library**: Chart.js, vendored locally the same way
MapLibre/pmtiles/basemaps already are — a real, single-file UMD build,
no bundler, no build step, consistent with this project's whole
frontend architecture. Well-established, genuinely the right tool for
this rather than hand-rolling axis scaling and tooltips from scratch.

## Tier 1 — static chart (complete, shippable on its own)

Checked against the actual current code before writing this plan:
`_parse_gpx` (`app/services/geo_sync.py`) already walks every track
point into a `coords: list[tuple[float, float]]` (lon/lat only, no
elevation kept) at the point the `LineString` is built, then separately
calls `gpx.get_uphill_downhill()` for the two aggregate numbers. Both
happen inside the same function, before `_GpxStats` (a 5-tuple) is
returned to `upsert_route_for_post`, which is the only caller and the
only place a `Route` row is constructed/updated (two branches: insert
and update, both building an `updates`/constructor dict from the same
unpacked tuple). This is the one seam to extend — no new GPX parsing
pass, no new caller to wire up.

**Scope**
- [ ] `Route.elevation_profile: Mapped[list[list[float]] | None]` — a
  `JSON`-typed column (SQLAlchemy's generic `JSON`, same import
  pattern as `Float`/`String`/`Text` already used in `route.py`),
  nullable, `default=None` — matches every other ride-stat column's
  nullability (not all GPX files have elevation data at all;
  `get_uphill_downhill()` already tolerates that by returning `None`/`None`,
  handled today via `uphill or 0.0`). Alembic migration
  (`uv run alembic revision --autogenerate -m "add elevation_profile to routes"`,
  then hand-check the generated `upgrade`/`downgrade` the way every
  prior migration in `alembic/versions/` has been — autogenerate on a
  JSON column addition is usually clean but never trust it unchecked).
- [ ] New pure function `_downsample_elevation_profile(coords_with_elevation, distance_km, max_points=300)`
  in `geo_sync.py`, next to `_parse_gpx` — but `_parse_gpx`'s existing
  `coords` list only keeps `(lon, lat)`; it needs a third element,
  elevation, added to that same tuple/loop (`pt.elevation` is already
  on every `gpxpy` track point, just not read today) rather than a
  second walk over `gpx.tracks`. Fixed-interval resampling as designed
  above: N equal cumulative-distance steps (using the same 2D distance
  gpxpy/shapely already computes, not a new haversine implementation),
  each step's elevation taken from (or averaged around) the nearest
  source point. Output: `list[[distance_km: float, elevation_m: float]]`,
  length `min(len(coords), max_points)` — short/simple routes
  (recorded at a low point count already) must not be padded or
  upsampled, only ever capped.
- [ ] `_parse_gpx` returns the new profile as a 6th tuple element
  (`_GpxStats = tuple[LineString, float, float, float, float | None, list[list[float]] | None]`) —
  update the docstring's tuple description and every unpacking site
  (`upsert_route_for_post`'s `linestring, distance_km, elevation_gain_m, elevation_loss_m, duration_minutes = parsed`
  line, plus both the insert-branch constructor and the update-branch
  `updates` dict, mirroring exactly how `duration_minutes` already
  flows through both branches).
- [ ] `route_geojson`/`pois_geojson` in `app/routes/posts.py`'s
  `post_detail` already establish the "convert to a JSON-safe dict,
  pass through the template context, `|tojson` in the `<script>` block"
  pattern (see `templates/post.html`'s `routeGeojson`/`poisGeojson`
  inline object) — add `elevation_profile: route.elevation_profile` the
  same way, no new conversion helper needed since the column is already
  a plain JSON-serializable list of `[float, float]` pairs.
- [ ] Vendor Chart.js as `static/vendor/chart.js` (the UMD single-file
  build, same acquisition pattern as `maplibre-gl.js`/`pmtiles.js` —
  check in the minified build, note the exact version + source URL in a
  header comment the way `sveltia-cms.js`/`sveltia-cms.source.md`
  already document their own vendoring).
- [ ] New `static/js/elevation-chart.js` (mirrors `post-map.js`'s file
  role/naming), loaded from `post.html`'s existing `{% block scripts %}`
  guard (`{% if route_geojson and tiles_url %}`) — extend that
  conditional's *body*, or add a narrower one keyed off
  `elevation_profile` specifically, since a route can have GeoJSON/tiles
  but no elevation data (GPX without elevation values is valid and
  already handled for the aggregate stats via `or 0.0`). Render inside
  a new container in `templates/partials/route_stats.html`, right after
  the existing `.map-wrap` block, gated the same way
  (`{% if elevation_profile %}`, not folded into the existing
  `{% if route_geojson and tiles_url %}` guard — a route can have
  elevation data without map tiles configured, and vice versa; keep the
  two independent).
- [ ] Theming: follow `post-map.js`'s exact established pattern —
  `document.documentElement.getAttribute("data-theme")` read on init,
  plus a listener on the `"bulliexplorer:themechange"` `CustomEvent`
  `base.html`'s toggle already dispatches, to update Chart.js's dataset
  border color / grid color / text color on the fly (call
  `chart.update()` after mutating `chart.options`, don't
  destroy-and-recreate). Reuse the exact route-line colors already
  established in `post-map.js`'s `routeLineColor(flavor)`
  (`#b85c00` light / `#f0954a` dark) for the chart's line — same brand
  color, same place it's defined conceptually, don't invent a second
  palette. Axis/grid/tick colors from `--color-text-muted`/
  `--color-border` (read via `getComputedStyle` at chart-init/theme-change
  time, since Chart.js needs literal color strings, not CSS custom
  properties, in its config object).

**Done when**
- A post with a route shows a real elevation profile, correct shape
  (visually cross-checked against the known ascent/descent totals
  already displayed in `route_stats.html`'s stat chips — a
  26,179m-ascent route's chart should visibly read as "a lot of
  climbing," not a flat line).
- Chart re-themes correctly on light/dark toggle *without a page
  reload* (the same bar `post-map.js` already meets for the basemap and
  route line) — verified by toggling theme with devtools open and
  confirming the chart's colors update in place.
- A post without a route, or with a route but no elevation values in
  the source GPX (`elevation_profile` is `None`/empty), simply doesn't
  render the chart or its container — no broken empty chart, no empty
  `<canvas>` taking up layout space, same graceful-omission philosophy
  as the amenity toggle (`has_amenities` existence check in
  `app/routes/posts.py`).
- `make ci` green — ruff/pyright/djlint clean, full test suite passing,
  coverage floor met.

**Testing**
- Unit tests for `_downsample_elevation_profile` in
  `tests/unit/test_geo_sync.py` (alongside the existing
  `test_parse_gpx_elevation_gain` etc.): fixed output length regardless
  of input point count (a 10-point and a 10,000-point input both cap at
  `max_points`), a short input (fewer points than `max_points`) is
  capped/passed through, not padded or upsampled, correct
  distance/elevation pairing against a known small hand-built input,
  and a GPX with no elevation values at all returns `None` (mirrors
  `elevation_gain_m`'s existing `0.0`-on-missing handling, but `None`
  here specifically so the template's `{% if elevation_profile %}` gate
  actually omits the chart rather than rendering an all-zero flat line).
- Extend `test_parse_gpx_elevation_gain` — or add a sibling — asserting
  `_parse_gpx`'s 6th tuple element is present and correctly shaped for
  the same fixture GPX already used there.
- Unit test on `upsert_route_for_post` (existing test file for it, if
  any — check `tests/unit/test_geo_sync.py`'s coverage of that function
  specifically) confirming `elevation_profile` round-trips through both
  the insert and update branches, same as every other ride-stat field's
  existing coverage there.
- Manual/visual for the chart rendering itself and the theme-toggle
  re-render, same reasoning as every other client-side rendering phase
  in this project's docs (`post-map.js`'s map rendering has never had
  automated visual tests either — consistent, not a gap specific to
  this feature).

## Tier 2 — Komoot-style hover sync with the map (optional, additive)

Only build this if Tier 1 alone feels incomplete once it's actually
live — genuinely fine to stop at Tier 1.

**Scope**
- [ ] Hovering the chart shows a marker on the map at the corresponding
  point along the route. Needs a small distance-along-line
  interpolation helper — given a target distance-km, walk
  `ROUTE_GEOJSON`'s coordinates accumulating segment lengths until the
  target is reached, interpolate between the two bracketing points.
  Hand-written, ~20 lines — **not** a reason to vendor a whole geometry
  library (Turf.js) for one function, consistent with this project's
  existing preference for small hand-rolled helpers over heavy
  dependencies (the Maki-icon canvas rendering took the same approach).
- [ ] Optional zoom/pan on the chart itself via `chartjs-plugin-zoom`
  (also vendorable as a single file) — the actual "slider and zoom"
  Komoot behavior. Genuinely optional even within Tier 2; hover-sync
  alone already delivers most of the value.
- [ ] Map → chart sync (hovering the route line highlights the matching
  chart position) is **not** in scope even for Tier 2 — meaningfully
  harder (click/hover tolerance detection along a rendered line) for
  proportionally less value than the chart → map direction, which is
  the one Komoot itself leads with.

**Done when**
- Hovering anywhere on the chart moves a visible marker to the correct
  position on the map, tracking smoothly, not just snapping to the
  nearest downsampled point.
- Zoom/pan (if built) doesn't break the hover-sync math — a zoomed
  chart's hover position still maps to the correct real-world point.

**Testing**
- Unit test for the interpolation helper (given a known LineString and
  a target distance, returns the expected coordinate) — this is pure
  math, testable independent of any rendering.
- Manual for the actual hover/zoom interaction.

## Explicitly out of scope

- **Surface-type-synced coloring on the chart** (paved/gravel bands) —
  this is `gis_cycling_upgrade.md`'s already-deferred, genuinely
  map-matching-dependent feature. Nothing about this doc changes that;
  don't let "we're already building an elevation chart" become a reason
  to quietly fold that harder, still-blocked feature in.
- **Per-point elevation precision matching the source GPX exactly** —
  the downsampled profile is for a readable chart, not a scientific
  record; the aggregate ascent/descent figures (already exact, computed
  separately) remain the authoritative numbers.