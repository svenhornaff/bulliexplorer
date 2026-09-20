# Fix: incremental amenity writes + operator sync visibility

> Root cause and fix plan for `dream-of-north` showing zero amenities on
> the live page despite the logs showing thousands of real, successfully
> fetched amenities across multiple chunks. See
> `fix_overpass_urban_density_timeout.md` and
> `fix_startup_blocking_amenity_sync.md` for the two prior fixes this one
> builds on — both worked correctly; this is the next layer the previous
> fixes' success exposed, same pattern as the whole investigation so far.

---

## Symptom

Live logs for a `dream-of-north` sync show clearly successful Overpass
responses — 6,940, 1,764, 1,202, 607, 605 amenities across different
chunks, real data, correctly fetched. The live page shows none of it,
and the "Show nearby services" toggle doesn't appear at all.

## Root cause — confirmed by reading `sync_amenities` directly, not inferred

`geo_sync.py`'s `sync_amenities` is deliberately **all-or-nothing**, by
its own docstring: *"Existing amenities are only replaced once every
chunk query has succeeded... an incomplete answer is worse than a stale
one."* Every chunk's results accumulate in a local list across the
entire loop; the actual DB write (delete existing rows for this route,
insert the deduped combined result) happens exactly once, **after every
chunk has succeeded**.

Worse than "wait for a fully clean run": on **any** chunk failure, the
function returns immediately —

```python
if chunk_results is None:
    logger.warning(...)
    return
all_results.extend(chunk_results)
```

— discarding not just that one chunk, but every other chunk's results
already accumulated **in the same run**. A failure on chunk 25 of 30
throws away chunks 1-24's worth of already-fetched, genuinely good data
too.

**Why this design made sense originally, and why it stops making sense
here**: for a typical route (a handful of chunks, high per-chunk
reliability against Overpass), a single failed chunk is a rare event,
and discarding a whole run for it is a reasonable, conservative
trade-off — you're protecting a *good existing snapshot* from being
silently downgraded by one bad chunk. Dream of North breaks both halves
of that reasoning: at 30 chunks against a famously unreliable free
public API, the probability of a fully clean run is low enough that
"wait for one" isn't a plan, it's an indefinite wait — and there's no
good existing snapshot being protected in the first place, since this
route has never once completed a full run. All-or-nothing here isn't
preventing harm; it's withholding real, correct, already-paid-for data
indefinitely, possibly forever.

## Recommended fix: write per chunk, not per route

**Design**: as each chunk succeeds, write its results immediately —
don't wait for the rest of the route's chunks. Keep the core safety
property that made the original design reasonable: a *failed* chunk
never deletes anything, it just means that specific slice of the map
doesn't get updated this run. No data is ever removed based on absence
of information, only replaced when new information for that specific
area actually arrives.

**Concretely**, per successful chunk:
- Upsert each result by its natural key (`route_id`, `osm_element_type`,
  `osm_element_id`) rather than blind insert — adjacent chunks'
  buffer-padded bboxes overlap by design, so the same OSM element can
  legitimately be returned by more than one chunk. Upserting means a
  second chunk re-reporting the same element updates it in place rather
  than creating a duplicate row.
- For removing genuinely stale elements (the route changed, an amenity
  that used to be nearby no longer is): scope the delete to *that
  chunk's own bbox* — delete existing rows within this specific bbox
  that aren't present in this chunk's fresh result, then upsert what
  the chunk actually returned. This correctly handles staleness at the
  granularity data actually arrives at, rather than requiring a perfect
  whole-route run to ever clean anything up.
- A chunk that fails touches nothing — no delete, no insert, for that
  bbox, this run. Exactly today's protection, just scoped to the chunk
  instead of the whole route.

**What this actually buys, worth being explicit about both halves:**

- **For you, operationally**: real amenity coverage for Dream of North
  starts appearing the first time *any* chunk succeeds, not after all
  thirty do. Given the logs already show many chunks succeeding
  individually, this route likely already has substantial real coverage
  today that's simply never been allowed to reach the page.
- **For a reader, and this needs no new reader-facing feature at all**:
  someone visiting the page mid-sync now sees whatever's actually been
  discovered so far instead of nothing. The map naturally becomes more
  complete over time as more chunks succeed on subsequent syncs — no
  "loading" indicator, no new UI, because the existing toggle/marker
  rendering already handles "however many amenities currently exist"
  correctly. The fix *is* the reader-facing improvement; nothing else
  needs building for that half.

## Also worth doing: operator visibility into in-progress syncs

Separate but related gap, surfaced by the same investigation: checking
"is Dream of North's sync working, and how far along is it" currently
means SSH, `docker compose logs`, and manual `grep` — every single time.
That's real operator friction, distinct from the reader-facing question
above, and worth its own small fix rather than living with indefinitely.

