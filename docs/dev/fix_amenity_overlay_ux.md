# Fix: amenity overlay UX — cluster expansion, real icons, richer popups

> Follow-up to `fix_amenity_overlay_performance.md`, based on live testing
> feedback against `dream-of-north` now that the clustered layer is
> deployed and working. Three fixes, each verified against MapLibre's
> actual current API before being scoped — not assumed.

---

## 1. Cluster click-to-expand — confirmed standard, confirmed missing

**Verified**: this is MapLibre's own canonical, documented pattern for
clustered sources — `source.getClusterExpansionZoom(clusterId)` +
`map.easeTo({ center, zoom })` on a cluster click. Checked directly
against Stadia Maps' MapLibre clustering tutorial, which uses the exact
same `clusterMaxZoom: 14` / `clusterRadius: 50` values already in this
codebase — strong signal the implementation was following this same
reference, minus this one handler.

**Confirmed missing**: no `getClusterExpansionZoom` or `cluster_id`
handling anywhere in `post.html` — clicking a cluster bubble currently
does nothing. A reader has to manually scroll-zoom repeatedly to make
clusters break apart, which is exactly the "feels like it should just
work" friction flagged in testing.

**Fix**:
```js
map.on("click", "amenities-clusters", function (e) {
  var features = map.queryRenderedFeatures(e.point, { layers: ["amenities-clusters"] });
  var clusterId = features[0].properties.cluster_id;
  map.getSource(AMENITIES_SOURCE_ID).getClusterExpansionZoom(clusterId, function (err, zoom) {
    if (err) return;
    map.easeTo({ center: features[0].geometry.coordinates, zoom: zoom });
  });
});
```
Standard cursor affordance too — `pointer` on hover over a cluster,
matching the existing hover handling already on the unclustered layer.

## 2. Real icons, not just color — feasible without new infrastructure

**What changed my mind**: the original performance-fix doc scoped icons
out because MapLibre's `symbol` layer `icon-image` conventionally
references a pre-built sprite sheet — real new asset-generation
infrastructure this project doesn't have. Checked MapLibre's actual
image API more carefully this time: **`map.addImage(id, image)` accepts
a runtime-generated image — including a `<canvas>` — with no sprite
sheet file required at all.** This is documented, standard MapLibre
functionality (their own "add an icon generated at runtime" example
uses exactly this), not a workaround.

**Concretely**: the Maki path data already vendored for curated POI
markers (`CATEGORY_ICON_PATHS`) can be drawn once per category onto an
offscreen canvas at page-load time, registered via `map.addImage()`,
and referenced by the unclustered `symbol` layer's `icon-image` —
zero new files, zero build step, reusing data that's already in the
codebase for a different purpose.

**Scope**: unclustered points only — individual amenities at high zoom.
Clusters keep their count-bubble circle styling; a cluster of dozens of
mixed-category amenities has nowhere useful to put a single icon, and
the count is the actually useful information at that zoom level. This
mirrors the same reasoning already applied correctly elsewhere in this
project (curated POIs get real icons because they're always shown
individually; clusters are inherently a different kind of thing).

**Design**:
```js
function categoryImageId(category) { return "amenity-icon-" + category; }

function registerCategoryImages(mapInstance) {
  Object.keys(CATEGORY_ICON_PATHS).forEach(function (category) {
    var canvas = document.createElement("canvas");
    canvas.width = canvas.height = 32;
    var ctx = canvas.getContext("2d");
    // draw CATEGORY_COLOURS[category] circle background, then the
    // existing SVG path (scaled into the canvas) in white on top —
    // same visual recipe buildCategoryMarkerElement already uses for
    // DOM markers, just rasterized once instead of built as DOM nodes
    // per feature.
    mapInstance.addImage(categoryImageId(category), canvas);
  });
}
```
Then the unclustered layer switches from `circle` to `symbol` with
`icon-image: ["concat", "amenity-icon-", ["get", "category"]]` (a
data-driven expression, not one layer per category).

