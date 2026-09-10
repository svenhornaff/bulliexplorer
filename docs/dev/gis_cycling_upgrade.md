# BulliExplorer — Cycling Map Upgrade

> Extends `maps_gis.md` (the shipped map feature) and `gis_refactor.md` (the
> coverage fix). Two goals: make the basemap itself cycling-aware (not just
> a generic road map with a route line on top), and add a full-screen view.
> Also resolves the open question from `ui_ux_refresh.md`'s deferred
> "interactive elevation profile chart" item — see the Phase 3 fork below.

---

## Research: what "top notch" actually means here, checked against the current field

Reviewed the current leading cycling platforms (Komoot, RideWithGPS,
Strava, Gaia GPS) rather than assumed. One clear, consistent signal:

**Surface-type visualization synced to the elevation profile** — colored
bands on the elevation graph showing exactly where pavement ends and
gravel/dirt/singletrack begins. RideWithGPS added this in 2025
specifically for the bikepacking/gravel touring segment — exactly this
project's niche. Neither Strava nor Garmin Connect has it; it's the
genuine differentiator in this space, not generic polish.

**Honest scoping, upfront**: that feature needs *per-segment surface
data*. Your GPX files (bike-computer recordings) contain only
lat/lon/elevation/time — no surface tags. Komoot/RideWithGPS get this by
*map-matching* the route against their routing engine's tagged road
network — snapping each point of the track to the nearest real-world way
and inheriting that way's `surface` tag. That's a real geospatial
pipeline, not a styling task. Phase 3 below resolves whether a lighter
version is feasible with what's already in the stack, honestly, before
committing either way.

Secondary reference: **CyclOSM**, the established OSM cycling-oriented
render (production since 2019) — color-coded cycleway/lane types,
surface/smoothness indication, bike-relevant POIs (shops, water, shelter
over generic tourism POIs). Used below as a *design* reference, not a
drop-in — its actively-maintained version is a raster tile server, and
its MapLibre vector-style port is explicitly marked unmaintained upstream.

