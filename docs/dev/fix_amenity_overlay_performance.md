# Fix: amenity overlay performance — DOM markers to clustered GL layer

> Root cause and fix plan for severe page slowness on `dream-of-north`
> after `fix_incremental_amenity_writes.md` started successfully landing
> real data — 15,686 amenities now exist for that route, and the current
> rendering approach breaks down catastrophically well before that scale.
> Same pattern as every fix in this chain: the previous fix working
> correctly is what exposed this one.

---

## Symptom

Loading `dream-of-north` is "brutal slow," confirmed by a screenshot
showing a solid, unreadable mass of overlapping marker icons rather than
a usable map.

## Root cause — confirmed in the code, not guessed

```js
return new maplibregl.Marker({ element: el })
  .setLngLat(feature.geometry.coordinates)
  ...
```

Every amenity creates its **own individual DOM element and its own
`maplibregl.Marker` object** — 15,686 of them for this route. This is
the well-documented MapLibre/Mapbox performance cliff: DOM markers are
fine for dozens, tolerable for a few hundred, and degrade sharply well
before the low thousands. 15,686 is far past that line. This is what's
actually slow — not the ~15k rows in Postgres (trivial for a database)
and not the network payload (a few MB of GeoJSON, unremarkable).

**Ruled out first, worth being explicit about**: the search radius
(`_AMENITY_SEARCH_RADIUS_KM = 2.0`) is already narrow. The data volume
is real — a 4,247km route legitimately crosses several dense urban
corridors within that already-tight 2km buffer — not a symptom of an
overly generous search area that needs shrinking further.

**Why the DOM-marker choice was reasonable when made, not a mistake**:
the comment beside it explains the original reasoning — DOM markers
survive a `map.setStyle()` theme swap without any extra code, which
mattered when amenity counts were in the dozens (88-191 for the small
local routes that existed at the time). Nobody was designing for a
15,000-row outlier; same shape as every other fix in this chain, a
sound decision under assumptions that later stopped holding.

## The fix: GeoJSON source + clustered GL layer

Standard, well-established MapLibre pattern for exactly this situation —
GPU-rendered via the same pipeline already drawing the entire basemap,
genuinely handles tens of thousands of points with no perceptible lag.
Clustering (`cluster: true` on the source) is not a separate feature
bolted on for this fix; it's necessary regardless, since even
instant rendering of 15,686 individual icons at a wide zoom would still
be the same unreadable mass in the screenshot — clustering groups nearby
points into a count bubble that splits apart on zoom, fixing readability
as the direct consequence of fixing performance, not a second project.

**The theme-swap mechanism this needs already exists and works** —
confirmed by reading it directly, not assumed. `document.addEventListener("bulliexplorer:themechange", ...)`
already calls `map.setStyle()` with a `transformStyle` callback that
carries the `route` source and `route-line`/`route-casing` layers across
the swap — MapLibre's own recommended pattern for this exact problem
(the code even cites the upstream GitHub discussions this was researched
from). Adding amenities means adding one more entry to that same,
already-proven carry-over list — not new architecture.

**Icons vs. color-coding — a deliberate scope decision, not an
oversight**: curated POI markers currently render real Maki icons via
inline SVG path data injected into a DOM element
(`buildCategoryMarkerElement`). MapLibre's native `symbol` layer icons
need a sprite sheet (`icon-image` referencing a pre-built sprite), not
inline SVG — building one would be new asset-generation infrastructure,
work this fix doesn't need in order to solve the actual problem
(performance). **Scope this fix to color-coded circles**, reusing the
existing `CATEGORY_COLOURS` map already defined for the DOM markers —
same visual language, zero new assets, and clusters wouldn't usefully
show per-category icons anyway (a cluster of 50 mixed amenities needs a
count, not 50 different glyphs). Real per-category icons on unclustered,
zoomed-in points is a legitimate future polish item, explicitly not
blocking this fix.

**Curated POI markers are untouched** — single digits to low dozens per
post, genuinely fine as DOM markers at that scale. Nothing about this
fix touches that code path.

## Phased implementation plan

### Phase 1 — Convert amenities to a clustered GeoJSON source + layers

