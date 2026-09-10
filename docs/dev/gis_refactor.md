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

- [x] Generate the Europe PMTiles extract (`pmtiles extract`, bbox
  `-25,34,45,72`, maxzoom 14) — 23 GiB, generated locally from
  Protomaps' `20260908.pmtiles` daily build. Took two attempts — the
  first failed on a transient network read; an auto-retry wrapper
  script succeeded on attempt 2, ~25 minutes.
- [x] Uploaded to R2 under the existing `tiles/` prefix as
  `tiles/europe.pmtiles` — same bucket, same CORS policy, no new R2
  config needed, confirmed.
- [x] Updated `TILES_URL` in both local and the server's `.env` to
  `pmtiles://https://pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev/tiles/europe.pmtiles`.
- [x] `make deploy` run to pick up the new `TILES_URL` value.

**Done when**

- [x] The new file is reachable at its R2 URL — `curl -sI` returned
  `200`, `Content-Length: 24487117444` (matches the 23 GiB extract),
  `Accept-Ranges: bytes` present (required for PMTiles' range-request
  reads).
- [~] File-size sanity check — **no such published Protomaps estimate
  exists to compare against** (checked, came up empty), so this
  specific criterion can't be satisfied as worded. Did a rough
  order-of-magnitude check instead: 24 GB for Europe vs. the world
  file's ~107 GB (per `maps_gis.md`'s own original sizing note) is
  plausible, not a "wrong file" red flag — not the same as the intended
  check, but the closest available substitute.

**Real incident during this phase, caught and fixed**: `make deploy`'s
`RSYNC_EXCLUDE` didn't exclude `static/pmtiles/`, so the first deploy
attempt tried to rsync the 23 GiB extract to the server too and filled
its disk (38 GB total, 11 GB free at the time) mid-transfer —
`rsync: ... No space left on device`. Self-terminated cleanly, no data
loss, all containers stayed healthy throughout. Root-caused (production
never reads a local pmtiles file — `TILES_URL` is a browser-side URL
pointing at R2) and fixed in the `Makefile`; the corrected deploy
succeeded cleanly on retry.

**Testing**

- No new automated test, as planned — this phase is a data asset swap,
  not code. Verification was Phase 2's job.

### Phase 2 — Verify against the actual route that exposed the bug

**Scope**

- [x] Open "Dream of North" on the live site.
- [x] Confirm the basemap renders correctly along the route — user
  confirmed after a hard refresh: "works as designed."
- [ ] Spot-check at least one other region the Europe extract should
  cover but no existing post touches yet (e.g. pan the map manually
  toward the Alps or the Balkans).

**Done when**

- [~] The Norway route in "Dream of North" renders with a real basemap
  for its entire length. Confirmed on desktop via the user's hard
  refresh. Mobile not explicitly confirmed — not the same as "both,"
  as originally worded here.
- [ ] The manual spot-check outside any existing post's route — not
  done. This is inherently a live-browser check; the agent can't drive
  it.

**Testing**

- Manual/visual only, as planned — basemap rendering is client-side and
  not meaningfully testable without a real browser, same reasoning
  already established in `media_storage_r2.md`'s Phase 4.

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

- [x] Update `maps_gis.md`'s Phase 4 section: correction note added
  in-place (not a rewrite of the historical record) pointing at this
  doc, with the reasoning and the geocoding/fit-bounds/stats-unaffected
  confirmation.
- [x] Update `buckets.md` bucket #1: one-line note added, bucket stays
  ✅ done, not reopened.

**Done when**

- [x] `maps_gis.md` no longer states or implies Germany-only coverage
  as the *current* state — the historical Phase 4 section is left
  intact (it was correct for its time) with a clearly-labeled
  correction note directly beneath it.
- [x] The full test suite passes with the two new coverage-check tests
  included — `make ci` green, 213 tests, 92%+ coverage.

**Left over**

None for this phase's own scope. (Phase 2's manual spot-check and
mobile confirmation remain open — tracked there, not duplicated here.)

**Summary**

Corrected `maps_gis.md` in place rather than rewriting its history: the
original Black Forest/Germany decision is left as-is (it was the right
call for what was planned then), with a dated correction note added
immediately below it pointing to this doc. Added a one-line note to
`buckets.md` bucket #1 — bucket stays done, not reopened, since this is
a data-coverage fix within an already-shipped feature, not new scope.

**Recommended next steps**

- Close Phase 2's two open items when convenient: the manual pan/zoom
  spot-check toward the Alps or Balkans, and an explicit mobile check of
  "Dream of North" (only desktop was confirmed via the hard refresh).
  Both are quick, low-risk, and don't block anything else.
- No code or infra work is blocked on either of those — this refactor's
  actual engineering (extract, upload, deploy, safeguard, tests) is
  fully shipped and verified. What's left is purely visual confirmation.
- Worth remembering for next time a `.pmtiles`-sized (or similarly
  large) asset needs to move: the `RSYNC_EXCLUDE` gap that caused the
  first deploy failure is fixed now, but it's a reminder to sanity-check
  `make deploy`'s file list before running it on the next multi-GB
  asset, rather than assuming exclusions are exhaustive.

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