**Third reference, checked directly**: [VeloPlanner](https://veloplanner.com/) —
a cycling route *planner* (not a documentation tool like this project),
with live overlays for campsites/hotels/attractions, surfaces, and road
classes along a route. Confirmed against their own site: **these overlays
are OpenStreetMap-derived, not a proprietary dataset** ("Our routing uses
OpenStreetMap data... Surface data is generally very accurate on major
cycling routes"). Same source this project's basemap already uses — the
gap isn't data access, it's that nothing here queries or renders it yet.

**One architectural distinction worth being deliberate about before
Phase 4**: VeloPlanner is built to help someone find services along a
route they're *planning* — a live tool. BulliExplorer documents routes
already *ridden* — a published blog post. That argues against a live
third-party API call on every page load (new runtime dependency, new
failure mode, slower page loads) and for the same pattern already used
for geocoding: **resolve once, at sync time, store the result.**

---

## Technical foundation — checked against the actual library and tile schema in use

Your current setup (`static/theme.css` / `templates/post.html`) uses
`@protomaps/basemaps`'s `layers()` function, confirmed against its actual
API (not assumed):

```js
layers: basemaps.layers("protomaps", basemaps.namedFlavor(flavor), { lang: "de" })
```

This returns a **plain array of MapLibre style layer objects** — meaning
custom layers can be appended directly:

```js
layers: [
  ...basemaps.layers("protomaps", basemaps.namedFlavor(flavor), { lang: "de" }),
  ...cyclingLayers(flavor),   // new, this project's addition
]
```

No new tile source, no forked style system — this is additive on top of
what already renders today.

**Confirmed good news on the data**: Protomaps' own layer documentation
lists the roads layer's `kind` classification as explicitly including
`cycleway`, `path`, `track`, `bridleway`, and `sidewalk` as distinct,
queryable values — not lumped into a generic "road" bucket. This means
the basic cycling-infrastructure styling in Phase 1 has real data to work
with today, in the Europe extract already in R2, no new tileset needed.

**Genuinely unresolved, needs verification, not assumption**: whether the
OSM `surface` tag (paved/gravel/dirt/etc.) survives into the tiles as a
feature property. Protomaps' docs describe tags as "schemaless — some
keys may only be present in a subset of features," which neither confirms
nor rules this out. Phase 0 checks this directly before any plan depends
on the answer.

---

## Phased implementation plan

### Phase 0 — Discovery: what's actually in the tiles

**Scope**

- [x] Inspected real tile data directly from the Europe extract (not a
  tile-inspector UI — extracted raw tiles with `pmtiles tile`, gunzip'd
  them, and decoded the MVT protobuf with `mapbox-vector-tile` for exact
  per-feature property inspection) at z14 across five real locations:
  Amsterdam and Copenhagen (globally cycleway-dense, strongest test of
  best-case tagging), Freiburg im Breisgau (this project's own home
  region), the Kinzig Valley (already-documented gravel/track terrain,
  a rural proxy for surface tagging), and a rural point near Nordkapp
  (sanity check — came back with no `roads` layer at all, as expected
  for that empty an area).
- [x] Recorded which properties are actually present per feature —
  checked for `surface`, `smoothness`, `cycleway`, `bicycle`, and
  everything else present on the `roads` layer, not just `kind`.

**Done when**

- [x] Concrete, written answer: **`surface` does NOT survive into the
  tiles — confirmed absent.** Zero occurrences of `surface`,
  `smoothness`, `cycleway` (as a lane-type tag), or `bicycle` across all
  five tiles and ~1,100 combined road features, including the rural
  Kinzig Valley sample (7 `track`-classified features there specifically,
  the terrain type most likely to carry a surface tag if any did).
  **This resolves Phase 3's fork toward "stop here, formally"** — real
  surface-synced visualization needs map-matching, not available from
  this tile data.
- [x] Exact `kind` values confirmed present, **and a correction to this
  doc's research section**: `kind` itself only has five broad buckets
  — `major_road`, `minor_road`, `path`, `rail`, `other` — not the
  `cycleway`/`path`/`track`/`bridleway`/`sidewalk` distinction the
  research section expected from Protomaps' docs. That finer
  distinction lives on a **different property**, `kind_detail`, which
  carries the OSM `highway=*` value directly. Filtered under
  `kind == 'path'`, real observed `kind_detail` values include
  `cycleway`, `footway`, `path`, `track`, `sidewalk`, `steps`,
  `pedestrian`, `crossing`, `driveway`, `pier`, `corridor`, `platform`
  — Amsterdam alone had 61 `cycleway`- and 5 `path`-classified features
  in a single z14 tile, real usable density for Phase 1's styling.
  **Phase 1 should filter on `kind_detail`, not `kind`**, when it's
  picked up — this doc's Phase 1 scope text (written before this
  finding) still says `kind`; corrected in that phase's own scope below
  since Phase 1 hasn't started yet, no dangling inconsistency left.

**Testing**

- No automated test, per this phase's own plan — this finding is the
  test. Verified concretely rather than assumed: real archive, real
  decoded protobuf bytes, five real locations chosen specifically to
  stress-test the best case (cycling capitals) and the terrain most
  likely to carry a surface tag (rural gravel), not just the easiest
  case to confirm.

**Left over**

None.

**Summary**

Answered both of Phase 0's open questions with real, decoded tile data
rather than assumption: extracted raw MVT tiles from the Europe extract
with `pmtiles tile`, gunzip'd them, and decoded the protobuf with
`mapbox-vector-tile` across five real locations — two cycling capitals
(Amsterdam, Copenhagen) as the best-case test, this project's own
Freiburg/Black Forest region, the already-documented gravel Kinzig
Valley as a rural surface-tag test, and a rural Nordkapp point as a
sanity check. Found `surface`/`smoothness`/`bicycle` genuinely absent
(zero occurrences across ~1,100 road features) — resolving Phase 3's
fork to "stop, formally." Also found and corrected a real inaccuracy in
this doc's own research section: the fine cycleway/path/track/footway
distinction lives on `kind_detail` (the OSM `highway=*` value), not on
`kind` itself as assumed — `kind` only has five broad buckets. Corrected
Phase 1's scope text to filter on `kind_detail` before Phase 1 starts,
so it doesn't inherit a known-wrong assumption.

**Recommended next steps**

Phase 1 can proceed as scoped, with the `kind_detail` correction already
folded in — no additional discovery needed before starting it. Phase 3
is closed per the fork resolution above; if real surface-synced
elevation profiles are ever picked up, it needs its own concept doc
evaluating map-matching engines (OSRM/Valhalla-style), not a reopening
of this phase. One thing worth flagging for whoever scopes Phase 1's
actual implementation: `kind_detail` values observed here also include
`footway`/`sidewalk`/`steps`/`pedestrian` under `kind == 'path'` —
Phase 1's dashed/dotted "likely unpaved" treatment should make sure it's
matching cycling-relevant values (`cycleway`, `path`, `track`) and not
accidentally styling pedestrian-only infrastructure the same way.

### Phase 1 — Cycling-aware basemap style layers

**Scope**

- [x] New `cyclingLayers(flavor)` function (co-located with
  `routeLineColor(flavor)` in `post.html`'s existing script, same
  pattern) — returns MapLibre layer definitions filtered on
  `kind_detail == 'cycleway'` **(corrected from `kind == 'cycleway'` by
  Phase 0's finding — `kind` only has five broad buckets;
  `kind_detail` carries the OSM `highway=*` value and is where the
  real cycleway/path/track/footway distinction actually lives, filter
  additionally on `kind == 'path'` first since that's the only `kind`
  bucket `kind_detail` in ["cycleway", "path", "track"] falls under)**,
  styled distinctly (CyclOSM-inspired: a saturated, high-contrast color
  against the base road palette, dashed/dotted variant for
  `kind_detail == 'path'`/`'track'` to distinguish unpaved-likely
  routes from dedicated cycleways).
- [x] Both light and dark flavor variants — reuse the existing
  flavor-aware pattern already established for the route line color,
  don't hardcode one theme.
- [x] Phase 0 confirmed `surface` is NOT present — skip the
  paved/unpaved sub-item entirely, not just this phase's version of it;
  see Phase 3's fork below, now resolved to "stop, formally."
- [x] Appended to the existing `basemaps.layers()` array, not replacing
  it — confirmed additive per the technical foundation above (also
  wired into the theme-swap `setStyle()` rebuild, which regenerates the
  full style — `cyclingLayers(nextFlavor)` is called fresh there too,
  so it doesn't need transformStyle carry-over the way the dynamically
  added route/POI layers do).

**Done when**

- [x] Cycleways/paths/tracks render visibly distinct from regular roads,
  verified on real areas with known cycling infrastructure —
  **confirmed by the user in the live browser**, on production, at
  both Köln (Kolner Dom/Deutz — moderate density) and Amsterdam
  (higher density). Cross-checked against real tile data for the
  exact Köln tile shown: 4 real `cycleway` features and 16 `path`
  features present — matching what was visually confirmed, and
  correctly excluding 148 pedestrian/footway/steps/pier/sidewalk
  features from the styling, the specific risk flagged in this
  phase's original scope note. Light-flavor confirmed directly; dark
  flavor not separately screenshotted but uses the same code path and
  filter logic, only the two color constants differ.
- [x] No regression to existing route-line/POI-marker rendering — the
  user's screenshots show the route line and stats panel rendering
  normally alongside the new cycling layers.

**Testing**

- Went further than this phase's own plan anticipated: added two
  automated tests in `tests/unit/test_templates.py`
  (`test_post_with_route_and_tiles_includes_cycling_layers`,
  `test_post_with_route_and_tiles_cycling_layers_use_kind_detail`),
  following the existing string-presence-on-rendered-HTML pattern
  already used for `ROUTE_GEOJSON`/`POIS_GEOJSON` in that file. These
  catch a regression in the *code being present and structurally
  correct* (right function, right filter keys, right layer count) —
  they cannot and do not replace the still-needed manual visual check
  above, which is genuinely browser-only, per this phase's original
  reasoning.

**Left over**

- Dark-flavor visual confirmation specifically — only light flavor was
  screenshotted. Low risk (same code path, same filter logic, only the
  two color constants swap), but not independently confirmed.

**Summary**

Added `cyclingLayers(flavor)` to `post.html`'s existing MapLibre script,
co-located with `routeLineColor(flavor)` in the same pattern. Two new
layers on the `"roads"` source-layer: a solid, saturated line for
`kind_detail == "cycleway"`, a dashed muted line for `kind_detail` in
`["path", "track"]` (both gated on `kind == "path"` first, since that's
the only `kind` bucket those `kind_detail` values fall under) — using
the corrected property from Phase 0's finding, not the doc's original
`kind`-only assumption. Both flavor-aware (separate light/dark color
pairs, chosen to sit distinctly apart from the existing route-line
accent color so the two don't get confused). Appended via `.concat()`
in both places the base style gets built — initial load and the
theme-swap `setStyle()` rebuild — not replacing `basemaps.layers()`'s
own array. Added two automated tests beyond what this phase's plan
called for, verifying the code is present and structurally correct on a
real rendered page; also verified directly against real production
HTML (not just tests) that the rendered `<script>` block is syntactically
valid JavaScript.

**Recommended next steps**

Phase 1 is now fully confirmed working in production — Phase 2 (the
full-screen modal) can start without any further prerequisite here.
One thing worth carrying forward, discovered during this confirmation
rather than planned for: cycleway/path tile data has genuinely uneven
density by location (Köln: 4 cycleway + 16 path features in one z14
tile; a Rhine-valley stretch a few km away: as few as 0-1 per tile;
Amsterdam: 61+). This isn't a bug, but worth knowing when eyeballing
any future map-styling change — an empty-looking tile doesn't
necessarily mean broken styling, it can just mean OSM's cycling
infrastructure tagging is sparse in that specific spot. Nothing found
here changes Phase 2's plan — the modal wraps the *existing* map
instance via `map.resize()`, and `cyclingLayers()` is already part of
the base style, so it comes along for free with no extra wiring.

### Phase 2 — Full-screen map modal

**Scope**

- [x] Expand icon overlaid on the map's corner — a simple
  absolutely-positioned button (top-left, clear of MapLibre's own
  `NavigationControl`/`AttributionControl`/`ScaleControl`, which occupy
  the other three corners). Matches the existing `.theme-toggle` button
  chrome exactly (`--color-border`/`--color-surface`/`--color-text`
  tokens, same border/radius pattern), and the existing icon macro
  convention in `partials/icons.html` (hand-authored 24x24 stroke SVGs,
  `icon_expand`/`icon_collapse`).
- [x] Clicking it toggles a `position: fixed` class on the wrapper and
  calls `map.resize()` — the **same** MapLibre instance the whole time,
  never re-initialized.
- [x] Escape key and the same visible toggle button (relabeled/re-iconed
  via `aria-pressed`) both dismiss it, again via `map.resize()`.
- [x] Focus trap (Tab-only, cycling the wrap's own focusable elements)
  while open, plus `role="dialog"`/`aria-modal="true"` set via JS only
  while the overlay is actually active.

**Done when**

- [x] Expanding and collapsing preserves pan/zoom/route-fit exactly —
  the SAME map instance is never torn down or re-created, only
  `resize()`d, so there is no state to lose in the first place. Verified
  structurally (single `map` instance referenced throughout, `resize()`
  is the only method called on toggle) and via the same real-rendered-
  output check used for every prior phase — not yet eyeballed in an
  actual browser.
- [x] Keyboard-only pass — confirmed by user UAT: expand button in
  place and working, Tab/Shift+Tab/Escape behave as implemented.
- [x] Screen-reader pass — confirmed by user UAT alongside the
  keyboard pass.

**Testing**

- Two new integration tests in `test_post_map_integration.py`
  confirming the toggle button, its wrapping element, and the required
  ARIA attributes (`aria-pressed="false"`, `aria-controls="post-map"`)
  render, and that the toggle button precedes `#post-map` in the DOM
  (so the focus trap's first-element ordering actually lands on the
  close control, not somewhere inside the map).
- Real-rendered-output check, same method used every prior phase: the
  actual production HTML for `dream-of-north` (Jinja placeholders
  already substituted with real GeoJSON, not a synthetic approximation)
  extracts to syntactically valid JavaScript via `node --check`, with
  `openFullscreen`/`closeFullscreen`/`getFocusable` and the toggle's DOM
  id each present exactly once.
- Manual keyboard-only and screen-reader passes still needed — no
  automated equivalent for this class of interaction, per this phase's
  own original plan.

**Left over**

None — both manual passes (keyboard-only, screen reader) confirmed via
user UAT.

**Summary**

Added a full-screen toggle to the existing map (not a second modal/map
instance) via `#map-wrap`/`#map-fullscreen-toggle` in
`partials/route_stats.html`, two new icon macros
(`icon_expand`/`icon_collapse`), and a `position: fixed` CSS toggle plus
`map.resize()` call in `post.html`'s existing MapLibre script. A
keydown listener traps Tab within the wrap's focusable elements and
dismisses on Escape, restoring focus to the toggle button either way.
Also found and removed an unrelated pre-existing dead/buggy helper
(`_make_app` in `test_post_map_integration.py`, never called, with a
genuine `tiles_url = tiles_url` self-reference bug) while touching that
file.

**Recommended next steps**

Before Phase 3/4 work, the two left-over manual passes above should get
a real look — quick (open a post with a route, click the expand button,
try Tab/Shift+Tab and Escape, then a VoiceOver/NVDA pass). Nothing found
in this phase changes Phase 3's already-closed fork or Phase 4's plan;
Phase 4's own map-rendering pieces (if any use the map at all) would
inherit this toggle for free, same reasoning as Phase 1's carry-forward
note.

### Phase 3 — Surface-type visualization: fork on Phase 0's finding

**Resolved by Phase 0: `surface` tags are confirmed absent** — zero
occurrences across five real locations (including a rural gravel/track
sample specifically chosen to give this the best chance of a hit) and
~1,100 combined road features. **This fork stops here, formally**, per
the plan already written below for this outcome. Not revisited or
second-guessed in this phase — Phase 0's finding is concrete enough to
act on directly, not just "likely" as originally framed.

~~**If Phase 0 found `surface` tags are NOT reliably present in the
tiles**~~ (the likely outcome, given Protomaps' own "some keys may only be
present in a subset of features" caveat): **stop here, formally.** Real
surface-synced elevation profiles need map-matching against a properly
surface-tagged road network — a genuine geospatial project (evaluate
existing OSS routing/map-matching services, likely a paid or
self-hosted OSRM/Valhalla-style engine), not a styling task. Document
this as its own future concept doc if it's ever picked up — don't let it
quietly become scope inside this one.

~~**If Phase 0 found `surface` tags ARE present for a meaningful share of
features**: a narrower, honestly-scoped version becomes feasible without
map-matching~~ — not this project's outcome; kept below only as the
record of what the other branch would have looked like.

**Scope** (not applicable — Phase 0 resolved the fork the other way)

- [ ] Extend `cyclingLayers()` (Phase 1) to color-code paths/cycleways
  by `surface` value where present (paved vs. unpaved distinction, not
  a full gravel/dirt/singletrack gradient — that level of nuance likely
  isn't reliably tagged at the basemap-tile level).
- [ ] This colors the *surrounding map*, not the *route line itself* —
  a real surface-synced elevation profile (the actual Komoot/RideWithGPS
  feature) would still require matching the specific GPX track against
  this data point-by-point, which is out of scope even in this
  fork — that remains a genuinely separate, larger feature.

**Done when / Testing**: only defined once the fork is resolved and this
sub-scope is actually picked up — not written speculatively here.

---

### Phase 4 — Auto-discovered nearby amenities (campsites, shelters, water, fuel)

**Scope**

- [x] Add `shelter` to the `category` select options in `config.yml`.
- [x] New model, **`NearbyAmenity`** (`app/models/nearby_amenity.py`),
  distinct from `PointOfInterest`. Tied to `route_id` via
  `ondelete="CASCADE"`, unique on `(route_id, osm_element_type,
  osm_element_id)` (OSM ids are only unique *within* their element
  type). GiST spatial index auto-created by GeoAlchemy2 at
  table-creation time — alembic's own autogenerated `op.create_index`
  for it was a duplicate that collided ("relation already exists");
  removed, matching the existing `points_of_interest` migration's
  precedent.
- [x] Overpass query (`app/services/overpass.py`, framework-free) in
  `sync_route`'s path. **Changed from this section's original plan
  mid-implementation**, after a real scope gap surfaced: a single
  whole-route bbox is fine for a local ride, but this project's own
  "Dream of North" spans ~4,200 km / half of Scandinavia — one bbox
  over that envelope would be slow, likely violate Overpass's fair-use
  policy, and return amenities scattered across a huge irrelevant
  area. Asked the user how to handle it (three options: cap+skip large
  routes, tile now, or no cap); **tiling now** was chosen. Implemented
  as chunking by **contiguous point index**, not a uniform grid over
  the bbox — consecutive GPX points stay geographically local to each
  other even when the route's overall span is huge, so this naturally
  follows the actual path and bounds the query count
  (`_MAX_AMENITY_QUERIES = 30`) regardless of route length. Routes
  below `_SINGLE_QUERY_MAX_SPAN_DEG` (~111 km) still get exactly one
  query — covers this project's actual local rides (Kinzig Valley,
  Sunday Gravel Loop) trivially.
- [x] Overpass usage policy: identifying `User-Agent`, same 1 req/s
  discipline as Nominatim (independent clock — a different remote
  service). Best-effort snapshot-replace semantics: queries Overpass
  **before** touching the DB; any chunk failing preserves the existing
  snapshot rather than replacing it with a partial answer; a `remark`
  field in an otherwise-200 response (Overpass's own way of flagging a
  server-side timeout/resource limit) is treated the same as a hard
  failure, not trusted as complete.
- [x] Rendering: muted (9px, 65% opacity, no drop shadow — vs. curated
  POIs' 14px/full-opacity/drop-shadow) plain DOM markers, same
  `maplibregl.Marker` approach as curated POIs (not a MapLibre GeoJSON
  source/layer) — deliberately, since DOM markers already survive a
  theme `setStyle()` swap for free, avoiding the "carry layers across
  setStyle" complexity the route line/casing needs. "Show nearby
  services" checkbox defaults unchecked; created but not added to the
  map until toggled on; the whole toggle control is omitted from the
  page entirely (not just hidden) when the amenity collection is empty.
- [x] `enable_amenity_discovery` **added, not in the original plan**:
  a `Settings` flag (`app/core/config.py`), off by default, threaded
  through `sync_posts()` → `sync_route()`. Necessary because an
  unconditional Overpass call on every route sync would have made
  *every one* of the 8 existing route-sync integration tests hit the
  real network, and made every production sync depend on Overpass's
  uptime. With the flag off by default, zero of the ~25 existing
  `sync_posts()` call sites (across `app/main.py`, `app/routes/
  internal.py`, and every existing test) needed to change at all.

**Done when**

- [ ] Syncing a real route populates `NearbyAmenity` rows for at least
  campsites and fuel stations — **attempted for real against the live
  Overpass API** (not mocked) for Kinzig Valley Loop, from this
  session's sandbox. Got a `httpx.ReadTimeout` on one attempt and an
  immediate `406 Not Acceptable` from Overpass's own Apache/WAF layer
  on a follow-up — signs of bot-protection/rate-limiting against this
  environment's network, not a bug in the query itself (the resilience
  path handled both failures correctly: logged clearly, zero rows
  written, nothing crashed). Retrying repeatedly against a public
  service already showing signs of blocking automated traffic isn't
  appropriate, so this is left for a real deploy/browser environment to
  confirm. What *is* verified: the full round-trip with a realistic
  mocked Overpass response (integration test), including a real node
  with `center`-style way coordinates parsed correctly.
- [ ] Toggling the overlay on/off in the browser — needs a real
  browser, not verified here. Implemented and traced through by hand:
  checkbox `change` listener calls `.addTo(map)`/`.remove()` per
  stored marker, curated POI markers are a completely separate array
  never touched by this listener.
- [x] Re-syncing the same route doesn't duplicate rows — verified via
  `test_amenity_discovery_resync_replaces_snapshot_not_duplicates`
  (two syncs, same mocked response, exactly one row after both).

**Left over**

- Confirming a real Overpass query finds real known amenities near a
  real route — blocked by this session's sandbox network showing signs
  of bot-protection against the public Overpass endpoint (see above).
  Needs re-attempting from a real deploy or your own machine with
  `ENABLE_AMENITY_DISCOVERY=true` set temporarily.
- The browser toggle check — needs a real browser, same as every prior
  phase's manual UI passes.

**Summary**

Built `NearbyAmenity` (own table, `route_id`-scoped, distinct from
curated `PointOfInterest`) and `app/services/overpass.py` (framework-
free Overpass client, best-effort/snapshot-replace semantics). Wired
into `sync_route()` behind a new `enable_amenity_discovery` flag
(`Settings`, off by default) so none of the ~25 existing `sync_posts()`
callers/tests needed any change. Replaced the plan's single-bbox v1
design with point-index-contiguous chunking after discovering "Dream of
North" (~4,200 km) would otherwise mean one query over half of
Scandinavia — a real gap the original plan didn't anticipate, resolved
by asking rather than guessing. Rendering reuses the exact DOM-marker
pattern curated POIs already use (muted/smaller), avoiding any new
style-layer complexity. 14 new tests (unit: bbox chunking + Overpass
parsing/failure modes; integration: DB round-trip, idempotency,
default-off behavior) plus a config fix (missing `shelter` marker
color, found while touching the file) and a real migration bug
(GeoAlchemy2's auto-created spatial index colliding with alembic's own
redundant `op.create_index`) caught and fixed before it ever shipped.

**Recommended next steps**

- Phase 4 is functionally complete and safe to leave off
  (`enable_amenity_discovery` defaults false) until the two left-over
  browser/network checks are done — there's no rush, and turning it on
  is a one-line env var change whenever ready.
- When you do turn it on for real: start with one local route (Kinzig
  Valley), not "Dream of North" — confirms the single-bbox path works
  against the real API before the 30-chunk path runs.
- No further plan changes needed for this doc's remaining sections —
  the "Explicitly deferred" list below already correctly anticipated
  "Precise corridor search" as a v1 simplification, which is what got
  built (chunked-but-still-bbox, not a true along-track corridor).

**Testing**

- Unit (`tests/unit/test_overpass.py`, 13 tests): query building
  (bbox order, tag coverage), element parsing (node/way-center,
  unmapped tags, missing/malformed coordinates, missing name), and
  every failure mode (network error, HTTP error, a `remark`-carrying
  200) — all via mocked `httpx` transports, matching this project's
  existing Nominatim test pattern, no real network call.
- Unit (`tests/unit/test_geo_sync.py`, 5 new tests): `_buffered_bbox`'s
  bbox order, single-bbox-for-short-routes, chunking-for-long-routes,
  the hard cap holding regardless of point count, and chunks staying
  geographically local even when the overall route span is huge.
- Integration (`tests/integration/test_geo_sync_integration.py`, 3 new
  tests): the full DB round-trip with a mocked-but-realistic Overpass
  response, default-off behavior (a mock that asserts it's never even
  called), and resync idempotency. All 8 pre-existing tests in this
  file pass completely unchanged (0.68s, confirmed no real network
  calls) — direct proof the opt-in-default-off design doesn't disturb
  anything already there.

---

### Phase 5 — Overpass mirror fallback

**Why now, not "later"**: the cooldown fix (Phase 4 follow-up, already
shipped) correctly addressed *our own* burst-request risk. It doesn't
address the separate, now-observed-directly problem that
`overpass-api.de` — a free, shared, best-effort public instance with no
uptime guarantee — is itself unreliable independent of anything this
project does. Confirmed directly, not assumed: a plain `curl` against it
returned a real `504` with the server's own message *"probably too busy
to handle your request,"* and three chunk queries in one sync batch
failed together within an 11-second window — a whole-instance bad
moment, not isolated flukes. Current (2026) practitioner guidance on
Overpass reliability converges on exactly this pattern: *"use mirrors as
the default, keep the primary as fallback... move to local infrastructure
only once usage is regular enough to justify it"* — mirror fallback is
the appropriately-sized fix for where this project actually is, not an
overreaction.

**Scope**
- [x] Add a fallback mirror: `https://overpass.kumi.systems/api/interpreter`
  — confirmed as a well-established, actively-used, globally-covering
  mirror (referenced consistently across sources from 2017 through
  2026, including current 2026 reliability guidance), not a guess.
- [x] **Per-sync failover, not per-chunk retry-both-every-time**: matches
  the observed failure shape (when the primary has a bad moment, it's
  bad for the *whole batch*, not one request). On a chunk's query
  failing against the primary, retry that same chunk once against the
  mirror before giving up on it — **and** remember the primary failed
  for the rest of *this* sync run, routing subsequent chunks straight
  to the mirror first rather than wasting a round-trip re-proving the
  primary is still down.
- [x] Rate-limiting stays global across both instances combined, not
  additive per-mirror — `_MIN_OVERPASS_INTERVAL` continues to pace
  *any* outbound Overpass request regardless of which instance it's
  going to. Doubling effective query rate just because a second
  hostname is available would defeat the whole point of being a good
  citizen toward shared public infrastructure. **Extra, beyond the
  original plan**: a second, smaller pacing gap
  (`_INTER_INSTANCE_RETRY_DELAY_S`, 1s) inside a single chunk query
  itself, between a failed primary attempt and the mirror retry —
  closes a gap the plan didn't call out: `_MIN_OVERPASS_INTERVAL` only
  paces *between* chunk calls, so without this a fallback event inside
  one chunk's call would fire two Overpass-bound requests back-to-back
  with zero pacing between them.
- [x] Log which instance actually served each successful response (not
  just failures) — makes it possible to see from logs alone how often
  the fallback is actually being used, informing whether this is enough
  or whether self-hosting eventually becomes worth it.

**Done when**
- [x] A fixture test simulating a primary failure + mirror success confirms
  the chunk's data is still captured, not lost.
- [x] A fixture test confirms a mid-sync primary failure routes *remaining*
  chunks straight to the mirror, not back through a known-bad primary
  first.
- [x] A fixture test confirms rate-limiting still applies across both
  instances combined — no burst just because two hostnames exist.
- [ ] Live: trigger a real sync during a moment the primary is
  slow/erroring and confirm the mirror actually serves the data, logged
  clearly — **not verified**. The two real production incidents this
  phase was written in response to (an outright connection refusal,
  then a `504`) both happened organically, not on demand; deliberately
  not re-provoking either against the live public instance a third
  time just to force this check. Confirmed everything one level down
  instead: the exact failure shapes from those two incidents
  (`ConnectError`, a `remark`-carrying `504`-equivalent) are reproduced
  as fixtures and correctly trigger the fallback in the test suite.

**Testing**
- Unit tests in `tests/unit/test_overpass.py`: mocked primary failure +
  mirror success (data captured, confirmed via `result_meta`), mocked
  primary failure + mirror also failing (correctly returns `None`, same
  graceful-degradation contract as today), `start_index` actually
  changes which instance is tried first (the mechanism the sticky
  failover relies on), and the pacing gap firing on a fallback but never
  on a healthy primary — 8 new tests total, none needing a real sleep
  (pacing verified via a mocked `asyncio.sleep`, consistent with how
  this project doesn't test rate-limit *timing* directly anywhere else).
- Existing `tests/integration/test_geo_sync_integration.py` amenity
  tests re-verified passing unchanged against the new sticky-failover
  wiring in `sync_amenities` — confirms the plumbing change didn't
  regress the already-shipped Phase 4 behavior.

**Left over**

- The one live-sync "Done when" check above — needs the primary to
  organically be having a bad moment again, which isn't something to
  force against a shared public service. The next time it happens
  naturally (and it will — confirmed twice already), the deploy's own
  logs will show it: `Overpass (https://overpass.kumi.systems/...)
  returned N amenities` instead of the primary's URL.

**Summary**

- Added a fallback mirror (`overpass.kumi.systems`) to
  `app/services/overpass.py`: on a primary failure (network error, HTTP
  error, or a `remark`-carrying partial response), retries once against
  the mirror before giving up, with a 1s pacing gap between the two
  attempts so a fallback event never fires two Overpass-bound requests
  back-to-back.
- Made the failover sticky per sync run: `query_nearby_amenities` gained
  `start_index`/`result_meta` parameters: `geo_sync.py`'s
  `sync_amenities` tracks which instance last actually served a chunk
  and starts the *next* chunk there — once the mirror serves once,
  remaining chunks in that sync try the mirror first, never re-proving
  a known-bad primary is still down. Resets to the primary on the next
  sync run (a local variable, not persisted state).
- This closed a real gap between what had already been proposed to the
  user (a simpler "retry once, no memory across chunks" design) and
  this doc's own more thorough plan already drafted in the working
  tree — caught and reconciled before calling the phase done, rather
  than shipping the weaker of the two designs.
- 8 new unit tests, all mocked (no real network, no real sleeps);
  4 existing Phase 4 integration tests re-verified passing against the
  new wiring, confirming no regression.
- `make ci` green throughout: 253 tests, 92.86% coverage.

**Recommended next steps**

- Nothing currently blocks; this closes the Overpass-reliability gap
  this phase set out to close. The only thing left is passive
  observation — watch production logs for `Overpass (mirror-url)` lines
  over the coming weeks to see how often the fallback actually fires,
  which is the concrete signal for whether self-hosting an Overpass
  instance (explicitly deferred below) ever becomes worth the added
  infrastructure.
- If the mirror itself is ever observed failing too (both instances
  down in the same window), that's the point to reconsider — right
  now this is genuinely unverified in practice, only in fixtures.

---

## Explicitly deferred, regardless of Phase 3's fork or Phase 4

- **Full route-level surface-synced elevation profile chart** (the
  actual Komoot/RideWithGPS-grade feature) — needs map-matching, a real
  geospatial project. Resolves `ui_ux_refresh.md`'s deferred "interactive
  elevation profile chart" item by making explicit *why* it's still
  deferred: not just "a chart is more work than a stats row" (the
  original reasoning) but "the surface-sync version specifically needs
  infrastructure this project doesn't have yet."
- **CyclOSM-style bike-specific POI icons** for Phase 1's basemap
  cycleway layers specifically (distinct from Phase 4's amenity markers,
  which already get their own icon treatment) — cheap to add later,
  not blocking either phase.
- **Precise corridor search** for Phase 4 (along-the-track buffer
  instead of bounding-box) — real refinement, not needed for a useful
  v1.
- **Live/on-demand Overpass queries** (re-querying as a reader pans the
  map, VeloPlanner-style) — deliberately rejected per the research
  section's reasoning: this is a documentation tool, not a planner: a
  live third-party dependency on every map interaction isn't worth it
  for content that doesn't change once published.
- **A custom/enriched tileset** (building your own Planetiler-based
  tiles with guaranteed surface tags, rather than relying on what
  Protomaps' general-purpose extract happens to include) — real
  infrastructure, only worth it if Phase 3's fork lands on "not
  present" and the surface feature is later judged worth the investment
  anyway.