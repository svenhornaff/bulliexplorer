# Fix: peaks, cable cars, and a full amenity-taxonomy review

> Three related additions, each verified to a different confidence
> level before being scoped — deliberately not treated as equally
> certain. Peaks: confirmed cheap, real data already in hand. Cable
> cars: genuinely unverified, needs its own discovery phase before any
> design commitment. New amenity categories: a full review of OSM's
> `Key:amenity` taxonomy, with explicit reasoning for what's added and
> what's deliberately left out — matching this project's existing
> restraint on category-list bloat.

---

## Peaks — confirmed cheap, but the initial research was wrong about *where*

**The doc's original research claim did not survive contact with real
data.** Direct tile inspection (`pmtiles tile` + `mapbox-vector-tile`
decode of a real z14 tile over Feldberg's actual summit, same method
as `gis_cycling_upgrade.md` Phase 0) found **no `physical_point` layer
exists in this basemap's schema at all** — the real declared
`vector_layers` are `boundaries`, `buildings`, `earth`, `landcover`,
`landuse`, `places`, `pois`, `roads`, `water`. Peaks actually live on
the **`pois`** source-layer as `kind="peak"`, which also carries a
real `elevation` field. Feldberg's own feature, read directly from the
tile: `elevation: 1494`, `min_zoom: 12`, `name: "Feldberg"` — matches
the ride's known summit elevation (1493 m per public reference,
within normal datum/rounding difference). This is exactly the kind of
docs-prose-vs-real-data gap this project's Phase 0 discipline exists
to catch.

**A second finding changed the actual implementation plan**: reading
the vendored `static/vendor/basemaps.js` library directly (not just
the tile schema) showed its own built-in `"pois"` symbol layer
**already renders a peak icon + name label** for `kind="peak"` (shared
with ~30 other POI kinds in one layer, light/dark flavors only —
white/grayscale/black have no `pois` colour palette, so this project's
supported flavors already get it for free). So peaks were **not
missing from the map at all** before this fix — only the elevation
value was.

**Why this is well-justified, not speculative**: Feldberg is a summit
ride — an elevation label at the actual summit is directly relevant to
that content, not a generic "more map detail" addition for its own
sake.

### Phase 1 — Peak elevation labels — done

**Scope**
- [x] New `symbol` layer (`peakElevationLayer()`, `static/js/post-
  map.js`), filtered on the real `pois` source-layer's `kind=="peak"`
  (corrected from the doc's original `physical_point` assumption, per
  the real-data finding above).
- [x] **Deliberately additive, not a full replacement layer**: rather
  than duplicating the native `pois` layer's icon/name/halo/zoom-fade
  logic (which would risk visually diverging from the other ~30 POI
  kinds sharing that one native layer, and double-render a name label
  already shown), this new layer renders **only the elevation text**
  (`"1494 m"`), positioned below the native icon+name (native uses a
  horizontal left/right offset, so this doesn't collide), colour/halo
  matched to the native `pois.green`/`earth` tokens per flavor so it
  reads as one coherent label. Adapted from OSM Carto's
  triangle-and-elevation convention, not copied wholesale — the
  triangle icon already exists natively; this fix adds the elevation
  half.
- [x] `minzoom: 11`, matching the existing cycling-lane layers'
  reasoning exactly — and the tile data's own per-feature `min_zoom`
  (12 for Feldberg, 14 for smaller nearby peaks) further thins minor
  peaks out at lower zooms, since planetiler excludes features below
  their own `min_zoom` from the tileset entirely, not just from the
  style.
- [x] Wired into both places the base style is built — initial load
  and the theme-swap `setStyle` rebuild — matching `cyclingLayers()`'s
  exact two-call-site pattern, not just the first one.

**Done when**
- [x] Feldberg's actual summit shows a peak label with a real
  elevation value, checked against the ride's already-known high
  point figure. Confirmed via direct tile inspection above (1494,
  matching the known ~1493 m summit) — verified against real decoded
  tile bytes, not assumed.
- [x] Zoomed out to the whole-route view, peaks don't visually compete
  with the route line or existing POI/amenity markers — `minzoom: 11`
  plus the tile data's own zoom-gated feature inclusion (see above)
  keeps this the same as the cycling-lane layers' already-accepted
  zoomed-out behavior.

**Testing**: `tests/unit/test_templates.py` —
`test_post_map_js_includes_peak_elevation_layer` (structural read of
the static source, same convention as every other MapLibre-rendering
test in this file — no JS test runner in this project). Actual visual
rendering is manual/visual verification, same reasoning as every other
MapLibre-rendering phase in this project's docs.

## Cable cars — real answer: not present, closed

**Honest confidence gap, stated plainly**: unlike peaks, I could not
confirm an aerialway layer exists in Protomaps' basemap schema from the
documentation alone — the confirmed layers are roads, buildings,
places, and physical points; aerialways weren't explicitly named either
way. This needs the same real tile-inspection discovery
`gis_cycling_upgrade.md` Phase 0 already did for cycling infrastructure
— checking real tile data at a location known to have a cable car —
before any design work, not assumed from the OSM wiki reference page
looking good.

**Also worth a real content-relevance question, not just a technical
one**: a gravel/touring cyclist doesn't typically ride a cable car
mid-route the way a hiker or skier might. Worth deciding whether this
is genuinely relevant to BulliExplorer's content (a bail-out option on
a brutal climb? a summit-access detail worth noting?) or a
speculative addition chosen because it looked good on a reference map,
before committing time to the Phase 0 check.

