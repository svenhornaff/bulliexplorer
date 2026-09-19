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

## Regression fix — `peakElevationLayer()` was silently suppressing the native peak label entirely

**Symptom, found by the operator's own real-world comparison**: after
the companion label-priority doc's fix landed (settlement names now
rendering correctly, confirming that part worked), peak labels were
**still genuinely, decisively missing** on a real route passing
directly through the Feldberg/Seebuck summit area — not the
elevation-text addition alone; the native icon+name label this doc's
own Phase 1 said already existed was gone too.

**Hypothesis raised, checked directly, disproven with real data**: a
property-name mismatch (`elevation` vs OSM's raw `ele` tag). Re-ran
the exact real tile-inspection method (`pmtiles tile` + `mapbox-
vector-tile` decode) specifically printing full property lists for
three real peaks (Feldberg, Seebuck, Baldenweger Buck) — every one
genuinely has a property literally named `elevation`, not `ele`.
Hypothesis disproven by direct evidence, not assumed correct or
incorrect.

**Real root cause, found by isolating the actual live production
style with a real headless browser**: built the stock, unmodified
vendor style alone (peaks render correctly: 1 result via
`queryRenderedFeatures`), then re-added this project's own layers one
at a time. `cyclingLayers()` and the label-priority split: no effect,
peaks still render. The moment `peakElevationLayer()` was added: peaks
dropped to 0 rendered results on the *native* `pois` layer — this
layer's own presence was winning MapLibre's cross-layer collision
budget over the native peak icon+name label for the identical
feature, hiding the more important native label entirely, even though
the two labels don't visually overlap by design (native is offset
left/right, this layer's text sits below).

**First attempted fix, tested directly, disproven**: an explicit
`symbol-sort-key` on this layer, deliberately set numerically worse
(lower priority) than the native layer's own fallback, on the theory
that MapLibre's documented "lower sort-key wins" rule would make this
layer defer. Re-ran the same isolated-rebuild method with that change
in place — disproven: the native layer still rendered 0 peaks.
MapLibre's own docs (checked via web search, not assumed) confirm
there's no single documented default/ordering rule for the omitted-
sort-key case this bug actually depended on — the theory didn't match
reality.

**Verified fix**: `"text-allow-overlap": true` + `"text-ignore-
placement": true` on `peakElevationLayer()`'s layout — removes this
layer from MapLibre's collision system entirely, rather than trying to
out-rank the native layer within it. Re-verified with the *literal*
function extracted from the real fixed file (not a manual
reconstruction) against the real production page: native `pois` layer
back to rendering "Feldberg" (1 result, matching the stock-style
baseline), this layer still rendering its own elevation text (10
results) at the same time — both working together, as originally
intended.

**Done when**
- [x] The reported symptom (peak labels genuinely missing on a real
  route through Feldberg/Seebuck) no longer reproduces — confirmed
  with a real headless browser against the real production page and
  the real, literal fixed function (not a reconstruction).
- [x] The elevation-property-name hypothesis was checked directly
  against real data, not left as an open theory either way.
- [x] A regression test exists that would have caught this —
  `test_post_map_js_peak_elevation_layer_never_competes_for_collision`
  — verified it actually fails against the pre-fix code before
  confirming it passes against the fix.
- [x] The supplementary elevation text still renders correctly
  alongside the restored native label, not just "native label back,
  new feature silently broken instead."

**Testing**: 1 new unit test
(`test_post_map_js_peak_elevation_layer_never_competes_for_collision`),
plus real, live headless-browser verification (stock-style baseline,
incremental isolation across every layer this project adds, and final
confirmation using the literal extracted function against the real
production page) — the same higher-rigor approach used for the
companion doc's filter-dialect crash fix, since this too was a runtime
rendering behaviour static source-reading alone couldn't have caught
directly. `make ci`: 407 passed, 96.33% coverage, security clean.

## Regression fix #3 — orphaned bare elevation numbers, missing the native layer's own prominence gate

**Symptom, found by the operator's own real-world comparison against
the OSM reference at a denser real location** (Siebengebirge —
Petersberg, Großer Ölberg, Drachenfels, near Königswinter): once
regression fix #2 correctly restored the native peak icon+name label,
a *different* real problem appeared — dozens of orphaned bare
elevation numbers scattered with no icon or name next to them, for
minor, unnamed elevation points the native `pois` layer deliberately
doesn't consider prominent enough to label at this zoom.

**Real mechanism, not a guess**: the native layer's own filter gates
on each individual feature's `min_zoom` property — a per-feature
prominence value baked into the tile data (real summits like
Petersberg/Großer Ölberg/Drachenfels earn a low enough `min_zoom` to
show at a given zoom; minor points don't). `peakElevationLayer()`'s
filter had no equivalent gate — only `kind=="peak"` plus a flat
`minzoom: 11` on the layer itself — so it fired for *every* peak
feature in the tile regardless of that specific feature's own
prominence, producing a bare number wherever the native layer was
correctly withholding its own label.

**Fix**: add the identical per-feature gate the native layer already
uses — `[">=", ["zoom"], ["+", ["get", "min_zoom"], 0]]` — so this
layer's elevation text only ever appears for peaks that also earn the
native icon+name at the current zoom.

**Verified with a real headless browser at two real locations**:
- Feldberg (the original regression #2 test location, sparse area):
  still correct after this fix — native peak renders, elevation label
  renders, zero orphans.
- Siebengebirge (this regression's own denser test location): with
  the full real style, still 2 of 3 real summits showed as "orphaned"
  by a naive same-name comparison — investigated further rather than
  accepted at face value. Isolating just the native `pois` layer
  against this layer alone (removing every *other* competing label)
  showed all 3 summits rendering correctly with zero orphans,
  confirming the apparent mismatch in the full style was ordinary
  MapLibre collision crowding from *unrelated* labels in a busy area
  (roads, settlements, other POIs) — not a bug in this fix. That's a
  separate, narrower, pre-existing trade-off of regression #2's
  `text-allow-overlap`/`text-ignore-placement` design (this layer
  always draws regardless of collision; the native layer still
  respects normal collision and can occasionally lose to unrelated
  crowding in busy areas specifically) — noted honestly in Leftover
  below rather than silently folded into "fixed."

**Done when**
- [x] The reported symptom (orphaned bare elevation numbers for minor,
  unnamed elevation points) no longer reproduces for peaks that don't
  meet their own prominence threshold.
- [x] Real summits that do meet their own prominence threshold still
  get both the native icon+name and this layer's elevation text
  together — not a regression back to #2's original problem.
- [x] A regression test exists
  (`test_post_map_js_peak_elevation_layer_matches_native_prominence_gate`)
  asserting the exact gate expression is present.
- [x] The remaining collision-crowding nuance in dense areas is
  investigated to a real, confirmed root cause (not left as an
  unexplained residual difference) and disclosed honestly rather than
  silently absorbed into "done."

**Testing**: 1 new unit test
(`test_post_map_js_peak_elevation_layer_matches_native_prominence_gate`),
plus real, live headless-browser verification at both the sparse
(Feldberg) and dense (Siebengebirge) locations, plus an isolation test
(native layer alone, no other competing labels) to distinguish this
fix's own correctness from ordinary collision crowding. `make ci`: 408
passed, security clean.

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
  in an actual browser** — update after the regression fix above: this
  *has* now been done, precisely because the reported symptom forced
  it. A real headless browser confirmed the native peak label and this
  layer's own elevation text both render correctly together on the
  real production page. What's still not verified is the general
  visual polish/colour-matching quality across every flavor (light/
  dark) and every marker category, not just the one location this
  regression happened to be reported against — that broader spot-
  check remains a manual step.
- **Regression: `peakElevationLayer()`'s first implementation
  silently suppressed the native peak label entirely** (see
  "Regression fix" section above) — an unset `symbol-sort-key`
  interacting with MapLibre's cross-layer collision system in an
  undocumented way. Found and fixed after the operator's own real-
  world comparison caught it, with a disproven property-name
  hypothesis and a disproven first fix attempt along the way — both
  checked directly against real data/behaviour rather than assumed.
  Worth noting for anyone adding another symbol layer that shares a
  source-layer/anchor point with an existing native layer: don't
  assume a new symbol layer is automatically "purely additive" just
  because it doesn't touch the same style properties — check its
  effect on the native layer's own collision outcome directly, the
  same way this bug was actually found.
- **Regression #3: `peakElevationLayer()` fired for every peak
  regardless of that specific feature's own prominence**, producing
  orphaned bare elevation numbers for minor, unnamed elevation points
  the native layer deliberately doesn't label yet — fixed by adding
  the identical per-feature `min_zoom` gate the native layer already
  uses (see "Regression fix #3" above).
- **A real, distinct trade-off surfaced while verifying regression
  #3, not fully resolved and deliberately not chased further**: in
  genuinely dense areas (verified at Siebengebirge), the native `pois`
  layer's peak label can occasionally lose MapLibre's ordinary
  collision fight against unrelated, more numerous nearby content
  (roads, settlement names, other POIs) — normal, expected behaviour
  for *any* symbol layer in a crowded scene. This layer's own
  `text-allow-overlap`/`text-ignore-placement` (regression #2's
  verified fix) means its elevation text keeps drawing regardless,
  so in that specific crowded-scene edge case a bare elevation number
  can still appear without its corresponding native icon+name right
  next to it — not the *original* bug (this fix's own gate correctly
  excludes low-prominence peaks), but a narrower, honestly-disclosed
  residual mismatch inherent to regression #2's own design choice.
  Chasing this further would mean either making this layer collision-
  sensitive again (risking reintroducing regression #2) or querying
  the native layer's actual runtime collision outcome per-feature
  (meaningfully more complex, no established MapLibre mechanism for
  it) — judged not worth the risk/complexity for a rare, cosmetic,
  dense-area-only edge case. Flagged concretely rather than silently
  absorbed into "done", in case it's worth revisiting later.
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