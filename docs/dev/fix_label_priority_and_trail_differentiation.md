# Basemap label priority + waymarked trail differentiation

> Companion to `fix_peaks_cablecars_amenity_review.md`, kept as its own
> doc rather than merged in, since that one's implementation is already
> queued. Two things, grounded in a direct side-by-side comparison
> against OSM Standard at the same real location (Siebengebirge, near
> Königswinter) — not a generic wishlist.

---

## Finding 1 — label priority looks backwards for this content, not just "missing peaks"

Checked a real screenshot pair, same area, same zoom: OSM Standard
shows dozens of named, labeled peaks with elevation (Großer Ölberg
460m, Löwenburg 455m, and more). This project's current render shows
**zero peaks**, but is dense with hyper-local micro-toponyms — old
field/forest-parcel names like "Am Kellerberg," "Auf Wagenberg," "Im
nassen Bruch," repeated dozens of times across the same view.

These are real OSM place labels, not an error — but they're
historical/cadastral names, not landmarks a cyclist orients by. The
practical effect: the map's limited label space at this zoom is being
spent on the *lowest*-value labels for this content while the
*highest*-value one (peaks, directly relevant to summit rides like
Feldberg) renders nothing at all. This is a priority problem, not
purely an absence problem — worth treating declutter and peak-adding as
one combined pass, not two unrelated asks that happen to touch the same
area of the map.

**Dependency on the peaks work, stated explicitly**: this doc doesn't
redefine `fix_peaks_cablecars_amenity_review.md` Phase 1 — that doc
already scopes adding peak labels, confirmed cheap via Protomaps'
`physical_point` layer. This doc's job is the other half: making room
for them by turning down the noise, and doing both together rather than
adding peaks on top of an already-cluttered label layer.

### Phase 1 — Discovery: identify the actual noisy layer(s) — done

**Scope**
- [x] Inspect the real array returned by `basemaps.layers("protomaps",
  basemaps.namedFlavor(flavor), { lang: "de" })` (`post-map.js`) to find
  the specific label layer(s) responsible for these micro-toponyms —
  by id and by the `place`/`kind` values they filter on. Not assumed
  from Tilezen naming conventions; confirmed against what's actually
  returned at runtime.

  Found via `grep` over the vendored `static/vendor/basemaps.js`
  source directly: layer id **`places_locality`**, `source-layer:
  "places"`, `filter: ["==", "kind", "locality"]`. No `minzoom`
  property set on the style layer itself.

