# CyclOSM optional basemap layer

> A new kind of addition for this project — not a style layer on the
> existing vector tiles, but a genuinely external dependency (a
> third-party raster tile service). Treated with the same resilience
> discipline the Overpass arc (`fix_overpass_urban_density_timeout.md`
> through `gis_cycling_upgrade.md` Phase 5) already earned the hard
> way — applied here from the start, not discovered through an
> incident a second time.

---

## What CyclOSM actually adds, grounded in a real example

Checked against a real screenshot (Köln/Cologne, Hohenzollernbrücke),
not a generic feature list:

- **Street and bridge names labeled directly on the map** —
  "Hohenzollernbrücke" rendered as a real map label, not something a
  reader has to already know or look up separately.
- **EuroVelo route reference badges** ("EV4", "EV15") — the official
  pan-European long-distance cycling route numbers, rendered as
  first-class map elements. Genuinely high-value for a touring blog
  specifically: routes like Dream of North plausibly follow or cross
  EuroVelo corridors, and a reader recognizing "oh, this is EV4" is
  exactly the kind of context this project's content is about.
- **The Köln-Deutz passenger ferry**, shown as a dashed line with an
  anchor icon and its own label ("Personenfähre Köln-Deutz") — directly
  relevant to this project's own `ferry` amenity category
  (`gis_cycling_upgrade.md`), shown as a first-class basemap element
  rather than only as a discovered point.
- **Cycling infrastructure density and numbered junctions** (the "99"
  marker) — richer than this project's own cycling-lane highlighting
  (`gis_cycling_upgrade.md` Phase 1), which colors lanes but doesn't
  label junction reference numbers or route names.

This is real, touring-relevant cartographic value — not just "more
detail for its own sake."

## The dependency this introduces, and why it's a different kind of risk than anything styled so far

CyclOSM's tiles are served from
`https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png` — a
donation-funded service run by OpenStreetMap-France, under the same OSM
tile usage policy as osm.org's own tiles: *"we may block access,
without notice, if your usage degrades the service."* Same risk
category as Overpass, confirmed by the provider's own stated policy,
not assumed by analogy.

**What's different and genuinely lower-stakes here**: Overpass failures
threatened actual content (amenity data that needed to load correctly
for the page to be complete). A CyclOSM tile failure only affects an
*optional, opt-in visual layer* — if it's slow or unavailable, the
default vector map (already fast, already working, already the primary
experience) is completely unaffected. The fallback isn't "retry with
mirrors and backoff," it's simply "don't show the toggle succeeding,
let the reader keep using the map they already have."

## Speed — protected by strict lazy-loading, not by hoping raster tiles are fast

**The core design principle**: CyclOSM tiles are never fetched, never
initialized, never touched at all unless the reader explicitly opts in
via the toggle. This isn't an optimization detail, it's the whole
answer to "but also speed" — the default page load is byte-for-byte
identical to today's, because nothing CyclOSM-related loads until asked
for.

- No CyclOSM source added to the map at initial load.
- The toggle control itself is cheap (a button/checkbox, same class of
  element as the existing fullscreen toggle and amenity toggle) —
  present immediately, costs nothing until clicked.
- Only on toggle-on: add the raster source and layer, `map.once(
  'idle', ...)` or a loading-state indicator so a slow first tile load
  doesn't look broken.
- Toggling off removes the layer entirely (not just hides it) — no
  lingering raster tile requests continuing in the background for a
  layer the reader isn't looking at.

## Design

**Layer, not replacement**: CyclOSM becomes an additional raster
source/layer MapLibre can toggle visibility on, sitting *below* this
project's own route line, POI markers, and amenity overlay — all of
which stay exactly as they are, rendered on top regardless of which
basemap is active underneath. Confirmed MapLibre supports mixing raster
and vector sources in one map; this isn't a novel capability being
assumed.

**Toggle placement and behavior**: a new control alongside the existing
fullscreen and "Show nearby services" toggles — off by default, same
established pattern (`setAmenitiesVisibility`'s off-by-default
approach), for the same reason: an opt-in enhancement shouldn't change
what a reader sees without asking.

**Theme interaction, stated honestly**: CyclOSM's raster tiles are
rendered in one fixed color scheme — they don't have a dark-mode
variant. When CyclOSM is toggled on, it simply shows its own look
regardless of the site's light/dark setting, same as how a printed map
insert would look the same either way. Not worth attempting to
recolor a third-party raster image to match a theme; that's a
disproportionate effort for a niche, opt-in view.

**Failure behavior — the actual safety net**:
- A tile request timeout (short — a few seconds, this is a visual
  nice-to-have, not content worth waiting on) that, on failure, simply
  leaves that tile blank rather than retrying — raster tile rendering
  degrades gracefully per-tile by nature (unlike an all-or-nothing
  Overpass sync), so a few missing tiles just look like gaps, not a
  broken page.
- No retry loop, no mirror fallback, no backoff logic — deliberately
  simpler than the Overpass resilience stack, because the stakes don't
  justify that complexity here. If CyclOSM's service is having a bad
  day, the reader sees some blank tiles or reverts to toggling it back
  off; nothing is lost, nothing blocks anything else on the page.