**Design**: a small authenticated status view, same pattern already
established for `/internal/resync` (token-header auth, no new
infrastructure). Per route: chunks succeeded so far this run / total
planned, last attempt timestamp, currently-in-progress or idle. This
doesn't need new state beyond what's already being tracked in-memory
during a sync — mostly a matter of exposing it rather than computing
anything new.

## Phased implementation plan

### Phase 1 — Per-chunk incremental writes

**Scope**
- [x] Refactor `sync_amenities`'s loop: move the delete+upsert logic
  inside the loop, scoped per-chunk, instead of accumulating
  `all_results` and writing once after the loop.
- [x] Natural-key upsert (not blind insert) so overlapping chunks'
  shared elements update in place, never duplicate.
- [x] Per-chunk delete scoped to that chunk's bbox only, for the
  staleness-cleanup property described above.
- [x] A failed chunk writes nothing for its own bbox and does not affect
  any other chunk's already-written data in the same run — the core
  behavior change from today's "one failure discards the whole run."

**Done when**
- [x] A fixture test: three chunks, the second fails — asserts the first
  and third chunks' results are both present in the DB afterward (this
  is the test that would have failed under today's code, and is the
  whole point of this phase).
  (`test_amenity_sync_partial_failure_preserves_other_chunks_writes`,
  `tests/integration/test_geo_sync_integration.py`.)
- [x] A fixture test confirms an element returned by two overlapping chunks
  doesn't create a duplicate row.
  (`test_amenity_sync_overlapping_chunks_no_duplicate_row` — exercises
  the DB's own `uq_nearby_amenities_route_osm_element` constraint via
  the natural-key upsert, not just in-memory dedup.)
- [x] A fixture test confirms a chunk that previously had an element which
  is genuinely gone now (re-queried, legitimately absent from a fresh
  successful response) gets its stale row removed — staleness handling
  preserved, just at chunk granularity instead of whole-route.
  (`test_amenity_sync_stale_element_removed_when_absent_from_fresh_chunk`.)
- [ ] Live: resync `dream-of-north`, confirm `nearby_amenities` for
  `route_id=3` gets non-zero rows *during* the run, not only if/when it
  fully completes — checked via the same `SELECT ... GROUP BY route_id`
  query used throughout this investigation, run partway through a sync
  rather than only after. **Still not verified this specifically** —
  doc-drift audit update, real new evidence, not the same claim as
  before: `dream-of-north` now genuinely has 21,673 amenity rows live
  in production (confirmed via `GET /posts/dream-of-north/amenities.
  geojson` against the real deployed site), so the *sync itself*
  demonstrably completes successfully end-to-end at real scale. What
  remains unconfirmed is narrower than the original claim: actually
  observing a non-zero, still-growing row count mid-sync (not just
  confirming the eventual completed result) — nobody has captured that
  specific timing snapshot.

**Design decisions made during implementation** (confirmed with the
user before proceeding — this changes `sync_amenities`'s transaction
contract, not just its internal loop structure):
- **Commit granularity**: `sync_amenities` now commits its own writes
  per chunk, immediately after each successful chunk's delete+upsert —
  not left to the caller as before. This was necessary, not optional:
  the "Done when" criterion above (non-zero rows visible *during* a run,
  checked from a separate DB connection/session) is only actually
  observable if each chunk's write is durably committed as it happens,
  not merely flushed within one still-open transaction that wouldn't be
  visible outside it until the whole run finishes. The
  `route.amenities_synced_at` cooldown timestamp is likewise committed
  up front, before any chunk runs, so a crash mid-sync still leaves the
  cooldown correctly started. A caller wrapping this in a larger
  transaction of its own should know amenity writes commit
  independently — documented explicitly in `sync_amenities`'s docstring.
- **Per-chunk delete scoping via PostGIS**: `func.ST_Within(NearbyAmenity.
  location, func.ST_MakeEnvelope(...))` scopes the staleness delete to
  exactly the querying chunk's own bbox, so a neighboring chunk's row
  (inside the overlap zone) is never touched by a chunk that simply
  didn't happen to return it this time.
- **Upsert via `postgresql.insert(...).on_conflict_do_update(constraint=
  "uq_nearby_amenities_route_osm_element", ...)`** — the DB's own unique
  constraint (already present on the model, not newly added) is the
  natural key; no new schema/migration needed for this phase.

**Testing**
- Unit tests in `tests/unit/test_geo_sync.py`: the existing rate-limit-
  backoff regression tests (`test_sync_amenities_backs_off_after_rate_
  limited_chunk`, `test_sync_amenities_no_backoff_without_a_429`) needed
  their mocked session's `execute()` updated to return a real (empty)
  list from the new per-chunk staleness query — confirms no regression
  to pacing/backoff behavior from this refactor.