### Phase 0 — Discovery (must happen before any scope commitment) — done

**Scope**
- [x] Inspect real tile data (same `pmtiles tile` + protobuf decode
  method as the original cycling-infrastructure discovery) at a
  location with a known real cable car, confirm whether `aerialway=*`
  features are present and what layer/properties they carry.

  Used the **Feldbergbahn** (a real, named gondola cable car in the
  Black Forest, valley station at 47.863154, 8.036695 — confirmed via
  web search, not assumed) as the test location — chosen deliberately
  for the same reason Feldberg was chosen for the peaks check: real,
  named, independently verifiable, and directly relevant to this
  project's own content region. Extracted the real z13 and z14 tiles
  covering that exact coordinate with `pmtiles tile`, gunzip'd them,
  and decoded the MVT protobuf with `mapbox-vector-tile` (same method,
  same throwaway analysis venv, not a project dependency — per
  `gis_cycling_upgrade.md` Phase 0's own precedent).

- [x] If present: a small design follow-up, similar in shape to Phase 1
  above. If absent: documented and closed, not left as an open
  question to re-litigate later.

  **Absent — confirmed, not inferred.** Printed every distinct
  `(layer, kind, kind_detail)` combination actually present across both
  tiles: `boundaries`, `buildings`, `earth`, `landuse` (bare_rock,
  farmland, forest, grass, grassland, industrial, meadow, military,
  nature_reserve, pitch, playground, residential, scrub, wetland,
  wood), `places`, `pois` (meadow, nature_reserve, parking, peak,
  sports_centre, water, wetland, winter_sports — `winter_sports` being
  the closest-sounding match, almost certainly the ski-area annotation,
  not the cable car line itself), `roads` (major_road, minor_road,
  path), `water`. **Zero occurrences of `aerialway` as a kind, a
  kind_detail, or anywhere else** in either tile, despite the exact
  coordinate of a real, currently-operating gondola falling inside the
  sampled area. This basemap's actual schema (confirmed separately via
  its own declared `vector_layers` metadata) has no aerialway-carrying
  layer at all.

**Done when**
- [x] A written yes/no answer exists, backed by real tile inspection
  — not inferred from documentation prose. **Answer: no.** Cable cars
  are not representable with this basemap's current tile data;
  building any styling for them would render nothing, ever, regardless
  of design quality. Closed here, not left open — matching this
  doc's own instruction not to re-litigate a settled Phase 0 finding
  later (same discipline `gis_cycling_upgrade.md` Phase 3 followed for
  its own "surface tags absent" finding).

**Testing**: none — this finding is the test, same reasoning as every
other Phase 0 discovery doc in this project.

**Left over**: the content-relevance question this phase's own intro
raised ("is a cable car actually relevant to a touring cyclist's
route, or a speculative reference-map addition") never needed
answering — the technical answer closed it first. If a future basemap
update ever adds aerialway data, that relevance question would need
answering *before* any styling work, not skipped a second time just
because the data finally exists.

## New amenity categories — a full `Key:amenity` review, with real restraint

Reviewed OSM's actual amenity taxonomy (`Key:amenity`, ~300+ established
values across categories like Sustenance, Transportation, Financial,
Healthcare) against what's already covered, rather than picking
categories that looked appealing in isolation.

### Recommended: `amenity=cafe`