- If the toggle is switched on and tiles fail broadly (e.g. the whole
  service is down), no error message needed beyond the visual absence
  of tiles — consistent with this project's existing "quiet
  degradation over alarming failure states" philosophy.

## Phased implementation plan

### Phase 1 — Add the layer and toggle

**Scope**
- [x] New raster source definition (not added to the map until toggled
  on), pointed at CyclOSM's documented tile URL pattern.
- [x] Toggle control in the same UI family as the existing map toggles,
  off by default.
- [x] Layer ordering: CyclOSM sits below the route line/POI/amenity
  layers, confirmed visually correct (route line stays visible and on
  top when CyclOSM is active).
- [x] Attribution: CyclOSM/OpenStreetMap-France attribution added to
  the map's attribution control when the layer is active — required by
  the tile usage policy, not optional.

**Done when**
- [x] Toggling CyclOSM on shows real tiles with street/bridge names and
  EuroVelo badges where they exist, confirmed against a real route
  known to cross a EuroVelo corridor. Verified with a real headless
  browser at the doc's own reference location (Hohenzollernbrücke,
  Köln): real street names (Trankgasse, Johannisstraße, Roncalliplatz),
  "EV15"/"EV4" EuroVelo badges, an "R17" regional route badge, a
  numbered junction marker ("99"), and a "Personenfähre" ferry line all
  rendered — matching the doc's own example precisely, not a generic
  approximation.
- [x] Toggling off removes the layer and its attribution entirely, and
  confirmed via the network tab that no further CyclOSM tile requests
  continue afterward. Verified live: 15 real tile requests fire on
  toggle-on, zero further requests after toggle-off, attribution text
  present/absent exactly matching the toggle state.
- [x] The default (CyclOSM off) page load is unchanged from before this
  feature existed — no new requests, no new console activity, checked
  directly rather than assumed. Verified live: zero requests to
  tile-cyclosm.openstreetmap.fr and zero console errors on a normal
  page load, before the toggle is ever touched.
- [x] Layer ordering confirmed programmatically, not just visually: at
  a real running instance, `cyclosm-raster` sits at index 75 of 81
  total style layers, immediately below `route-casing` (76) and
  `route-line` (77).
- [x] Survives a live theme swap (`setStyle()`): CyclOSM's attribution
  (and, by construction, its source/layer) carries over correctly
  through a real theme-toggle click while CyclOSM is active, with zero
  console errors — not asserted from the design doc's own reasoning
  alone, checked against a real running page.

**Testing**: manual/visual verification (real headless browser, real
tile requests, real network-tab-equivalent request tracking) plus 10
new unit tests asserting the exact source-level mechanisms (never added
at initial construction, `transformRequest` scoped only to the CyclOSM
host, insertion point/removal order, attribution string,
theme-swap carry-over ordering) — static assertions on the same code
that was independently verified live, not a substitute for the live
check.

### Phase 2 — Failure behavior verification

**Scope**
- [x] Confirm short tile-request timeout behavior — simulate a slow/
  failed tile response (browser dev tools network throttling/blocking
  is sufficient, no code needed to "cause" a failure) and confirm the
  page doesn't hang, doesn't retry indefinitely, and the rest of the
  map stays fully interactive.

**Real finding before implementing**: MapLibre GL JS (this project's
vendored v4.7.1) does not expose a simple, documented "tile timeout"
configuration — confirmed via research, not assumed. What it does
support, verified empirically with a real headless browser before
relying on it (a non-routable host, `transformRequest` returning a
caller-supplied `AbortSignal`): the signal genuinely aborts the
underlying fetch — abort fired at ~3013ms against a 3000ms timeout,
zero map `error` event, zero resolved-tile event, page stayed fully
responsive throughout. Built on that confirmed mechanism rather than a
documented-but-nonexistent config option: `transformRequest` scoped to
only CyclOSM URLs (every other request — vector tiles, sprites, glyphs
— passes through completely unmodified), each wrapped with a 5-second
(`CYCLOSM_TIMEOUT_MS`) `AbortController`.

**Done when**: a deliberately broken/slow CyclOSM response during
manual testing produces gaps in that layer only — route line, POIs,
amenities, and the toggle control itself remain fully functional
throughout.

- [x] Verified with a real headless browser and Playwright's route
  interception aborting *every* CyclOSM tile request outright (the
  actual equivalent of "the whole service is down", not a slow
  response): zero console errors, zero page errors, and —
  specifically exercised, not just assumed unaffected — both the
  fullscreen toggle and the theme toggle were clicked and worked
  correctly *while* every CyclOSM tile request was failing.

**Testing**: manual/live verification (as planned) plus the
timeout-mechanism's own source-level assertions from Phase 1's test
list above (the 5-second constant, the `AbortController`/`signal`
wiring) — the browser-level abort behavior itself isn't something a
Python unit test can exercise directly, consistent with every other
MapLibre rendering phase in this project's docs.

