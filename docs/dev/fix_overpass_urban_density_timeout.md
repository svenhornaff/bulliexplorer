# Fix: Overpass amenity sync fails on dense-urban route chunks

> Root-cause investigation and fix plan for a reproducible Overpass
> `ReadTimeout` on one specific chunk of `dream-of-north`, surviving both
> the mirror fallback and per-route cooldown from `gis_cycling_upgrade.md`
> Phase 5. See that doc for the amenity-sync architecture this corrects,
> and `fix_service_overlay.md` for a recent, unrelated false lead this one
> is careful not to repeat.

---

## Symptom

`dream-of-north`'s "Show nearby services" checkbox never appears —
`amenities_geojson.features` is empty for that route, while
`kinzig-valley-loop` and `feldberg-summit-loop` both work correctly.

## Investigation

Direct log inspection (`docker compose logs app`, filtered to the actual
sync window) shows the same bbox failing **twice**, against **both**
Overpass instances, roughly 25 seconds apart:

```
bbox (50.71967998198198, 6.575888876730576, 51.561832018018016, 7.258887123269424)
  05:59:05  overpass-api.de           → ReadTimeout
  05:59:11  overpass.kumi.systems     → ReadTimeout
  05:59:31  overpass-api.de           → ReadTimeout (retried on next sync)
  05:59:37  overpass.kumi.systems     → ReadTimeout
```

Every other chunk in the same sync run — including Feldberg's rural
Black Forest bbox — succeeded cleanly, several in under a second.

**Corrected root cause, checked precisely rather than assumed**: the
failing bbox spans `0.84°` latitude × `0.68°` longitude — both *under*
`_SINGLE_QUERY_MAX_SPAN_DEG` (`1.0°`), the existing per-chunk size cap.
This chunk is not oversized by the current design's own rules. What's
different about it is what it *covers*: this bbox sits squarely over the
Cologne–Bonn–Ruhr conurbation — one of the most densely OSM-mapped
regions in Germany. The query itself is cheap (a handful of tag filters),
but Overpass has to scan a vastly larger feature index for the same
physical area here than it does over rural Scandinavia or the Black
Forest. **A fixed geographic span cap doesn't distinguish "small area,
sparse data" from "same size, dense data"** — and this route is the
first one in production whose path happens to cross a genuinely dense
region at all.

This is a different failure shape from anything `gis_cycling_upgrade.md`
Phase 5 was built for. The mirror fallback and cooldown both correctly
address *transient, whole-instance* unavailability (a bad moment, an
abuse-protection block). This is neither — it's a *structurally* expensive
query for this specific area, and retrying it against a second instance
changes nothing, because the bottleneck isn't which server answers, it's
how much data exists to scan within that area.

## Options considered

**A. Raise `_HTTP_TIMEOUT_S` globally (35s → e.g. 90s).** Cheapest
possible change, worth trying first as a quick experiment. Real
limitation: it delays *every* query's failure detection, not just dense
ones, and there's no guarantee 90s is enough either — a sufficiently
dense area could still exceed a generous timeout, just later. Doesn't
fix the underlying issue, only buys headroom.

**B. Lower `_SINGLE_QUERY_MAX_SPAN_DEG` globally (smaller max chunk size
for every route).** Would shrink this chunk enough to likely succeed, but
uniformly punishes every *other* route too — sparse rural chunks that
already succeed instantly would get needlessly split into more, smaller
queries, increasing total sync time and Overpass load for no benefit
where density isn't a problem.

**C. Adaptive sub-splitting on failure — recommended.** If a chunk fails
against *both* instances, split that specific bbox into halves (quadrants,
if needed) and retry each smaller piece, up to a bounded subdivision
depth, before giving up on that section entirely. This only pays the
extra-query cost exactly where it's actually needed — dense chunks that
demonstrably fail at the current size — and leaves every already-working
chunk on every other route completely untouched. No need to predict or
hand-tune per-region density in advance; the system discovers it
reactively, at the one place it actually matters.

**Recommendation: do both A and C.** A is a five-minute, low-risk change
worth having regardless (more headroom before *anything* is declared a
failure). C is the real structural fix, and the one worth the actual
implementation effort.

## Interaction with the existing query cap