**Scope**
- [x] Replace the `amenityFeatures.map(...) → maplibregl.Marker` loop
  with a `map.addSource('amenities', { type: 'geojson', data:
  AMENITIES_GEOJSON, cluster: true, clusterMaxZoom: 14, clusterRadius:
  50 })`.
- [x] Three layers on that source, MapLibre's standard clustering
  pattern: a `circle` layer for clusters (filtered on `['has',
  'point_count']`, radius/color scaled by count), a `symbol` layer for
  the cluster count label (`text-field: '{point_count_abbreviated}'`),
  and a `circle` layer for individual unclustered points (filtered on
  `['!', ['has', 'point_count']]`), colored via a `match` expression on
  `category` reusing the existing `CATEGORY_COLOURS` values.
- [x] All three layers start `visibility: 'none'` — the "Show nearby
  services" toggle default-off behavior is preserved, just implemented
  via `setLayoutProperty` instead of not calling `.addTo(map)`.
- [x] Toggle handler: `map.setLayoutProperty('amenities-clusters',
  'visibility', checked ? 'visible' : 'none')` (and the other two layer
  ids), replacing the current `.forEach(marker => marker.addTo/remove)`
  loop.
- [x] Click handler on the unclustered-point layer for the popup
  (`map.on('click', 'amenities-unclustered', ...)`), replacing each
  marker's individual `.setPopup()` — MapLibre layers handle this via
  one event listener querying the clicked feature, not per-feature
  listeners.
- [x] Add `amenities` (source) and the three layer ids to the existing
  `transformStyle` carry-over list alongside `route`/`route-line`/
  `route-casing`, so the overlay survives a theme swap the same way the
  route line already does.

**Done when**
- [ ] Loading `dream-of-north` with the toggle checked is smooth — no
  perceptible jank on initial render, pan, or zoom. Informal but real:
  "does this feel brutal" is the actual bar this phase exists to clear.
  **Not yet verified live** — no browser/production access from this
  sandbox; left for the user's next deploy.
- [ ] Zoomed out, amenities render as count-bubbled clusters, not a solid
  mass of overlapping icons — the screenshot's specific problem, fixed.
  **Not yet verified live**, same reason.
- [ ] Zooming in progressively splits clusters apart, down to individual
  color-coded points at high zoom. **Not yet verified live**, same
  reason.
- [ ] A theme swap (light/dark toggle) with amenities visible carries the
  overlay across correctly, same as the route line already does —
  verified by toggling theme while "Show nearby services" is checked.
  **Not yet verified live**, same reason — the `transformStyle`
  carry-over code is written and structurally mirrors the already-
  working route-line carry-over exactly, but hasn't been exercised in a
  real browser against the real amenities data.
- [ ] Kinzig Valley Loop and Feldberg (88 and 191 amenities respectively)
  still render correctly — confirms this isn't a regression for the
  routes that were already working fine at low counts. **Not yet
  verified live**, same reason.