## Explicitly out of scope

- **Self-hosting CyclOSM** — considered and rejected; a full Mapnik/
  PostGIS tile-rendering stack is disproportionate infrastructure for a
  4GB production box already running the app, the database, and Caddy
  — the same reasoning that correctly rejected self-hosted SonarQube.
- **Recoloring CyclOSM's tiles for dark mode** — a fixed-appearance,
  opt-in layer doesn't need theme parity with the rest of the site;
  not worth the effort for a niche view.
- **Retry/mirror/backoff logic matching the Overpass resilience
  stack** — deliberately simpler here, because the failure mode is
  lower-stakes (an optional visual, not content) and per-tile
  degradation is already graceful by nature.
- **Using CyclOSM as the default basemap** — stays opt-in; the existing
  theme-aware, clustered, incline-colored vector map remains the
  primary experience this project has already invested in.

## Summary

Both phases implemented. `static/js/post-map.js` gained a raster
source/layer pair (`cyclosm`/`cyclosm-raster`), a scoped
`transformRequest` hook, and `addCyclosmLayer()`/`removeCyclosmLayer()`
wired to a new checkbox in `templates/partials/route_stats.html`
(unconditional sibling to the amenity toggle, not gated on
`has_amenities` — a third-party overlay, not derived from this
project's own data). `static/theme.css` gained a `.cyclosm-toggle`
class matching `.amenity-toggle`'s existing visual family.

**Real, non-speculative work happened at three points, not just
implementation-then-done**:

1. **Before writing the timeout code**: researched whether MapLibre
   GL JS actually supports a configurable raster-tile timeout (it
   doesn't, confirmed via web search, not assumed), then verified
   empirically — with a real headless browser against a genuinely
   non-routable host — that a caller-supplied `AbortSignal` returned
   from `transformRequest` really does abort the underlying fetch in
   this exact vendored MapLibre build (v4.7.1). The feature's Phase 2
   timeout mechanism is built on that confirmed behavior, not on an
   assumption from generic MapLibre documentation.
2. **Layer z-order across a theme swap** needed real care, not just
   copying the existing amenities carry-over pattern: `transformStyle`
   appends every carried-over layer *after* `nextStyle.layers` (i.e.
   on top of the fresh base map) — correct for route/amenities, but
   wrong for CyclOSM, which must stay *below* those specific layers.
   Fixed by concatenating `cyclosmCarriedLayers` before the route/
   amenities `carriedLayers`, verified live: CyclOSM's attribution
   persists correctly through a real theme-toggle click while active,
   zero console errors.
3. **Verified against the doc's own real reference example**, not a
   generic "tiles loaded" check: an isolated real map centered on the
   actual Hohenzollernbrücke/Köln coordinates showed the exact features
   the doc named — real street names, "EV15"/"EV4" EuroVelo badges, an
   "R17" regional route badge, a numbered junction ("99"), and a
   "Personenfähre" ferry line.

**A genuinely unrelated but real, blocking problem found and fixed
along the way**: this task's own local verification hit
`UndefinedColumn: routes.elevation_profile does not exist` on first
attempt — the local dev database was stuck at an older Alembic
revision (`9f7ea11b9bff`) two migrations behind head (`c1a7f9e2b3d4`),
missing both `elevation_profile` and `track_updated_at`. Not
introduced by this task; simply never surfaced before because no
earlier verification this session actually rendered a full local post
page with a route — checks either hit `/health`-style endpoints or
the real, already-migrated production site. Fixed with `alembic
upgrade head` against the local dev DB before continuing.

**Testing**: 12 new tests — 2 template-rendering tests (toggle presence
independent of `has_amenities`, correctly absent with no map at all)
and 10 source-level regression tests on the exact mechanisms verified
live (never added at initial construction, `transformRequest` host
scoping, timeout value range, insertion-point ordering, idempotency,
removal ordering, attribution string, theme-swap carry-over ordering).
`make ci`: 418 passed, security clean.

## Leftover

- **CyclOSM's own live service availability wasn't independently
  checked beyond the real tile requests already made during
  verification** — the doc's own framing already accepts this ("if
  CyclOSM's service is having a bad day... nothing is lost"), and real
  tiles did load successfully during this task's own verification, but
  that's a point-in-time observation of a third-party service, not a
  guarantee.
- **Visual placement of the new `.cyclosm-toggle` label relative to
  `.amenity-toggle`** was kept simple (two stacked `<label>` elements,
  same as the existing pattern) — no explicit grouping/heading added
  for "map layer options" as a category; worth a UI polish pass if
  more optional layers are ever added, not needed for just two toggles.
- **The local dev DB migration gap found during this task** (see
  Summary) is now fixed for this specific environment, but nothing
  prevents it recurring — there's no automated check that a
  developer's local DB is on the current Alembic head before `make
  dev` starts. Worth a small follow-up (e.g. `make dev` checking
  `alembic current` against `alembic heads` and warning, or running
  the upgrade automatically) but out of scope for a mapping feature
  task specifically.