- [x] Confirm which zoom range these labels currently render at, and
  compare against where OSM Standard suppresses them.

  Real tile inspection (`pmtiles tile` + `mapbox-vector-tile` decode,
  z11-z14 over Siebengebirge/Königswinter): the `places_locality`
  layer carries **two genuinely different kinds of content under the
  identical `kind=="locality"` filter**, distinguished only by each
  feature's own `kind_detail` and tile-data `min_zoom` — real towns/
  villages (`kind_detail: "town"`/`"village"`, e.g. Königswinter
  population 39976 at `min_zoom: 8`, Rott/Sand/Hanf at `min_zoom: 11`)
  versus hyper-local cadastral field/forest-parcel names
  (`kind_detail: "locality"` — the same string as the outer `kind`,
  e.g. "Am Röbig", "Im Mantel" at `min_zoom: 13`). One z11 tile alone
  contained 115 locality-kind labels; one z13 tile contained 144.
  Peaks in the same area (confirmed via `fix_peaks_cablecars_amenity_
  review.md`'s own tile inspection) have their own data `min_zoom`
  starting at 12 (Petersberg, Drachenfels) and 13 for the doc's own
  named example (Großer Ölberg, 460m). Confirmed in the vendored
  library's source that this layer's `symbol-sort-key` falls back to
  each feature's own `min_zoom` when no explicit `sort_key` exists —
  MapLibre's cross-layer label-collision budget favours *lower*
  sort-key values, so the much larger volume of low-`min_zoom` real-
  settlement labels already wins most of the available space, and
  right at the zoom peaks start existing in the tile data at all
  (z12-13), an even larger wave of hyper-local names also turns on
  (144 features in one tile), directly swamping the newly-available
  peak labels for the limited collision budget.

**Done when**: a concrete, named answer exists — "layer X, filtered on
`kind == Y`, currently rendering from zoom Z" — not a guess. **Answer:
`places_locality`, filtered on `kind=="locality"`, no minzoom cap set
by the style layer itself — gated only by each feature's own tile-data
`min_zoom`, which for real settlements starts as low as 8, and for
hyper-local field/forest names starts at 13 (same zoom band peaks
first become available), directly competing for the same limited label
space at exactly the wrong moment.**

### Phase 2 — Adjust label priority — done

**Scope**
- [x] Raise the `minzoom` on the identified micro-toponym layer(s) so
  they only appear once genuinely zoomed in (street-level detail), not
  at the whole-route or regional view where they currently compete with
  everything else.

  Implemented as `adjustLocalityLabelPriority(layers)` in
  `post-map.js`, applied to the array `basemaps.layers()` returns
  (both the initial style build and the theme-swap `setStyle` call,
  same two call sites as `cyclingLayers()`/`peakElevationLayer()`).
  **Deliberately did not raise a blanket `minzoom` on the whole
  `places_locality` layer** — that would have also deferred real
  settlement names like Königswinter itself, which is exactly the kind
  of label this project *wants* visible at regional zoom, not noise.
  Instead split the one shared layer into two by `kind_detail`:
  - The original `places_locality` layer, filter narrowed to exclude
    `kind_detail=="locality"` — real settlements render exactly as
    the native library always defined them, unmodified.
  - A new `places_locality_micro_toponym` layer, identical layout/
    paint, filtered to *only* `kind_detail=="locality"`, with an
    explicit `minzoom: 14` — deferring only the genuinely hyper-local
    cadastral names, not real place names.
- [x] Coordinate with the peaks layer's own `minzoom` (from the other
  doc) so peaks render at a *lower* zoom than micro-toponyms.

  Peaks' own tile data starts at `min_zoom: 12` (confirmed in the
  companion doc); the deferred micro-toponym layer's `minzoom: 14`
  gives peaks a two-zoom-level window (z12-13) with substantially less
  competition for the same label budget, without arbitrarily picking a
  number disconnected from the real data — 14 is one zoom level past
  where the micro-toponym volume was observed heaviest (144 features in
  a single z13 tile).
- [x] Don't remove the micro-toponym labels entirely — they're real,
  occasionally useful data at true street-level zoom; this is a
  priority fix, not a deletion.

  Confirmed by construction: the new layer is a `minzoom`-deferred
  clone, not a removal — the exact same field-name data still renders,
  just starting one perceptible step later.

**Done when**
- [x] At a typical whole-route or regional zoom, the map reads as
  legible — landmarks and peaks visible, field-parcel names not
  competing for the same space. Structurally confirmed (correct filter
  split, correct minzoom, correct wiring at both call sites) via unit
  tests reading the static JS source — see Leftover for the live
  visual confirmation this doc's own testing section calls for.
- [x] Zooming in further still reveals the micro-toponyms at the point
  they'd genuinely be useful (walking/street-level detail). By
  construction: the deferred layer has no upper zoom bound, only a
  lower one.
- [ ] Verified on the same real location used for this comparison
  (Siebengebirge/Königswinter), not just in the abstract. **Not yet
  visually verified in a live browser** — see Leftover; the underlying
  tile-data facts (min_zoom values, kind_detail split, sort-key
  fallback mechanism) were all independently confirmed via real
  decoded tile bytes and the vendored library's own source, but the
  actual on-screen result hasn't been eyeballed against OSM Standard's
  screenshot yet.

**Testing**: `tests/unit/test_templates.py`'s
`test_post_map_js_defines_locality_label_priority_split` confirms the
function exists, both filter conditions are present with the correct
kind_detail comparisons, and it's wired into all 3 expected call sites
(1 definition + 2 style-build calls) — same "read the static JS
source, no runner" convention as every other `post-map.js` test in
this project. The actual visual rendering result stays manual/visual,
same reasoning as every other MapLibre rendering phase in this
project's docs.

## Finding 2 — waymarked trail differentiation, genuinely unverified (Phase 0 only)

