# Fix: skip amenity re-sync when a route's geometry hasn't changed

> Root cause and fix plan for Dream of North re-running its full 21-chunk,
> ~30-minute Overpass discovery on every trigger — container restart,
> `/internal/resync`, and every webhook push — regardless of whether the
> route's actual physical path changed at all. Complementary to, not a
> replacement for, `gis_cycling_upgrade.md`'s existing 15-minute cooldown.

---

## Evidence

Two full syncs of `route_id=3` (Dream of North) in the same log session,
two hours apart:

- **15:31** — container restart. Full 21-chunk sync, ~30 minutes,
  chunk 1 alone returns 6,942 amenities for the Rhineland bbox.
- **17:32** — a webhook push. The commit only touched
  `dream-of-north.md`, `feldberg-summit-loop.md`, and
  `sunday-gravel-loop.md` — **post content, no GPX file**. Dream of
  North's route geometry is provably unchanged. And yet: the exact same
  21-chunk sync runs again from scratch — chunk 1 re-fetches the same
  physical Rhineland stretch, gets 6,942 amenities (one more than
  before — real-world OSM data drift, not anything BulliExplorer did),
  and rewrites it.

Ninety minutes and dozens of Overpass calls spent re-confirming data
that hadn't meaningfully changed.

## Root cause — confirmed in the code, not inferred

`sync_amenities_for_routes()` (`background_sync.py`) takes a plain list
of route IDs and runs full discovery for every one, unconditionally.
The existing check in `geo_sync.py` (`"Skipping Overpass amenity sync
for route_id=X — last attempt was ... ago (cooldown 0:15:00)"`) only
prevents *rapid, back-to-back* attempts on the same route — it says
nothing about whether the route actually needs re-syncing at all. A
trigger two hours after the last one sails straight past that cooldown
and re-runs everything.

**Nothing in `Route` tracks when the geometry itself last changed.**
The content-sync idempotency check *does* correctly detect a real track
change — comparing WKB hex strings — but only sets a local `changed`
flag inside one function call; it's never persisted anywhere. There's
no existing signal to build a "is this route's amenity data still
fresh" check on without adding one.

## The two checks are genuinely different things, worth keeping distinct

- **Cooldown** (existing, 15 minutes): anti-burst protection. Stops the
  same route being hammered by rapid, repeated attempts — the incident
  it was built for (a testing burst that got the server IP-blocked).
- **Freshness** (this doc, proposed: days, not minutes): anti-redundant-
  work protection. Stops a route whose physical path hasn't changed
  from re-running expensive, unnecessary Overpass discovery just because
  *something else* (unrelated post content) triggered a sync.

Both live at the same check point in `sync_amenities`, checked together,
serving different timescales and different purposes. Fixing one
wouldn't have caught what the other catches.

## Design

**New column**: `Route.track_updated_at: datetime | None` — set only in
the specific branch of `post_sync.py`'s route-upsert logic that already
detects a real track change (`if str(existing.track) != str(new_track):`),
and on initial insert. Deliberately **not** derived from the broader
`changed` flag, which also fires for `description`/`name` edits — a
prose-only edit must not look like a geometry change, or this fix
defeats its own purpose.

**New check in `sync_amenities`**, alongside the existing cooldown
check: skip the whole discovery run if *both* hold:

- `amenities_synced_at` is not null and is **after** `track_updated_at`
  (the last amenity data reflects the route's current physical path,
  not a stale one), **and**
- `amenities_synced_at` is within a freshness window (proposed: 7
  days — real-world amenities like campsites and shelters don't
  meaningfully change hour to hour, but a route left untouched for
  months should still eventually re-check rather than trust data
  forever).

Log this distinctly from the cooldown skip (`"Amenity data for
route_id=X still fresh (synced Yd ago, geometry unchanged since Zd
ago) — skipping"`) so future log review can tell the two apart, same
as this investigation needed to.

**Interaction with partial failures**: use the existing
`amenities_synced_at` (set on every *attempt*, success or failure) as
the freshness reference rather than requiring a fully-clean run. Dream
of North routinely completes 20/21 chunks, not 21/21 — treating a
near-complete run as "not fresh enough to skip" would mean this fix
almost never actually applies to the one route it matters most for.
Accepting "recently attempted" as good enough for the long freshness
window is the right trade-off; the short cooldown still separately
governs how soon a genuinely failed chunk gets retried.

## Phased implementation plan

### Phase 1 — Track the geometry-change timestamp

**Scope**
- [x] `track_updated_at` column + Alembic migration
  (`alembic/versions/c1a7f9e2b3d4_add_track_updated_at_to_routes.py`).