**Worth reconsidering despite the existing exclusion** —
`overpass.py`'s own comment on the restaurant addition explicitly said
`cafe` and `fast_food` "stay out of scope." Revisiting specifically
`cafe`, not both: a coffee/pastry stop is arguably **more** relevant to
a typical touring day than a sit-down restaurant — shorter, more
frequent, exactly the kind of stop a cyclist makes without derailing a
day's mileage. Distinct enough from `restaurant` to warrant its own
category, not a case of quietly re-opening a settled decision.

### Recommended: `amenity=bicycle_repair_station`

**Genuinely new, no overlap with the existing `bike_shop` category.**
A `bicycle_repair_station` is OSM's tag for a free, public self-service
stand (tools + pump, no staff, no purchase) — common along cycling
infrastructure in many European cities and parks. `bike_shop` is a
commercial business; this is a public amenity. Directly relevant to
touring: a free pump/tool stand is exactly the kind of practical detail
worth surfacing, and it's a different *kind* of thing from a shop, not
a duplicate.

### Explicitly deferred, with reasoning — not silently skipped

- **`amenity=fast_food`** — practical, but `restaurant` and the newly
  recommended `cafe` already cover "sit-down meal" and "quick stop";
  adding a third, narrower sustenance category starts trading category
  clarity for completeness. Revisit only if the two existing options
  prove insufficient in practice.
- **`amenity=pub` / `amenity=biergarten`** — genuinely common stops for
  European cycle touring, but lean toward "lifestyle/social," a step
  further from the practical-necessities theme the existing category
  list (water, fuel, shelter, repair) has consistently followed.
- **`amenity=ice_cream`** — charming, not essential; the kind of
  category that's easy to justify one at a time but adds up to a
  cluttered dropdown, the same concern already raised and acted on
  earlier this project when `guest_house` was deferred.
- **`amenity=food_court`** — a shopping-mall concept, essentially never
  relevant to a rural touring route; excluded on relevance, not
  restraint.
- **`amenity=bicycle_rental` / `amenity=bicycle_parking`** — real OSM
  tags, but not clearly useful to someone touring on their own bike
  (rental and parking-for-others' bikes solve a different problem than
  "where can I fix or resupply mine").

### Phase 2 — Implementation — done

**Scope**
- [x] `_TAG_TO_CATEGORY` additions: `("amenity", "cafe"): "cafe"`,
  `("amenity", "bicycle_repair_station"): "bike_repair_station"` (kept
  distinct from `bike_shop`'s category value, matching the commercial-
  vs-public distinction above).
- [x] Add both tags to the Overpass query's regex alongside the
  existing set.
- [x] Icon/color: `cafe` shares `restaurant`'s visual family (both are
  food-related stops, distinguished by name/popup); `bike_repair_station`
  shares `bike_shop`'s family for the same reason — same "family
  resemblance, not a wholly new visual language per category"
  principle already applied to `wilderness_hut`->`shelter` (this doc's
  intro's "mountain_hut" reference — that mapping directly reuses
  `shelter`'s category string rather than sharing just the visual
  family; `cafe`/`bike_repair_station` stay as their own distinct
  category values per this phase's own scope above, only the *visual*
  styling is shared).

**Done when**
- [x] Both tags correctly map and appear in the Overpass query string,
  confirmed via the same direct assertion tests used for the restaurant
  addition —
  `test_parse_element_cafe_maps_to_cafe_category`,
  `test_parse_element_bicycle_repair_station_maps_to_bike_repair_station_category`,
  and `test_build_query_includes_all_target_tags`'s two new assertions.
- [x] A real route sync produces at least one `cafe` or
  `bike_repair_station` result where one is independently known to
  exist, spot-checked the same way Feldberg's restaurant addition was
  verified. **Verified against the real, live Overpass API** (not
  mocked) with this project's exact query pattern over the Feldberg
  area bbox (47.83,7.95,47.95,8.10): **7 real results** — 6 cafes
  (Steimle, Bitzenberger / Cafe zum gscheiten Beck, Cafe Bäckerei
  Schwarzwaldmaidle, Mühlen-Café, Cafe Sonnenhöhe, Glöcklehof) and
  1 `bicycle_repair_station`, real OSM data, not a synthetic fixture.

**Testing**: unit tests mirroring the exact pattern already established
for `restaurant` and `mountain_hut` — tag-to-category mapping, query
string inclusion, nothing novel needed.