- Integration tests in `tests/integration/test_geo_sync_integration.py`
  (new, 3 tests, real PostGIS): the three "Done when" fixture tests
  above, using a new multi-chunk GPX fixture spanning >1° so
  `_amenity_query_bboxes` actually plans multiple chunks — the whole
  point of this phase is only observable across more than one chunk in
  the same run.

### Phase 2 — Operator sync-status visibility

**Scope**
- [x] New `GET /internal/sync-status` — per route: chunks succeeded /
  total this run (or last run), chunks failed, last attempt timestamp,
  in-progress or idle. Same `X-Resync-Token` auth already in place for
  the existing internal endpoints — no new auth mechanism needed.

**Done when**
- [x] Hitting the endpoint mid-sync shows real, current progress for a
  route actively being synced — confirms it reflects live state, not a
  cached/stale snapshot.
  (`test_sync_status_reflects_live_in_memory_state`, confirmed at the
  fixture level by mutating the tracker directly — the same object a
  running `sync_amenities` call mutates — and observing identical
  values through the endpoint. The live equivalent, hitting the real
  endpoint against `dream-of-north`'s actual in-progress sync, is **not
  yet verified live**.)

**Design decisions made during implementation:**
- **In-memory, process-local tracker** (`geo_sync.AmenitySyncStatus` +
  a module-level `route_id -> AmenitySyncStatus` dict), not persisted to
  the DB — this is operator-facing progress for *this* process's
  current or most recent run, not a durable record; the actual result
  of a sync is the `NearbyAmenity` rows themselves, already durable via
  Phase 1. Fine for this project's single-process deployment
  (`bulliexplorer-tech-concept.md`) — a multi-worker deployment would
  need this moved to the DB or a shared cache, explicitly not attempted
  here since it isn't warranted by the current deployment shape.
- **A route absent from the response, not zeroed-out**: a route never
  attempted in this process's lifetime (e.g. right after a restart)
  simply doesn't appear in `"routes"`, rather than appearing with
  `chunks_total: 0` etc. — avoids a caller mistaking "never run" for
  "ran and found nothing to do."

**Testing**
- `tests/unit/test_resync.py` (4 new tests): token-auth parity with
  `/internal/resync` (missing/wrong token → 401), live-state reflection
  via direct tracker mutation, and the never-synced-route-is-absent
  case.

## Explicitly out of scope

- **A reader-facing "amenities still loading" indicator** — deliberately
  not building this. Phase 1 already delivers the reader-facing
  improvement (progressively more complete coverage) without any new UI;
  adding a loading indicator on top would add noise to what's meant to
  stay a quiet, best-effort enhancement, and contradicts the
  graceful-degradation design already correct everywhere else in this
  feature.
- **Retroactively backfilling Dream of North's full history of past
  successful-but-discarded chunk results** — not recoverable (those
  responses were never persisted, per today's design, by definition),
  and not worth reconstructing. The very next sync under Phase 1's new
  behavior naturally accumulates real coverage going forward; no need to
  chase what's already gone.

## Summary

Both phases implemented. `sync_amenities` writes and commits per chunk
as it succeeds (natural-key upsert + bbox-scoped staleness delete via
PostGIS `ST_Within`/`ST_MakeEnvelope`), instead of accumulating results
in memory and writing once only if every chunk in the route succeeds. A
failed chunk now only affects its own bbox, never any other chunk's
already-written data in the same run. A new `GET /internal/sync-status`
endpoint (same `X-Resync-Token` auth as `/internal/resync`) exposes an
in-memory, process-local per-route progress tracker
(`geo_sync.AmenitySyncStatus`) that a running sync mutates directly, so
the endpoint always reflects live state.

`make ci`: 293 passed, 95.65% coverage, security checks clean.

## Recommended next steps

- **Live verification (both phases)** — not possible from this sandbox,
  no production access. On the next deploy:
  - Trigger a resync of `dream-of-north` and, partway through (not
    waiting for it to finish), run the same `SELECT ... GROUP BY
    route_id` query used throughout this investigation against
    `nearby_amenities` — confirm non-zero rows appear for `route_id=3`
    *during* the run, not only after.
  - In parallel, hit `GET /internal/sync-status` mid-sync and confirm
    `chunks_succeeded` is actually advancing between polls, not frozen
    or reflecting a previous run.
  - Confirm the reader-facing outcome directly: load the Dream of North
    post page while a sync is in progress (or shortly after a partial
    one) and confirm the "Show nearby services" toggle now appears with
    real markers, where it previously showed nothing at all.
- **Worth watching, not yet a known problem**: per-chunk commits mean a
  30-chunk sync now does up to 30 separate commits instead of one (or
  zero, on failure) — each individually small and fast, but worth
  confirming this doesn't introduce any noticeable DB load pattern change
  in production monitoring, given nothing here was load-tested against
  real concurrent traffic.