- [x] Set it in `geo_sync.py`'s `sync_route` — on initial insert, and in
  the existing track-comparison branch only, never from the generic
  `changed` flag. (Note: the doc originally said "`post_sync.py`'s
  track-comparison branch" — that logic actually lives in
  `geo_sync.py`'s `sync_route`, called *from* `post_sync.py`; corrected
  while implementing, no design change.)
- [x] Backfill: existing routes get `track_updated_at` set to `now()`
  in the migration's `upgrade()` (`UPDATE routes SET track_updated_at =
  now() WHERE track_updated_at IS NULL`) — the conservative default
  this doc specified, confirmed on the actual production deploy (see
  Summary below): every existing route's next amenity sync attempt ran
  normally rather than being skipped, because the migration's `now()`
  postdated each route's pre-existing `amenities_synced_at`.

**Real bug found and fixed while building this** (not in the original
 plan, but blocking it): `sync_route`'s existing geometry-change
 detection — `str(existing.track) != str(new_track)` — was **always
 true**, even for a byte-identical, unchanged track. `existing.track`
 round-trips through PostGIS as EWKB (SRID embedded in the header,
 e.g. `0102000020e6100000...`) while a freshly built `from_shape(...)`
 is plain WKB with no such header (`010200000003000000...`) — the two
 string forms never matched, for any route, ever. This was silently
 rewriting every Route row on every single re-sync regardless of
 whether the GPX actually changed — wasted writes, and fatal to this
 fix specifically: `track_updated_at` would have been bumped on every
 sync too, permanently defeating the freshness check before it did
 anything. Confirmed by direct reproduction against the real Postgres
 container, not guessed. Fixed by re-hydrating `existing.track` via
 `to_shape()` first and comparing Shapely's own `.wkb` on both sides —
 an apples-to-apples comparison, unlike the old one.

**Done when**
- [x] A fixture test: updating a route's `description` only does not
  touch `track_updated_at`; updating its `track` does. —
  `test_track_updated_at_unchanged_on_description_only_edit` and
  `test_track_updated_at_bumped_on_real_track_change` in
  `tests/integration/test_geo_sync_integration.py` (plus
  `test_track_updated_at_set_on_initial_insert` for the insert case).
- [ ] A live content-only edit (prose change, no GPX) confirms
  `track_updated_at` stays unchanged in the DB — **not yet verified
  live**; the fixture test above exercises the identical code path
  (`sync_route`'s update branch with an unchanged GPX and a changed
  `description`), but hasn't been observed against a real webhook push
  in production. See Leftover.

**Testing**
- Integration tests in `tests/integration/test_geo_sync_integration.py`
  (needs the real PostGIS container — the EWKB/WKB bug above is
  specifically the kind of thing a fixture-only/no-DB unit test would
  never catch, since it only appears after an actual round-trip through
  Postgres).

### Phase 2 — The freshness check itself

**Scope**
- [x] `_AMENITY_FRESHNESS_WINDOW = timedelta(days=7)` in `geo_sync.py`.
- [x] The skip condition in `sync_amenities`, alongside the existing
  cooldown check, with the distinctly-worded log message above
  (`"Amenity data for route_id=%d still fresh ... — skipping"`).
  `track_updated_at is None` (a row somehow missing the migration
  backfill) is treated as "unknown, therefore not provably unchanged"
  — never skips — the same conservative default the backfill itself
  uses.

**Done when**
- [x] A fixture test: a route synced 2 hours ago with unchanged geometry
  is skipped by the freshness check (not just the cooldown, which would
  also technically still apply at 2 hours — the test needs to isolate
  which check actually fired, e.g. via the distinct log message). —
  `test_sync_amenities_freshness_skips_when_geometry_unchanged` (unit,
  asserts the distinct log message and absence of the cooldown one) and
  `test_amenity_freshness_skips_resync_for_unchanged_route_outside_cooldown`
  (integration, full `sync_posts` → `sync_route_amenities` pipeline).
- [x] A fixture test: a route whose `track_updated_at` is *after* its
  last `amenities_synced_at` (a genuine geometry change) is **not**
  skipped, even if the timestamps are close together — freshness must
  never mask a real change. —
  `test_sync_amenities_freshness_does_not_skip_when_track_changed_after_sync`
  (unit) and `test_amenity_freshness_does_not_skip_after_real_track_change`
  (integration).
- [ ] Live: trigger a content-only webhook push for Dream of North
  within the freshness window, confirm the log shows the new skip
  message and zero Overpass calls happen, instead of the ~30-minute
  chunk sequence seen in this investigation's evidence. **Not yet
  verified live** — the fix is deployed to production (see Summary),
  but no webhook push has landed since deploy to observe this directly.
  See Leftover.

**Testing**
- Unit tests in `tests/unit/test_geo_sync.py`
  (`test_sync_amenities_freshness_*`, three cases: skip when unchanged
  and fresh, don't skip when geometry changed after sync, don't skip
  once the freshness window itself has expired), same mocked-transport
  pattern as every other Overpass-adjacent test in this project — no
  real network calls, fixture timestamps asserted against the skip
  logic directly. Two matching integration tests exercise the same
  scenarios through the real `sync_posts()` → `sync_route_amenities()`
  pipeline against the PostGIS container.

## Explicitly out of scope

- **Partial/per-chunk freshness** (skip only the chunks whose specific
  sub-area didn't change, re-sync the rest) — real added complexity for
  a case that doesn't come up in practice: a route's geometry either
  changed or it didn't, as a whole GPX re-upload, not chunk-by-chunk.
- **Making the freshness window configurable per-route** — a single
  project-wide constant is enough; nothing about this project's actual
  routes calls for per-route tuning, and it's one more thing to
  document and get wrong.

## Summary

Both phases implemented. `Route.track_updated_at` is now set on initial
insert and, in `sync_route`'s update branch, only when the route's
geometry has genuinely changed — a content-only edit (description,
name) never touches it. `sync_amenities` gained a second skip check
alongside the existing 15-minute cooldown: a route whose most recent
sync attempt is within `_AMENITY_FRESHNESS_WINDOW` (7 days) **and**
whose geometry hasn't changed since that attempt is skipped, logged
distinctly (`"still fresh ... — skipping"`) from the cooldown message.

**Real bug found and fixed along the way, not in the original plan**:
`sync_route`'s pre-existing geometry-change detection
(`str(existing.track) != str(new_track)`) never actually worked —
comparing a DB-round-tripped EWKB string against a freshly-built plain
WKB string meant it was `True` on literally every re-sync, for every
route, since the column existed. This wasn't just a latent bug; left
as-is, it would have made `track_updated_at` update on every sync too,
silently defeating this whole fix on day one. Fixed by comparing
Shapely's own `.wkb` on both sides after re-hydrating `existing.track`
with `to_shape()` first.

Migration `c1a7f9e2b3d4` (`add_track_updated_at_to_routes`) adds the
column and backfills every existing route's `track_updated_at` to
`now()` — the conservative default this doc specified. Applied via
`make db-upgrade` locally and via `make deploy` in production; the
production startup log after deploy confirms the conservative backfill
behaved as intended: all 3 existing routes' background amenity sync ran
normally (not skipped) immediately after migration, because the
migration's `now()` timestamp postdated each route's pre-existing
`amenities_synced_at`.

`make ci`: 360 passed, 96.45% coverage, security checks clean.
`make deploy` completed — image built, `alembic upgrade head` ran
against production (`4a7b4678b2db` → `c1a7f9e2b3d4`), `app` container
healthy post-deploy, startup log shows the normal 3-route amenity sync
kicking off (one Overpass 504 observed for one chunk, unrelated to this
change — the existing resilience machinery in `geo_sync.py`/`overpass.py`
already handles that).

## Leftover

- **Live webhook-triggered skip, not yet observed** — no content-only
  webhook push has landed for Dream of North (or any route) since this
  deployed. The fixture/integration tests exercise the exact same code
  paths (`sync_route`'s update branch with an unchanged GPX plus a
  content-only frontmatter edit; `sync_amenities`'s freshness skip with
  fabricated timestamps matching that scenario), but this doc's own
  original evidence was a real two-hour-apart webhook push — worth
  confirming the log actually reads `"still fresh ... — skipping"` the
  next time a content-only push for a route inside the freshness window
  happens for real, rather than relying on the tests alone.
- **`_AMENITY_FRESHNESS_WINDOW = 7 days` is a first guess, not yet
  tuned against real observation** — the doc's own Phase 2 scope note
  flagged this ("or whatever value feels right after real observation").
  Revisit once there's a few weeks of production log history showing
  how often routes actually get re-synced within vs. outside 7 days.
- **The EWKB/WKB comparison bug's blast radius before this fix**: every
  Route row has been rewritten (an UPDATE, not a no-op) on every single
  re-sync since the column-based upsert logic was written, not just
  since this fix started. No data-integrity impact (the write always
  wrote the *same* values), but worth knowing this explains why
  `sync_route`'s update branch has always logged "Updated Route" rather
  than "unchanged — no write" for otherwise-idempotent re-syncs — a
  loose end from `test_sync_is_idempotent_with_route_and_pois` that
  this fix happened to close as a side effect, not something that test
  itself was checking for.