`_MAX_AMENITY_QUERIES = 30` bounds the *initial* planned chunk count per
sync — that stays unchanged, still the baseline cost ceiling for any
route regardless of length. Adaptive sub-splitting (Option C) needs its
own, separate, small bound — e.g. **at most one subdivision level per
originally-failed chunk** (split into 2, retry each once; don't split
recursively into 4, 8, 16). This keeps worst-case total query count for
a bad sync run predictable (30 initial + at most a handful of recovery
splits) rather than open-ended.

## Phased implementation plan

### Phase 1 — Raise the HTTP timeout (cheap, do first)

**Scope**
- [x] `_HTTP_TIMEOUT_S`: `35.0` → `90.0` in `overpass.py`.
- [ ] Re-run the sync for `dream-of-north` and check whether the
  Rhineland chunk now succeeds outright — if it does, Phase 2 may not
  even be necessary; if it still times out, that's useful evidence the
  problem is genuinely structural, not just "35s was a bit tight."

**Done when**
- Either the chunk succeeds (informs whether Phase 2 is still needed),
  or it still fails, with the same log signature, confirming a longer
  timeout alone isn't sufficient. **Not verified against production** —
  see Phase 3.

**Testing**
- No new test needed — this is a constant value change, already covered
  by existing timeout-path tests in `test_overpass.py`.

**Summary**
- Raised `_HTTP_TIMEOUT_S` from `35.0` to `90.0` in `app/services/overpass.py`,
  with a comment cross-referencing this doc so a future reader sees why
  the value isn't the original Phase-4/5 default any more.
- Implemented regardless of whether Phase 2 alone would have been
  sufficient — cheap, low-risk headroom worth having either way, per the
  doc's own recommendation to do both A and C rather than treat them as
  alternatives.

### Phase 2 — Adaptive sub-splitting on dual-instance failure

**Scope**
- [x] In `overpass.py`, when `query_nearby_amenities` exhausts all
  instances for a given bbox (today: returns `None`), instead split the
  bbox into two halves (along its longer dimension — lat or lon,
  whichever spans more) and recursively retry each half through the
  same instance-fallback logic, to a max depth of 1 (per the cap
  reasoning above).
- [x] If a sub-split half *also* fails on all instances, give up on that
  half specifically (existing graceful-degradation behavior — log a
  warning, leave existing data untouched) rather than recursing further.
- [x] Log the split explicitly (`"bbox X too expensive, retrying as two
  halves"`) so this is visible and diagnosable in future logs, not silent.

**Design decisions made during implementation** (confirmed with the
project owner before writing code, since the doc above didn't fully
pin these down):
- **A half that fails while its sibling succeeds still fails the whole
  bbox** — no partial results are ever returned from a split. Matches
  this pipeline's existing all-or-nothing philosophy
  (`geo_sync.py`'s `sync_amenities` already aborts an entire sync
  rather than write a partial snapshot on one failed chunk); keeps the
  split logic fully self-contained inside `overpass.py`, with no
  `geo_sync.py` changes needed at all.
- **`result_meta["served_index"]` after a split reports the second
  half's serving instance** — "most recently confirmed working," same
  spirit as the existing single-bbox sticky-failover logic from Phase 5.
- **The two halves are queried concurrently** (`asyncio.gather`), not
  sequentially — an improvement over the doc's implicit assumption,
  caught during implementation review: sequential halves would double
  the wall-clock cost of the already-slow failure path (worst case
  `2 × (timeout + retry-delay + timeout + retry-delay)`), while the two
  halves have no data dependency on each other.
- **Boundary-element dedup, not assumed away**: Overpass bbox filters
  are inclusive on both ends, so an element sitting exactly on the
  split's dividing line can be returned by *both* halves. Deduped by
  `(osm_element_type, osm_element_id)` after combining both halves'
  results — the same natural key `geo_sync.py` already uses to dedupe
  across chunks for the (different) buffer-overlap case.

**Done when**
- [x] A fixture test simulating the exact observed failure (a bbox
  failing on both instances) confirms it gets split and each half is
  retried through the normal instance-fallback path.
- [x] A fixture test confirms the depth cap: a half that *also* fails on
  both instances does not get split further.
- [ ] Live: resync `dream-of-north`, confirm the Rhineland-area chunk now
  either succeeds directly (if Phase 1's timeout increase alone fixed
  it) or succeeds via one of its sub-split halves — check via
  `SELECT route_id, COUNT(*) FROM nearby_amenities WHERE route_id = 3;`
  showing a non-zero count, and the "Show nearby services" checkbox
  actually appearing on the live page. **Not verified** — see Phase 3.