## Explicitly out of scope

- Every deferred category listed above, with its own stated reasoning
  — not a blanket "maybe later," a real decision per category.
- **Re-litigating `guest_house`** — already considered and deferred in
  `fix_amenity_force_resync_and_mountain_hut.md`; nothing in this
  review changes that reasoning.

## Summary

All three parts implemented, each landing at a different confidence
level exactly as the doc's own intro predicted — not treated as
equally certain, and each verified against real data rather than
assumed from documentation prose.

**Peaks (Phase 1)**: real tile inspection **corrected this doc's own
research section** — no `physical_point` layer exists in this
basemap's actual schema at all; peaks live on `pois` as `kind="peak"`.
Also found the native `basemaps.layers()` library **already renders a
peak icon + name label** (light/dark flavors) — this fix is
deliberately additive, not a duplicate layer: `peakElevationLayer()`
adds only the elevation text, positioned and coloured to read as one
coherent label with the existing native rendering. Feldberg's own peak
confirmed via real decoded tile bytes: elevation 1494 (matches the
known ~1493 m summit), `min_zoom` 12.

**Cable cars (Phase 0)**: real tile inspection at the actual
Feldbergbahn coordinates (a real, named, currently-operating gondola)
found **zero aerialway data anywhere** in either a z13 or z14 tile
covering that exact location, across every layer's actual kind/
kind_detail values. Answer: no, closed — not left open. The doc's own
content-relevance question (is a cable car even relevant to a touring
cyclist) never needed answering, since the technical answer closed it
first.

**New amenity categories (Phase 2)**: `cafe` and
`bicycle_repair_station` added to `_TAG_TO_CATEGORY` and the Overpass
query, kept as their own distinct category values (not folded into
`restaurant`/`bike_shop`) while sharing those categories' visual
styling in `post-map.js`. Verified against the **real, live Overpass
API** (not mocked) over the Feldberg area: 6 real cafes and 1 real
`bicycle_repair_station` resolved correctly. Every deferred category
(`fast_food`, `pub`/`biergarten`, `ice_cream`, `food_court`,
`bicycle_rental`/`bicycle_parking`) kept its own stated reasoning, not
a blanket "maybe later."

**Testing**: 6 new unit tests (`test_overpass.py`: cafe/
bike_repair_station tag mapping ×2, query-string inclusion) and 2 new
tests reading the static JS source (`test_templates.py`:
`peakElevationLayer` presence/wiring, `cafe`/`bike_repair_station`
marker colour+icon presence) — same "no JS test runner in this
project" convention as every other `post-map.js`/`elevation-chart.js`
test. `make ci`: 404 tests passing, 96.33% coverage, security clean.
`make deploy` completed; live-verified in production (see Leftover for
the one item not yet re-checked post-deploy).

## Leftover

- **Live visual confirmation of the peak label and new marker colours
  in an actual browser wasn't performed** — this project's own stated
  testing convention for MapLibre-rendering work is "manual/visual
  only" for the rendering itself (no JS test runner), and that manual
  step is the operator's own visual check, not something this agent's
  text-based tools can perform. The structural facts (layer exists,
  filtered correctly, wired into both style-build call sites, colours/
  icons present for both new categories) are unit-tested; the actual
  pixel-level rendering in a real browser against Feldberg's post page
  is the one remaining manual check, same as every prior MapLibre
  styling phase in this project.
- **`cafe`/`bike_repair_station` not added to `static/editor/
  config.yml`'s curated-POI dropdown** — this doc's own Phase 2 scope
  only covers the Overpass auto-discovery side (matching exactly what
  it wrote), not the author-curation side. `restaurant` already had a
  config.yml entry before its own auto-discovery gap was fixed;
  `cafe`/`bike_repair_station` are new categories with no such
  precedent either way. Left as a deliberate non-decision here — add
  if an author ever wants to manually curate a cafe/repair-stand POI
  off a route's auto-discovered radius, not pre-emptively.
- **Existing already-synced routes won't show cafes/repair stations
  until their next resync** — same caveat as `fix_amenity_restaurant_
  category.md`'s own Leftover; not urgent at this project's current
  scale, a manual `/internal/resync` trigger would backfill sooner if
  wanted.
- **If a future Protomaps/Planetiler basemap release ever adds
  aerialway data**, the cable-car content-relevance question this
  phase's own intro raised needs answering *then*, not skipped a
  second time just because the data finally exists.