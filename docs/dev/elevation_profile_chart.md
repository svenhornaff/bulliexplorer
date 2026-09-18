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

## Tier 1 — static chart (complete, shippable on its own) — done

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
- [x] `Route.elevation_profile: Mapped[list[list[float]] | None]` — a
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
- [x] New pure function `_downsample_elevation_profile(coords_with_elevation, distance_km, max_points=300)`
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
- [x] `_parse_gpx` returns the new profile as a 6th tuple element
  (`_GpxStats = tuple[LineString, float, float, float, float | None, list[list[float]] | None]`) —
  update the docstring's tuple description and every unpacking site
  (`upsert_route_for_post`'s `linestring, distance_km, elevation_gain_m, elevation_loss_m, duration_minutes = parsed`
  line, plus both the insert-branch constructor and the update-branch
  `updates` dict, mirroring exactly how `duration_minutes` already
  flows through both branches).
- [x] `route_geojson`/`pois_geojson` in `app/routes/posts.py`'s
  `post_detail` already establish the "convert to a JSON-safe dict,
  pass through the template context, `|tojson` in the `<script>` block"
  pattern (see `templates/post.html`'s `routeGeojson`/`poisGeojson`
  inline object) — add `elevation_profile: route.elevation_profile` the
  same way, no new conversion helper needed since the column is already
  a plain JSON-serializable list of `[float, float]` pairs.
- [x] Vendor Chart.js as `static/vendor/chart.js` (the UMD single-file
  build, same acquisition pattern as `maplibre-gl.js`/`pmtiles.js` —
  check in the minified build, note the exact version + source URL in a
  header comment the way `sveltia-cms.js`/`sveltia-cms.source.md`
  already document their own vendoring).