**Testing**
- Unit tests in `tests/unit/test_overpass.py`: dual-failure triggers a
  split (mocked), split halves retried correctly, depth cap respected
  (a failing half is not split again), and — importantly — a chunk that
  succeeds normally never triggers any splitting logic at all (no
  regression to the common case).

**Summary**
- `overpass.py`'s instance-fallback loop was extracted into a private
  `_query_one_bbox_all_instances` helper, and a new
  `_query_bbox_with_split` wraps it: on total failure (every instance
  failed for a bbox), it splits the bbox in half
  (`_split_bbox_in_half`, along whichever axis — lat or lon — has the
  larger span) and retries each half through
  `_query_one_bbox_all_instances` again, recursing at most once
  (`_MAX_SPLIT_DEPTH = 1`). The public `query_nearby_amenities`
  signature is unchanged — the split logic is entirely internal, not a
  new parameter callers need to know about.
- Both halves are queried concurrently via `asyncio.gather`, not
  sequentially, so a split doesn't double the wall-clock cost of the
  already-slow failure path.
- Boundary elements (an OSM element sitting exactly on the split's
  dividing line, which Overpass's inclusive bbox bounds can return from
  both halves) are deduped by `(osm_element_type, osm_element_id)`
  before being returned — the same natural key `geo_sync.py` already
  uses to dedupe across buffer-overlapping chunks.
- 9 new unit tests in `tests/unit/test_overpass.py`: dual-instance
  failure triggers a split with each half retried correctly, the depth
  cap (a failing half is never split again — asserted against
  `_MAX_SPLIT_DEPTH` directly, not just observed request counts),
  boundary-element dedup, `result_meta` reporting the second half's
  serving instance, and — the regression check — a chunk that succeeds
  normally never triggers any split logic at all (request count stays
  at 1). All mocked (no real network), using a new
  `_PerUrlAndBboxTransport` fixture that keys responses on `(url, bbox
  substring)` since a split retries the *same* two instance URLs with a
  *different* (halved) bbox — the existing `_PerUrlTransport` (keyed on
  URL alone) can't express that.
- `make ci` green throughout: 261 tests, 93.05% coverage.

**Recommended next steps**
- Nothing currently blocks Phase 3's non-live scope item (the
  `gis_cycling_upgrade.md` cross-reference, added below). The one thing
  actually left is the live verification itself — see Phase 3.

### Phase 3 — Verify and close out

**Scope**
- [ ] Confirm `dream-of-north` shows real amenity data end-to-end on the
  live site, same verification used for Feldberg/Kinzig earlier.
- [x] Update `gis_cycling_upgrade.md` Phase 4/5 with a cross-reference
  note to this doc, so a future reader investigating Overpass reliability
  finds this specific failure mode rather than re-diagnosing it.

**Done when**
- The screenshot-level check: opening `dream-of-north`, checking "Show
  nearby services," and seeing real markers on the Rhineland stretch of
  the route, not just the rest of it. **Not verified** — this sandbox
  has no access to the production deployment, its Overpass egress, or
  its database. Phase 1 and 2 are implemented and fully covered by
  fixture tests reproducing the exact observed failure shape (the same
  bbox, the same dual-`ReadTimeout`), but the actual live resync against
  `dream-of-north` and the DB/UI check described above are left for the
  project owner to run and confirm — same pattern as
  `gis_cycling_upgrade.md` Phase 5's own unresolved live-verification
  "Left over" bullet.

**Left over**
- The live resync check above. Once run: confirm via
  `SELECT route_id, COUNT(*) FROM nearby_amenities WHERE route_id = <dream-of-north's id>;`
  showing a non-zero count, and the "Show nearby services" checkbox
  appearing on the live page. If the Rhineland chunk still fails even
  after both the timeout increase and the split (i.e. even a halved
  bbox is still too dense), that's the signal this doc's "explicitly out
  of scope" items below may need revisiting — not expected, but worth
  checking for before assuming Phase 2 fully closes this out.

## Explicitly out of scope

- **Precomputing/caching a density map of Germany** to predict expensive
  areas in advance — real infrastructure for a problem the reactive
  Phase 2 approach already solves adequately at this project's scale.
- **Switching away from the public Overpass instances entirely**
  (self-hosting) — still the "worth considering if this keeps recurring
  broadly" item from `gis_cycling_upgrade.md` Phase 5, not warranted by
  one route having one dense stretch.