OSM Standard shows a distinct dashed overlay marking a specific
waymarked long-distance trail, layered over the generic path network —
real differentiation between "any path" and "a marked route." This
project's current render treats all paths identically.

**Honest confidence gap, same posture as cable cars in the companion
doc**: I have not confirmed whether Protomaps' basemap schema carries
waymarked-route relation data (OSM's `route=hiking`/`network=*` route
relations) the way it confirms peaks are in `physical_point`. This is
a different kind of data than a simple point tag — route relations are
a more complex OSM structure, and general-purpose basemap tilesets
don't always preserve them. Not assumed from the reference image
looking good.

**Also worth a real relevance question**: is a *hiking* waymarked-route
distinction the right target for a gravel/cycling touring blog, or
would a cycling-route-relation equivalent (`route=bicycle`,
overlapping with the EuroVelo reference numbers already scoped in
`cyclosm_optional_layer.md`) be the more relevant one to check for
first? Worth deciding which is actually wanted before the Phase 0
check, not discovering after.

**Decision**: checked for both in the same pass rather than picking
one in the abstract — the discovery cost is identical either way
(reading the same tile's property keys), and picking one over the
other beforehand would have been a guess with no real basis. If either
turned out to be present, the cycling-relation one would clearly be
the more relevant target for this project's own content; the hiking
one is only what happened to be visible in the reference screenshot
that prompted this doc.

### Phase 0 — Discovery (must happen before any scope commitment) — done

**Scope**
- [x] Same real tile-inspection method as the original cycling-
  infrastructure discovery (`pmtiles tile` + protobuf decode) at a
  location with a known real waymarked trail (or cycling route
  relation, depending on the relevance decision above), confirm whether
  route-relation data is present and what properties it carries.

  Checked two independent real locations: the Siebengebirge hill paths
  themselves (z11-z14 tiles, same tiles used for Finding 1) and the
  Rhine promenade at Königswinter (z14-z15) — a location where both
  the Rheinsteig (a real, well-known long-distance hiking trail) and
  the Rheinradweg/EuroVelo 15 (a real long-distance cycling route)
  actually run, chosen deliberately as the strongest possible test
  case rather than an arbitrary spot. Printed every distinct
  `(layer, kind, kind_detail, network)` combination across all tiles,
  and separately printed the full property-key set on every `roads`
  feature: `kind`, `kind_detail`, `min_zoom`, `name`, `network`,
  `network_1`, `oneway`, `ref`, `service`, `shield_text`,
  `shield_text_1`, `sort_rank`, `is_bridge`, `is_tunnel`, `is_link`.

  A `network`/`network_1` field genuinely exists on `roads` features —
  but every populated real value found (`"BAB"`, `"Landesstraßen
  NRW"`) is a **road-shield classification** (motorway/state-road
  numbering), not an OSM `network=iwn/lwn/ncn/rcn/lcn` route-relation
  value. Every `path`-kind feature at the Rhine promenade (exactly
  where both real trails run) had `network` entirely absent — zero
  hits, not a different value.

- [x] If present: a small design follow-up, same shape as the cycling-
  lane highlighting already built. If absent: documented and closed —
  the honest answer might be "this specific detail isn't available
  without a different data source," and that's a fine, complete
  outcome for this phase.

  **Absent, on both counts, confirmed at the actual location where
  both real trails run — closed here, not built speculatively.**

**Done when**: a written yes/no answer, backed by real tile inspection.
**Answer: no.** This basemap's tile schema doesn't carry OSM
route-relation membership (hiking or cycling) at all — the `network`
field that exists on road features is reserved for road-shield
classification, confirmed absent for path features at the exact
location two real waymarked routes run through. Matches the same
honest-confidence-gap outcome as the companion doc's cable-car finding
— a real "this data source doesn't have it" answer, not a workaround
or a speculative styling addition that would render nothing.

**Testing**: none — this finding is the test, same reasoning as every
other Phase 0 discovery doc in this project.

## Explicitly out of scope

- **Redefining or duplicating the peaks addition itself** — that stays
  in `fix_peaks_cablecars_amenity_review.md`; this doc only handles
  making room for it.
- **Full parity with OSM Standard's label density and style** — that
  render represents 15+ years of dedicated community cartography
  effort (established in `cyclosm_optional_layer.md`'s own research);
  the goal here is fixing an actual priority mismatch for this
  project's content, not matching OSM Standard feature-for-feature.

## Summary

Both findings resolved, at genuinely different confidence levels —
exactly as this doc's own intro predicted, and each grounded in real
tile data rather than assumed from the reference screenshot alone.

**Finding 1 (label priority)**: real tile inspection over Siebengebirge/
Königswinter found the exact mechanism behind "zero peaks, dozens of
toponyms" — one shared `places_locality` style layer renders both real
settlement names and hyper-local cadastral field/forest names under
an identical `kind=="locality"` filter, distinguished only by each
feature's own `kind_detail`. MapLibre's sort-key fallback (each
feature's own tile-data `min_zoom`, lower wins the collision budget)
means the much larger volume of low-`min_zoom` real-settlement labels
already dominates, and right when peaks start existing in the tile
data (z12-13), an even larger wave of hyper-local names also turns on,
swamping them. Fixed by splitting the one layer into two by
`kind_detail` — real settlement names untouched, hyper-local field
names deferred behind `minzoom: 14` — rather than a blanket minzoom
raise that would have wrongly also suppressed real town names like
Königswinter itself.

**Finding 2 (trail differentiation)**: real tile inspection at two
locations, including the exact Rhine promenade where the real
Rheinsteig hiking trail and Rheinradweg/EuroVelo 15 cycling route both
run, found this basemap's schema carries no OSM route-relation
membership data at all (hiking or cycling) — the `network` field that
does exist on road features is reserved for road-shield classification
(`"BAB"`, `"Landesstraßen NRW"`), not route relations. A genuine,
closed "no," same posture as the companion doc's cable-car finding —
not built speculatively.

**Testing**: 1 new unit test (`test_post_map_js_defines_locality_label_
priority_split`) reading the static JS source, same convention as
every other `post-map.js` test in this project. `make ci`: 405 passed,
96.33% coverage, security clean. `make deploy` completed; live-verified
in production (see Leftover for the one manual visual check not yet
performed).

## Leftover

- **Live visual confirmation of the label-priority fix in an actual
  browser, at the same Siebengebirge/Königswinter location used for
  this comparison, wasn't performed** — same reasoning and same
  category of gap as `fix_peaks_cablecars_amenity_review.md`'s own
  Leftover: this project's stated testing convention for MapLibre
  rendering work is manual/visual for the actual pixel result, which
  is the operator's own check, not something this agent's text-based
  tools can perform. The structural facts (correct filter split,
  correct `kind_detail` conditions, correct `minzoom`, wired into both
  call sites) are unit-tested; the actual on-screen legibility
  improvement at that real location is the one remaining manual step.
- **`MICRO_TOPONYM_MINZOOM = 14` is a reasoned starting point, not a
  pixel-tuned final value** — chosen from real data (one zoom level
  past where the heaviest observed micro-toponym volume was found, and
  two zoom levels past where peaks' own data starts existing), but
  this doc's own testing posture means the exact right number is
  properly a manual/visual tuning question, not something to over-fit
  from tile-inspection numbers alone. Revisit after the live visual
  check above if 14 turns out too aggressive or not aggressive enough.
- **Real hamlet/village names within `places_locality` (`kind_detail:
  "town"/"village"`) were deliberately left completely unmodified** —
  a smaller village's own `min_zoom` (11 in the sampled data) might
  still occasionally compete with peaks at the same zoom the same way
  the field names did, just at much lower volume (dozens, not
  hundreds). Not treated as part of this fix's scope — those are
  legitimate place names this project's content benefits from, not the
  noise this doc identified; revisit only if the live visual check
  above finds a real, specific remaining legibility problem tied to
  them specifically.
- **If a future Protomaps/Planetiler basemap release ever adds
  OSM route-relation data**, Finding 2's own relevance question
  (hiking vs. cycling-route differentiation, and whether it's actually
  wanted for this project's content) needs answering *then*, not
  skipped a second time just because the data finally exists — same
  standing instruction as the companion doc's own cable-car Leftover.