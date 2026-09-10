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
- [ ] Using a tile inspector (e.g. PMTiles' own viewer at pmtiles.io, or
  MapLibre's own feature-query on a loaded layer), inspect real
  `kind=cycleway`/`kind=path`/`kind=track` features from the current
  Europe extract, on a handful of real, known-locations (e.g. any
  street known to have a marked cycleway).
- [ ] Record which properties are actually present per feature —
  specifically checking for `surface`, `smoothness`, `cycleway` (lane
  type), and `bicycle` (access) tags, not just `kind`.

**Done when**
- A concrete, written answer exists to: "does `surface` survive into
  the tiles, yes or no" — this is the fork point for Phase 3.
- The exact `kind` values actually present in the extract are confirmed
  (docs list what's *possible*; this confirms what's *actually there*
  for this specific Europe extract).

**Testing**
- No automated test — this is a one-time data-discovery step, output is
  a short written finding in this doc's Phase 0 summary, not code.

### Phase 1 — Cycling-aware basemap style layers

**Scope**
- [ ] New `cyclingLayers(flavor)` function (co-located with
  `routeLineColor(flavor)` in `post.html`'s existing script, same
  pattern) — returns MapLibre layer definitions filtered on
  `kind == 'cycleway'`, styled distinctly (CyclOSM-inspired: a
  saturated, high-contrast color against the base road palette,
  dashed/dotted variant for `kind == 'path'`/`'track'` to distinguish
  unpaved-likely routes from dedicated cycleways).
- [ ] Both light and dark flavor variants — reuse the existing
  flavor-aware pattern already established for the route line color,
  don't hardcode one theme.
- [ ] If Phase 0 confirms `surface` is present: add a subtle
  paved/unpaved visual distinction to these same layers (e.g. a
  slightly different dash pattern), scoped to what's honestly
  achievable from tile data alone — **not** the full route-level
  surface-sync feature, that's Phase 3's fork, not this phase's scope
  creep.
- [ ] Appended to the existing `basemaps.layers()` array, not replacing
  it — confirmed additive per the technical foundation above.

**Done when**
- Cycleways/paths/tracks render visibly distinct from regular roads on
  both light and dark flavors, verified on a real area with known
  cycling infrastructure (not just the route line itself — the
  *surrounding* map context).
- No regression to existing route-line/POI-marker rendering — the new
  layers are additive, verified by comparing before/after screenshots
  of an existing post.

**Testing**
- No meaningful automated test for visual rendering (same reasoning
  established in `media_storage_r2.md`'s Phase 4 and `gis_refactor.md`'s
  Phase 2 — this is client-side WebGL rendering, not testable without a
  real browser). Manual visual verification, documented with
  screenshots in the Summary.

### Phase 2 — Full-screen map modal

**Scope**
- [ ] Expand icon overlaid on the map's corner (existing pattern:
  MapLibre's built-in `NavigationControl`-adjacent custom control, or a
  simple absolutely-positioned button — match whatever's visually
  consistent with the site's existing icon language from
  `ui_ux_refresh.md`'s design tokens).
- [ ] Clicking it moves the **same** MapLibre instance into a
  fixed-position, full-viewport overlay — critically, do not
  re-initialize a second map instance (wasteful, and risks the two
  instances drifting out of sync). Resize the existing container and
  call `map.resize()` — MapLibre's documented method for this exact
  case.
- [ ] Escape key and a visible close button both dismiss it, returning
  the map to its inline size (again via `map.resize()`, not
  re-creation).
- [ ] Focus trap while open, `aria-modal="true"` — matches the WCAG 2.2
  AA target already committed to project-wide.

**Done when**
- Expanding and collapsing preserves the current pan/zoom/route-fit
  state exactly — no jump or reset.
- Keyboard-only: Tab cycles only within the modal while open, Escape
  closes it, focus returns to the expand button on close (not lost to
  `<body>`).
- Screen-reader pass: modal is announced on open, dismissible, and
  doesn't trap a screen-reader user who can't find/use Escape.

**Testing**
- Manual keyboard-only and screen-reader passes, per the same standard
  already used for Phase 5 of `ui_ux_refresh.md` — no automated
  equivalent for this class of interaction.

### Phase 3 — Surface-type visualization: fork on Phase 0's finding

**If Phase 0 found `surface` tags are NOT reliably present in the
tiles** (the likely outcome, given Protomaps' own "some keys may only be
present in a subset of features" caveat): **stop here, formally.** Real
surface-synced elevation profiles need map-matching against a properly
surface-tagged road network — a genuine geospatial project (evaluate
existing OSS routing/map-matching services, likely a paid or
self-hosted OSRM/Valhalla-style engine), not a styling task. Document
this as its own future concept doc if it's ever picked up — don't let it
quietly become scope inside this one.

**If Phase 0 found `surface` tags ARE present for a meaningful share of
features**: a narrower, honestly-scoped version becomes feasible without
map-matching:

**Scope** (only if the fork above resolves this direction)
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

## Explicitly deferred, regardless of Phase 3's fork

- **Full route-level surface-synced elevation profile chart** (the
  actual Komoot/RideWithGPS-grade feature) — needs map-matching, a real
  geospatial project. Resolves `ui_ux_refresh.md`'s deferred "interactive
  elevation profile chart" item by making explicit *why* it's still
  deferred: not just "a chart is more work than a stats row" (the
  original reasoning) but "the surface-sync version specifically needs
  infrastructure this project doesn't have yet."
- **CyclOSM-style bike-specific POI icons** (bike shops, repair
  stations, water points as distinct icons vs. generic markers) — cheap
  to add later on top of Phase 1's layers, not blocking, not included
  here to keep this phase's scope contained.
- **A custom/enriched tileset** (building your own Planetiler-based
  tiles with guaranteed surface tags, rather than relying on what
  Protomaps' general-purpose extract happens to include) — real
  infrastructure, only worth it if Phase 3's fork lands on "not
  present" and the surface feature is later judged worth the investment
  anyway.