# BulliExplorer — GIS Coverage Refactor

> Fixes a real production bug: the PMTiles basemap only covers a Black
> Forest/Germany regional extract, decided in `maps_gis.md` Phase 4 back
> when every planned post was a local ride. "Dream of North" (a planned
> 4,247km route to 71°N) exposed it — the map renders a gray void outside
> Germany. See `maps_gis.md` for the original architecture this corrects,
> and `cloudflare_r2_setup.md` for the R2 bucket this reuses.

---

## What actually broke, and what didn't — scope this precisely

Checked the code before assuming this was systemic. It isn't — it's one
static asset's coverage, not a design flaw in Maps & GIS itself:

| Component | Status | Evidence |
| --- | --- | --- |
| **PMTiles basemap file** | ❌ Broken | Only ever covered a Black Forest/Germany bounding box (`maps_gis.md` Phase 4's original decision). Norway isn't in the file — nothing to render there, hence the gray band. |
| Geocoding (`geo_sync.py`'s `_geocode`) | ✅ Fine | No `viewbox`/`countrycodes` restriction on the Nominatim call — confirmed by reading the function directly. Already fully global. |
| Map fit-to-route (`post.html`) | ✅ Fine | `center: [8.1, 48.1]` is explicitly commented *"Rough centre — overridden once the map loads and fits to the route"* — `fitBounds()` already adapts to any GPX geometry, anywhere. Not hardcoded to any region. |
| Distance/elevation stats (`gpxpy`) | ✅ Fine | Pure geometry math (`length_2d()`, `get_uphill_downhill()`), no geography assumption at all. |

**The fix is: replace one file, and add a safeguard so its coverage limits are never silently discovered by a reader again.** Not a rewrite of anything else in the Maps & GIS stack.

---

## The fix: Europe-scale extract, not a one-off corridor

Don't size the replacement for *this* trip (a Germany→Norway corridor) —
that just relocates the same bug to the next unplanned destination (the
Balkans, the Alps, wherever the next "big experiment" post goes, per
"Dream of North"'s own stated ambition of staged, increasingly distant
touring). The right fix is Protomaps' standard **Europe extract** —
covers essentially every plausible destination for a Germany-based rider
without the full ~107GB world file's storage/generation/management
overhead, which was already correctly rejected in the original
`maps_gis.md` decision for being disproportionate to this project's
actual needs.

**Worth knowing so file size doesn't cause new worry**: PMTiles serves via
HTTP range requests — a much larger file mostly costs more R2 *storage*
(still cheap, R2's free tier alone covers this comfortably) and longer
one-time generation/upload, not per-page load time. The browser only ever
fetches tiles for the current viewport, regardless of the total file size.

---

## The standing safeguard — turning this into a check, not a hope

This project has a track record of exactly this failure shape: a real
assumption silently breaking because nothing checked it (the
`TILES_URL`-not-deployed gap, the webhook-vs-`make deploy` desync found
during the R2 migration). The fix each time was the same: convert the
one-off bug into an automated check, not a note to remember. Same
approach here.

**Add a coverage check to the sync path**: when `geo_sync.py` parses a
GPX file, `gpxpy`'s `GPX.get_bounds()` already returns the track's
min/max lat/lon for free — no new computation needed, just read a value
that's already being touched. Compare it against a documented
`_TILE_COVERAGE_BOUNDS` constant (the Europe extract's actual bounding
box) and log a **warning**, not a failure, if the route falls outside it.
This surfaces the problem in sync/deploy logs the moment a route is
added, instead of a reader finding a gray map days or weeks later.

---

## Phased implementation plan

### Phase 1 — Generate and deploy the Europe-scale extract

**Scope**

- [ ] Generate the Europe PMTiles extract (Protomaps' standard tooling,
  one-time, not app code) — in progress as of this doc's writing.
- [ ] Upload to R2 under the existing `tiles/` prefix (same bucket,
  same CORS policy already configured — no new R2 setup needed).
- [ ] Update `TILES_URL` in the server's `.env` to point at the new
  file, if the filename/path changed from the original extract.
- [ ] `make deploy` if `TILES_URL`'s value changed the env var itself
  (not just the R2 object) — otherwise a container restart alone
  suffices, per the existing `static/` volume-mount fix from earlier
  in this project.

**Done when**

- The new file is reachable at its R2 URL — `curl -sI` returns `200`.
- File size is sanity-checked against Protomaps' published Europe-extract
  size estimate — confirms the right extract was generated, not
  accidentally the world file or a truncated one.

**Testing**

- No new automated test — this phase is a data asset swap, not code.
  Verification is Phase 2's job.

### Phase 2 — Verify against the actual route that exposed the bug

**Scope**

- [ ] Open "Dream of North" on the live site.
- [ ] Confirm the basemap renders correctly along the **entire** route —
  Germany through Denmark, Sweden, and up to 71°N in Norway — not just
  that `fitBounds()` zoomed to the right area (that part already worked;
  the tiles themselves are what's being verified now).
- [ ] Spot-check at least one other region the Europe extract should
  cover but no existing post touches yet (e.g. pan the map manually
  toward the Alps or the Balkans) — confirms the fix is genuinely
  Europe-wide, not narrowly patched for the Norway corridor specifically.

**Done when**

- The Norway route in "Dream of North" renders with a real basemap
  (roads, terrain, place names) for its entire length, on both mobile
  and desktop.
- The manual spot-check outside any existing post's route also renders
  correctly.

**Testing**

- Manual/visual only — basemap rendering is client-side and not
  meaningfully testable without a real browser, same reasoning already
  established in `media_storage_r2.md`'s Phase 4.

### Phase 3 — Add the coverage-check safeguard

**Scope**

- [x] `_TILE_COVERAGE_BOUNDS` constant in `app/services/geo_sync.py`
  (kept as a plain module constant, not env-configurable, per the
  reasoning already in this doc):

  ```python
  # Bounding box of the current PMTiles basemap extract (Europe, as of
  # the gis coverage-refactor fix documented in docs/dev/maps_gis.md).
  _TILE_COVERAGE_BOUNDS = {
      "min_lat": 34.0, "max_lat": 72.0,
      "min_lon": -25.0, "max_lon": 45.0,
  }
  ```

  (Corrected from this doc's own draft snippet, which cited a
  `gis_refactor.md` file that doesn't exist — this doc's actual name is
  `maps_gis.md`, used consistently in the real code comment.)
- [x] In `sync_route`, right after `_parse_gpx` returns — compares
  against the constant and `logger.warning(...)`s the route name, post
  id, and how far outside coverage it falls; sync continues normally
  either way. **Simpler than planned**: no need to call `gpxpy`'s
  `GPX.get_bounds()` at all — `_parse_gpx` already builds a Shapely
  `LineString` for the DB write, and `linestring.bounds` gives the same
  `(min_lon, min_lat, max_lon, max_lat)` for free, zero new computation,
  no signature change to `_parse_gpx` needed.
- [x] Documented above (this doc), cross-referenced from `geo_sync.py`'s
  module docstring isn't needed — the constant's own comment points
  here directly.

**Done when**

- [x] A fixture route with coordinates outside `_TILE_COVERAGE_BOUNDS`
  triggers the warning log during sync.
- [x] A fixture route safely inside the bounds does not.
- [x] Existing real posts (all currently within Europe) produce zero
  warnings — confirms the check doesn't cry wolf on content that's
  actually fine. Checked for real, not assumed: ran `_parse_gpx` +
  `_check_tile_coverage` against all three live posts' actual GPX data.
  `dream-of-north`'s Nordkapp reach bounds at `(6.55, 50.74, 25.97,
  71.17)` — comfortably inside the 72°N ceiling, confirming the extract
  covers the exact route that exposed this bug in the first place.

**Testing**

- Two new unit tests in `tests/unit/test_geo_sync.py`
  (`test_check_tile_coverage_warns_outside_bounds`,
  `test_check_tile_coverage_silent_inside_bounds`): call
  `_check_tile_coverage` directly with a hand-built `LineString`
  (San Francisco / Black Forest coordinates) rather than a full GPX
  fixture — simpler and just as direct a test of the actual check
  logic, consistent with this module's existing pure-function test
  style.

### Phase 4 — Close out

**Scope**

- [ ] Update `maps_gis.md`'s Phase 4 section: correct the coverage
  decision (Black Forest/Germany → Europe), with the reasoning above,
  and a note that geocoding/fit-bounds/stats were checked and confirmed
  unaffected — so a future reader doesn't have to re-derive that this
  was a scoped, contained bug.
- [ ] Update `buckets.md` if this affects bucket #1's status line (it
  shouldn't reopen the bucket — Maps & GIS is still "done," this is a
  data-coverage fix within an already-shipped feature, not new scope —
  but worth a one-line note for the historical record).

**Done when**

- `maps_gis.md` no longer states or implies Germany-only coverage
  anywhere.
- The full test suite passes with the two new coverage-check tests
  included.

---

## Explicitly out of scope

- **Re-litigating the original "no world file" decision.** Europe-scale
  is a correction of an under-scoped regional extract, not a reason to
  reopen the world-file-vs-extract debate that `maps_gis.md` already
  settled with clear reasoning (storage/management cost disproportionate
  to actual need). If a future trip genuinely leaves Europe, that's the
  moment to revisit, not now, speculatively.
- **Automated tile re-generation on route additions.** The coverage
  check (Phase 3) only warns — it doesn't attempt to auto-fetch new
  tiles or resize the extract. That would be real, speculative
  infrastructure for a problem that's now caught early and fixed
  manually in minutes, not worth automating preemptively.
- **A UI-facing warning to readers** (e.g. "map may be incomplete for
  this route") — the Phase 3 safeguard is for you, at publish/sync time,
  not a reader-facing feature. If this recurs often enough to need a
  reader-facing fallback, that's a different, larger conversation.