**Needs re-registering after a theme swap** — `map.addImage` doesn't
survive `setStyle()` any more than the layers do, so
`registerCategoryImages` needs calling again after the `transformStyle`
carry-over, before the unclustered layer (now referencing these images)
would try to render.

## 3. Richer popups — surfacing data that's already stored, not fetching anything new

**Checked directly**: `NearbyAmenity.tags` (the raw OSM tags) is already
being written to the database for every amenity — but `_amenities_to_geojson()`
in `app/routes/posts.py` currently only serializes `name` and `category`
into the properties sent to the browser. The richer data isn't missing
from storage, it's just not being passed through.

**What's realistically there**: OSM tagging commonly includes
`website`/`contact:website`, `phone`/`contact:phone`, and
`opening_hours` for exactly the categories in this project's list
(restaurants, supermarkets, bike shops, pharmacies) — not guaranteed
per-element, but genuinely present often enough to be worth surfacing
when it exists.

**Fix, backend**: add `tags` to the properties dict in
`_amenities_to_geojson()` — same pattern already used for POIs, no new
query, the data is already loaded.

**Fix, frontend**: build the popup HTML conditionally on what's actually
present — name and category always shown (closer to the Google Maps
reference: name plus a category line, not just a bare name); a
`website` link (opens in a new tab) and a `phone` link (`tel:`) added
only when those tags exist. No layout for fields that aren't there —
an empty "Phone: —" row is worse than not showing the row at all.

## Explicitly deferred, and why

- **Photos** — correctly flagged as "nice to have, not a must." OSM
  doesn't reliably carry photo data for these categories; doing this
  properly means a third-party image source (Wikimedia Commons search,
  or similar), which is real new infrastructure and a real new external
  dependency, not a data-surfacing task like the fixes above. Worth
  revisiting only if the website/phone links prove insufficient in
  practice.
- **A full business-card-style expanded panel** ("opening a callout
  gives further information," read broadly as reviews/hours/full
  detail) — deliberately not matching Google Maps' full ambition here.
  This overlay is a supplementary, auto-discovered layer; the curated
  POIs the author actually picked are meant to stay the primary content.
  Matching the popup's richness to what OSM data actually and reliably
  offers (a name, a category, sometimes a link) is the right calibration
  for what this layer is for — not a reason to avoid the real
  improvements above, but a reason not to chase every field a
  commercial maps product shows.

## Phased implementation plan

### Phase 1 — Cluster click-to-expand

**Scope**: the handler above, plus `pointer` cursor on hover. [x] Done.
**Done when**: [ ] clicking a cluster smoothly zooms/centers to the point
where it starts splitting apart — verified live on `dream-of-north`'s
densest clusters (the Rhineland stretch). **Not yet verified live** —
no browser/production access from this sandbox; left for the user's
next deploy.
**Testing**: manual only, same reasoning as every other MapLibre
interaction phase in this project's docs — client-side WebGL, not
meaningfully unit-testable.

### Phase 2 — Real icons via runtime-generated images

**Scope**: `registerCategoryImages()`, switch the unclustered layer from
`circle` to `symbol`, re-register images after theme swap. [x] Done.
**Done when**: [ ] individual (unclustered) amenities show real category
icons matching the curated-POI icon set, on both light and dark themes,
before and after a theme toggle. **Not yet verified live**, same reason.
**Testing**: manual — same as Phase 1's reasoning.

### Phase 3 — Richer popups from already-stored tag data

**Scope**: `tags` added to `_amenities_to_geojson()`'s output;
frontend popup builder extended to conditionally show website/phone
links when present. [x] Done.
**Done when**: [x] an amenity with real `website`/`phone` tags (findable by
querying `nearby_amenities.tags` directly for a non-null example) shows
a clickable link in its popup; one without those tags shows the
same clean name/category popup as today, no empty placeholder rows.
Confirmed at the unit-test level
(`test_amenities_to_geojson_includes_tags_when_present`,
`test_amenities_to_geojson_tags_defaults_to_empty_dict_when_none`); the
frontend rendering of that data into an actual clickable link is
**not yet verified live** in a real browser, same reason as Phases 1-2.
**Testing**: unit test for `_amenities_to_geojson()` confirming `tags`
is now present in output properties — the one part of this phase that
*is* backend/testable, unlike Phases 1-2. Done
(`tests/unit/test_amenities_geojson.py`, 3 tests).