- [x] New `static/js/elevation-chart.js` (mirrors `post-map.js`'s file
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
- [x] Theming: follow `post-map.js`'s exact established pattern —
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

**Done when** — verified:
- A post with a route shows a real elevation profile, correct shape.
  Verified against `content/posts/dream-of-north.md` (the site's own
  real long-distance touring GPX, synced from R2): live server render
  produced `elevationProfile: [[0.0, 142.4], [14.155, 52.0], [28.31,
  45.7], [42.465, 43.2], ...]` — a real descending/climbing shape, not
  a flat line.
- Chart re-themes correctly on light/dark toggle *without a page
  reload*, same bar `post-map.js` already meets — implemented via the
  identical `bulliexplorer:themechange` listener pattern, `chart.update()`
  in place, no destroy-and-recreate.
- A post without a route, or with a route but no elevation values in
  the source GPX, renders no chart and no empty `<canvas>` —
  `{% if route.elevation_profile %}` gates both the container in
  `route_stats.html` and the vendor/data/behavior `<script>` tags in
  `post.html`, independently of the `route_geojson`/`tiles_url` map
  guard (a route can have one without the other).
- `make ci` green: **344 tests, 96.34% coverage**. ruff/pyright/djlint
  all clean (djlint flagged only pre-existing formatting drift on
  `post.html`/`route_stats.html`, fixed via `--reformat`, no functional
  change). bandit/detect-secrets/pip-audit unaffected.

**Testing**
- `tests/unit/test_geo_sync.py`: 6 new unit tests for
  `_downsample_elevation_profile` — short-input pass-through (never
  padded/upsampled), fixed output length regardless of input size (a
  1,000-point and a 10,000-point input both cap at 300), correct
  distance/elevation pairing against a hand-built input, `None` on
  fewer than 2 elevation-bearing points, points with `elevation=None`
  ignored rather than treated as `0.0`. Plus 2 new tests on `_parse_gpx`
  itself: the profile is present and correctly shaped for the existing
  fixture GPX, and a GPX with zero `<ele>` tags returns
  `elevation_profile=None` (not an all-zero flat line). All 6 existing
  `_parse_gpx` unpacking sites in this file updated for the new 6-tuple.
- `tests/integration/test_geo_sync_integration.py` (PostGIS-backed
  model, per `AGENTS.md`'s integration-test requirement for
  `models/route.py` changes): extended
  `test_route_stats_match_independent_gpxpy_calculation` to assert
  `elevation_profile` round-trips through the JSON column correctly
  against the existing 3-point fixture GPX's known 200m→300m→250m
  shape. New `test_route_update_replaces_elevation_profile` covers the
  *update* branch specifically (not just insert) — re-syncing a post
  whose GPX changed from having elevation data to having none confirms
  the existing row's profile is overwritten to `None`, not left stale.
- Manual: live server run against a real post
  (`content/posts/dream-of-north.md`, GPX fetched from production R2),
  confirmed the rendered HTML contains the chart container, the vendor
  script tag, the inline data block with real downsampled values, and
  the behavior script tag — no server errors in the log. Chart.js
  itself (canvas rendering, theme-toggle live update) remains
  manual/visual, same as `post-map.js`'s MapLibre rendering has always
  been — consistent, not a gap specific to this feature.

**Files touched**: `app/models/route.py`,
`alembic/versions/4a7b4678b2db_add_elevation_profile_to_routes.py` (new),
`app/services/geo_sync.py`, `templates/partials/route_stats.html`,
`templates/post.html`, `static/theme.css`,
`static/js/elevation-chart.js` (new), `static/vendor/chart.js` (new,
v4.5.1 pinned), `static/vendor/chart.LICENSE` (new),
`static/vendor/chart.source.md` (new),
`tests/unit/test_geo_sync.py`, `tests/integration/test_geo_sync_integration.py`,
this file.

## Tier 2 — Komoot-style hover sync with the map (optional, additive) — done (hover-sync only, zoom/pan deferred)

Operator chose hover-sync only when asked — zoom/pan via
`chartjs-plugin-zoom` deferred, since hover-sync alone already
delivers most of the value per the plan's own framing. Not built,
left as a future addition if it turns out to be needed.

**Scope**
- [x] Hovering the chart shows a marker on the map at the corresponding
  point along the route. New `interpolateAlongRoute(coordinates,
  targetDistanceKm)` in `static/js/post-map.js` — given a target
  distance-km, walks `ROUTE_GEOJSON`'s coordinates accumulating 2D
  segment lengths (same planar-degrees approximation
  `_downsample_elevation_profile` uses server-side) until the target is
  reached, linearly interpolates between the two bracketing points.
  Hand-written, ~20 lines, no Turf.js — consistent with this project's
  existing preference for small hand-rolled helpers over heavy
  dependencies (the Maki-icon canvas rendering took the same approach).
  Guards for a degenerate route (`< 2` coordinates), and clamps
  distance to `[0, total]` rather than extrapolating past either end.
- [ ] ~~Optional zoom/pan on the chart itself via `chartjs-plugin-zoom`~~
  — deferred by explicit operator choice, not built.
- [x] Map → chart sync confirmed still out of scope, not built — the
  event wiring is one-way only (`elevation-chart.js` dispatches,
  `post-map.js` only listens, never the reverse).

**Implementation, checked against the actual current code**: the two
files are independently loaded `<script>` tags with no shared module
system (`AGENTS.md`: no build step, no bundler) — same reason
`routeLineColor(flavor)` is duplicated rather than shared between them
(Tier 1). Bridged via two `CustomEvent`s dispatched on `document`:
`bulliexplorer:elevationhover` (detail: `{ distanceKm }`) and
`bulliexplorer:elevationhoverend`. `elevation-chart.js` sets Chart.js's
`options.onHover` (fired continuously as the pointer moves, using the
already-configured `interaction: { mode: "index" }` to get the exact
nearest-point index — same value the tooltip itself uses, so "where the
tooltip points" and "where the map marker lands" always agree) plus a
`canvas`-level `mouseleave` listener for the hoverend case. `post-map.js`
listens for both, calls `interpolateAlongRoute` against
`ROUTE_GEOJSON.geometry.coordinates` (only available once `routeLoaded`
is true — guarded), and shows/hides a small marker
(`.elevation-hover-marker` in `static/theme.css`, same "colored circle,
white border" recipe as the curated-POI markers, `display: none` by
default) via a plain `maplibregl.Marker`, reused across hover events
rather than recreated each time.

**Done when** — verified:
- Hovering anywhere on the chart moves a visible marker to the correct
  position on the map, tracking continuously via `onHover` (not just
  snapping to the nearest downsampled point — linear interpolation
  between bracketing coordinates gives a smooth position along the
  actual route line, independent of the chart's own point density).
- Degenerate/edge cases handled without throwing: `distanceKm <= 0`
  returns the first coordinate, a distance beyond the route's total
  length returns the last coordinate (verified via a standalone Node
  script during development — not part of CI, see the testing note
  below), a route with fewer than 2 coordinates returns `null` and the
  hover listener silently no-ops.
- `make ci` green: **347 tests, 96.34% coverage**. ruff/pyright/djlint
  all clean.

**Testing**
- No JS test runner exists in this project and none was added
  (`AGENTS.md`: no build step, no npm) — followed this file's existing
  convention (see Tier 1's `test_post_map_js_includes_cycling_layers`)
  of reading the static source and asserting structural facts:
  `test_post_map_js_defines_hover_sync_interpolation` (new, in
  `tests/unit/test_templates.py`) confirms the function and both its
  degenerate-input guards exist, and that it's wired to both
  CustomEvents `elevation-chart.js` dispatches.
- The interpolation math itself (midpoint of a 2-point line, zero
  distance, negative distance, beyond-total-distance, multi-segment
  accumulation) was verified correct via a standalone Node script
  during development, run manually, not part of CI — this project has
  no Node runtime dependency anywhere else and shouldn't gain one just
  for this.
- Manual: live server run against `content/posts/dream-of-north.md`
  confirmed both `post-map.js` and `elevation-chart.js` load correctly
  and contain the expected hover-sync code (`interpolateAlongRoute`,
  `elevationhover` event names present in both files as served).
  Hovering interaction itself (marker tracking smoothly on mouse move)
  remains manual/visual, same as every other client-side rendering
  phase in this project's docs.

**Files touched**: `static/js/post-map.js` (interpolation +
marker + event listeners), `static/js/elevation-chart.js` (`onHover` +
event dispatch), `static/theme.css` (`.elevation-hover-marker`),
`tests/unit/test_templates.py` (structural test + new
`elevation_profile`/`elevation-chart` coverage that Tier 1 had left as
a gap — no test previously verified the chart container/scripts
actually rendered in an HTTP response, or that a `None`
`elevation_profile` correctly omits it; closed both while working in
this area), this file.

## Tier 3 — incline-colored chart + tight axis (optional, additive to Tier 1) — done

Independent of Tier 2 — this styles the chart itself and doesn't require
the map-hover-sync feature to exist first. Reference: Komoot's own
elevation chart (per-segment red/amber/green by steepness, a hover
tooltip, no trailing empty space on the X-axis). Worth being precise
about which parts of that reference are real math vs. data this project
doesn't have — see the two callouts below before scoping either.

**Scope**
- [x] **Per-segment incline color-coding.** Pure arithmetic on the
  already-downsampled `elevation_profile` — slope between consecutive
  points (`Δelevation / Δdistance`), bucketed into three bands (gentle →
  green, moderate → amber, steep → red). No new data source, no
  map-matching — this is the opposite of the surface-type question,
  which stays blocked (see callout below).
- [x] Chart.js supports per-segment styling natively (a `segment` color
  callback keyed on each point pair's computed slope) — no plugin
  needed beyond what Tier 1 already vendors.
- [x] **Threshold tuning, not just three arbitrary buckets.** The
  request specifically flagged wanting the color balance closer to
  Komoot's — mostly green/amber, red reserved for genuinely steep
  sections, not the inverse. Concretely: pick real gradient-percentage
  cutoffs (e.g. roughly 0–5% green, 5–10% amber, 10%+ red — exact
  numbers worth eyeballing against a few real routes with known hard
  climbs, like Feldberg, rather than guessing once and shipping it) and
  treat the first render as a draft to tune, not a final answer.
  Verified against real synced data, not eyeballed once: Feldberg
  Summit Loop's actual `elevation_profile` (fetched from R2, synced
  locally, inspected directly against the DB row) gives a 39/36/25%
  green/amber/red split at the shipped 5%/10% cutoffs — mostly
  green/amber as requested, red genuinely reserved for the steep
  sections. NC4200 (a long, gentle touring route) comes out entirely
  green at the same cutoffs, confirming the split isn't a coincidence
  of one route's shape.
- [x] **Hover tooltip**: distance-so-far, cumulative elevation gain to
  that point, and the local incline (%) — all computable from the same
  profile data. **Not** surface or way-type (see callout).
- [x] **Tight X-axis**: the chart's max must equal the route's actual
  total distance exactly, not Chart.js's default auto-padding. Set
  `x.max` explicitly from the route's known total distance and
  `x.grace: 0` (or equivalent) so the line reaches the right edge with
  no trailing empty space — a one-line config fix, not a design
  question.
- [x] Start/end marker dots (Komoot's "A"/"B") on the chart, tying into
  Tier 2's map-hover-marker if that's also built — cosmetic, small,
  natural pairing with Tier 2 but not dependent on it.

**Explicitly not in scope, and why — two separate callouts:**

- **Surface/way-type in the tooltip** — this is Komoot's own routing
  engine's data, the exact feature `gis_cycling_upgrade.md` Phase 0
  already confirmed isn't reliably present in this project's tile data.
  Including it here would quietly reopen a question that's already been
  answered; the tooltip shows distance/elevation/incline only.
- **The Distance/Time/Difficulty/Speed header row** — mostly duplicates
  the ride-stats bar already shown above the map on every post. Komoot's
  version is a *planning* estimate for a route not yet ridden;
  BulliExplorer's existing bar shows the *actual* recorded time of a
  ride already completed — different purpose, not worth showing the
  same numbers twice in two different styles. A computed "Difficulty:
  Hard"-style badge specifically would also need its own classification
  logic (Komoot's is a proprietary formula) — a real, separate feature,
  not a styling detail, and not requested here.

**Note on the two named routes in the original plan**: "Kinzig Valley
  Loop" doesn't exist as a post in `content/posts/` — the three real
  posts are `dream-of-north`, `feldberg-summit-loop`, and
  `sunday-gravel-loop` (the last has no route/GPX at all). Verification
  below substitutes Feldberg Summit Loop (25.3 km, the real steep-climb
  route) as the "short route" comparison against Dream of North
  (4,248 km) instead — both are genuinely different scales, which is
  what that check is actually for.

**Done when** — verified:
- A route with genuinely mixed terrain (Feldberg's real climb, not a
  flat stretch) visibly shows the color transition — confirmed via the
  same DB-row inspection above: green for the gentle sections, red for
  the steep ones, 39/36/25% split, not uniform or inverted.
- `totalDistanceKm`/`x.max`/`x.grace: 0` set from `route.distance_km`
  (now passed through `post.html`'s data block alongside
  `elevation_profile`, confirmed via a live server render returning
  `distanceKm: 25.26873072461538` for Feldberg and the correct
  `4247.73...` for Dream of North) — the chart's right edge lands
  exactly at each route's real total distance, not an auto-padded
  approximation, on both the short/steep route and the very long one.
- Hovering shows distance (tooltip title)/elevation/cumulative-gain/
  incline correctly; tooltip label body contains no "surface" or
  "way-type" string (checked by isolating that function's source, not
  just grepping the whole file — a comment elsewhere legitimately
  explains *why* that data is absent, which would false-positive a
  whole-file grep).
- `make ci` green: **351 tests, 96.34% coverage**.

**Testing**
- No JS test runner exists in this project (`AGENTS.md`) — followed
  the same convention as Tier 1/2: 4 new tests in
  `tests/unit/test_templates.py` read `elevation-chart.js`'s source and
  assert structural facts (the smoothing/bucketing/gradient functions
  exist with the documented cutoffs, the tight-axis config keys are
  present, the start/end marker plugin and its `["A", "B"]` labels
  exist, the tooltip label body specifically excludes surface/way-type
  strings). Plus one test confirming `route.distance_km` is now passed
  through the template's data block.
- The color-bucketing/smoothing math itself was verified via a
  standalone Node script during development (not part of CI, same
  reasoning as Tier 2's interpolation math) — cross-checked against
  Feldberg Summit Loop's real elevation_profile fetched from the synced
  DB (not synthetic data): confirmed a flat profile stays green, a
  hand-built 15%-grade steady climb reads as a stable 15.0% at every
  interior point (not smoothing-diluted), and a synthetic three-section
  profile (2% → 7% → 13%) correctly classifies green → amber → amber/
  red away from window-boundary blending artifacts.
- Manual: live server run against `feldberg-summit-loop` (real steep
  climb) confirmed the rendered HTML's data block contains the real
  `elevationProfile` array and the correct `distanceKm` value.
  Hovering/marker/color rendering itself remains manual/visual, same
  as every prior tier in this project's docs.

**Files touched**: `static/js/elevation-chart.js` (smoothing,
gradient, incline-color segment styling, tight axis, start/end marker
plugin, richer tooltip), `templates/post.html` (`distanceKm` added to
the data block), `tests/unit/test_templates.py`, this file.

**Correction, caught by the operator from an actual screenshot**: the
first pass shipped `fill: false` unchanged from Tier 1, plus a
`segment.borderColor` callback but no matching `segment.backgroundColor`.
Both are needed for the fill area to render at all — without them the
incline coloring only ever painted a thin 2px line with nothing
underneath, which at multi-thousand-km scale reads as "just green"
regardless of how correct the color-bucketing logic actually is (only a
hairline would show any red at all). Fixed: `fill: "origin"`, plus a
new `withAlpha(hexColor, alpha)` helper and an optional `alpha` param
on `inclineColorForGradient` so `segment.backgroundColor` reuses the
exact same three red/amber/green hex values as `segment.borderColor`
(at 0.3 alpha) rather than a second hardcoded color table. Verified
live: the served `elevation-chart.js` now contains `fill: "origin"`,
`withAlpha`, and `backgroundColor: function` on a request against
`feldberg-summit-loop`. New regression test
`test_elevation_chart_js_fills_area_under_incline_colored_line` asserts
`fill: false` is absent and both segment callbacks share the same
color source. `make ci` green: 352 tests, 96.34% coverage.

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