**Design decisions made during implementation:**
- **Idempotent `addAmenitiesSourceAndLayers`**: guards on
  `map.getSource('amenities')` already existing before adding anything.
  Necessary because `transformStyle`'s carry-over means the source/
  layers already exist in the *next* style by the time `setStyle()`'s
  own `"load"`-equivalent fires again (theme swaps don't re-run the
  outer `map.on("load", ...)` handler that calls this function once at
  init, so this specific guard is defensive/future-proofing rather than
  something exercised by the current single call site — kept anyway
  since it's a correct, standard MapLibre pattern and costs nothing).
- **`amenitiesVisible` hoisted to a closure-level variable** (alongside
  the existing `routeLoaded`), not read fresh from the checkbox's DOM
  state each time — needed so a theme swap's `transformStyle` carry-over
  logic doesn't need to know anything about the toggle at all; visibility
  is a layer-layout property carried over as part of the layer
  definitions themselves, not a separate re-application step.
- **Cluster radius steps** (`["step", ["get", "point_count"], 14, 25, 18,
  100, 24, 750, 30]`) sized against the actual data distribution this
  fix exists for — a 750+ threshold specifically because Dream of
  North's densest single chunk alone returned 4,309 amenities
  (fix_overpass_urban_density_timeout.md's live log), so clusters at
  that scale needed their own visually-distinct top tier rather than
  maxing out at the same size as a 100-point cluster.

**Testing**
- No meaningful automated test for this — client-side WebGL rendering
  and clustering behavior, same reasoning already established for every
  other MapLibre-rendering phase in this project's docs (Phase 1/2/4 of
  `gis_cycling_upgrade.md`, Phase 4 of `media_storage_r2.md`). Manual
  verification against the specific route that exposed the problem is
  the only meaningful check — confirmed the new JS is syntactically
  valid (extracted and checked with `node -c` after substituting the
  Jinja2-templated values) and that `djlint templates/post.html --check`
  (the actual CI-gating template linter) reports clean, but neither of
  those substitutes for an actual browser render.

## Explicitly out of scope

- **Real per-category icons on unclustered points** (sprite-sheet-based
  `icon-image` instead of color-coded circles) — legitimate future
  polish, deliberately not blocking a performance fix on new asset
  infrastructure. Revisit if the color-only distinction proves
  insufficient in practice.
- **Viewport-based/paginated amenity loading** (fetching only the
  currently-visible map area's amenities instead of the whole route at
  once) — not needed at this data scale. MapLibre's clustering is
  designed for, and regularly demonstrated with, datasets well beyond
  15,686 points rendered smoothly client-side; this would be solving a
  problem that doesn't actually exist yet.
- **Reducing `_AMENITY_SEARCH_RADIUS_KM`** — the buffer is already
  narrow; this was ruled out as the actual cause above, not deferred as
  a future nice-to-have.

## Summary

Phase 1 implemented. `templates/post.html`'s amenity overlay is now a
clustered GeoJSON source + three GL layers (`amenities-clusters`,
`amenities-cluster-count`, `amenities-unclustered`) instead of one
`maplibregl.Marker` DOM element per amenity. Cluster radius scales with
count up to a dedicated top tier for 750+-point clusters, sized against
Dream of North's actual data (a single chunk alone returned 4,309
amenities per `fix_overpass_urban_density_timeout.md`'s live log). The
amenities source and all three layer ids were added to the existing
`transformStyle` theme-swap carry-over list, mirroring the pattern
already proven for the route line/casing. Curated POI markers are
untouched — still plain DOM markers, genuinely fine at their scale
(single digits to low dozens per post).

`make ci`: 293 passed, 95.65% coverage, security checks clean —
unchanged from before this change, since it's a pure client-side/
template fix with zero Python code touched.

## Recommended next steps

- **Live verification (the whole point of this fix)** — not possible
  from this sandbox: no browser, no ability to actually render a
  WebGL map or visually confirm clustering/theme-swap behavior. Every
  item under Phase 1's "Done when" is unchecked for exactly this reason
  and needs the user's own browser against the real deployed page:
  - Load `dream-of-north` with "Show nearby services" checked — confirm
    it's smooth (no jank on render/pan/zoom) and that amenities render
    as count-bubbled clusters at a wide zoom, splitting apart into
    individual color-coded points on zoom in.
  - Toggle light/dark theme while amenities are visible — confirm the
    overlay survives the swap the same way the route line already does
    (the `transformStyle` carry-over code is written and structurally
    mirrors the proven route-line pattern exactly, but has never
    actually run against real amenities data in a real browser).
  - Confirm Kinzig Valley Loop and Feldberg (88 and 191 amenities) still
    render correctly — not a regression for the low-count routes that
    already worked fine as DOM markers.
  - Click an unclustered point and confirm the popup still shows the
    amenity's name (the click-handler rewrite from per-marker
    `.setPopup()` to one layer-level `map.on('click', 'amenities-
    unclustered', ...)` listener is untested against a real click
    event).
- **What was verified without a browser, worth noting for confidence**:
  the new/changed JS was extracted from the template and checked with
  `node -c` after substituting Jinja2's `{{ ... }}` placeholders (which
  a plain JS parser can't parse) with dummy values — confirms no syntax
  error, but proves nothing about actual MapLibre runtime behavior,
  clustering correctness, or the carry-over logic's real effect.
  `djlint templates/post.html --check` (the actual CI-gating template
  linter) also reports clean.