## Implementation notes

- **`buildAmenityPopupHtml` reads `props.tags` defensively**: a
  clustered GeoJSON *source* feature returned from a MapLibre click
  event serializes nested object properties (like `tags`) to a JSON
  string on the wire, not a live JS object — `amenityTags()` handles
  both shapes (parses if it's a string, uses it directly if a browser/
  MapLibre version ever hands back the object form) rather than
  assuming one.
- **HTML-escaping added for amenity popups** (`escapeHtml()`), not
  present on the existing curated-POI popup it's visually modeled on.
  Deliberate, not an inconsistency to "fix" on the POI side too: POI
  name/notes are the site owner's own curated content (trusted input);
  amenity name/tags are auto-discovered from OpenStreetMap, editable by
  anyone — different trust boundary, warrants the extra step even
  though it means the two popup builders aren't symmetric.
- **`categoryColorExpression()` removed**, not left dead: it built the
  `circle-color` match expression the unclustered layer used before
  Phase 2 switched that layer from `circle` to `symbol`. Nothing
  references it after the switch; kept it would have been dead code the
  next reader has to figure out is safe to ignore.
- **Icon re-registration ordering on theme swap**: `registerCategoryImages()`
  is called from a `map.once("styledata", ...)` handler set up just
  before `map.setStyle()`, not immediately after — `styledata` fires
  once the new style (including `transformStyle`'s carried-over layers)
  has actually been applied, the earliest point at which `addImage()`
  calls stick to the new style rather than silently landing on the
  outgoing one and being discarded.

## Summary

All three phases implemented. Cluster click now zooms/centers via
`getClusterExpansionZoom` (MapLibre's own canonical pattern). Unclustered
amenity points render real per-category icons via `map.addImage()` with
runtime-generated canvases — no sprite sheet, reusing the same Maki path
data already vendored for curated POI markers — re-registered after
every theme swap since `addImage()` doesn't survive `setStyle()`.
`_amenities_to_geojson()` now passes each amenity's raw OSM `tags`
through to the browser; the popup builder shows a name + category line
always, plus a website link and/or `tel:` phone link only when those
tags exist, with HTML-escaping added for this auto-discovered (not
curated) data.

`make ci`: 296 passed, 96.08% coverage, security checks clean.

## Recommended next steps

- **Live verification (all three phases)** — not possible from this
  sandbox: no browser, no ability to actually render a WebGL map or
  click through real interactions. Every "Done when" item above is
  unchecked for exactly this reason and needs the user's own browser
  against the real deployed page:
  - Click a dense cluster on `dream-of-north`'s Rhineland stretch —
    confirm it smoothly zooms/centers to the point it starts splitting
    apart, with a `pointer` cursor on hover beforehand.
  - Zoom into individual amenities — confirm real per-category icons
    render (not the old plain color-coded circles), matching the
    curated-POI icon set, on both light and dark theme, and that a
    theme toggle mid-session doesn't lose the icons (the re-registration
    ordering fix is the one part of this whole doc with no automated
    test coverage at all, backend or frontend).
  - Click an unclustered amenity with real `website`/`phone` OSM tags
    (findable via `SELECT * FROM nearby_amenities WHERE tags IS NOT NULL
    AND (tags->>'website' IS NOT NULL OR tags->>'phone' IS NOT NULL)
    LIMIT 5`) — confirm the link(s) render and actually work (opens a
    new tab / dials via `tel:`), and that an amenity without those tags
    shows the same clean name/category popup with no empty rows.
- Caught and fixed during implementation, not deferred: OSM's `phone`
  tag occasionally lists more than one number separated by `;`/`,` —
  `buildAmenityPopupHtml` now splits on that and builds the `tel:` href
  from only the first number, while still displaying the full original
  tag text so a reader needing the second number can see it. Still
  worth a live check against a real multi-number example if one turns
  up, since this was fixed by inspection, not against real OSM data.