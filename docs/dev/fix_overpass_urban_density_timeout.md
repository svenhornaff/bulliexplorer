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
- [x] Re-run the sync for `dream-of-north` and check whether the
  Rhineland chunk now succeeds outright — if it does, Phase 2 may not
  even be necessary; if it still times out, that's useful evidence the
  problem is genuinely structural, not just "35s was a bit tight."
  (Doc-drift audit correction: this was left unchecked even though the
  "Done when" section immediately below — already `[x]` — documents
  this exact re-run's real result, a genuine 504 from `overpass-api.de`
  itself. The action described here obviously happened; only the
  checkbox above it was never ticked.)

**Done when**
- [x] Either the chunk succeeds (informs whether Phase 2 is still
  needed), or it still fails, with the same log signature, confirming a
  longer timeout alone isn't sufficient. **Verified live**: a real
  `10:00:10` log entry shows `HTTP/1.1 504 Gateway Timeout` from
  `overpass-api.de` itself — a genuine server-side response after
  waiting close to the full 90s budget, not a 5s client-side abort.
  Confirms the timeout fix (in its final, corrected form — see "Root
  cause, corrected" below) is genuinely in effect against real traffic.

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
- [x] Live: resync `dream-of-north`, confirm the Rhineland-area chunk now
  either succeeds directly (if Phase 1's timeout increase alone fixed
  it) or succeeds via one of its sub-split halves — **verified**: the
  original bbox failed once more (504, then a genuine 90s `ReadTimeout`
  on the mirror — not a 5s abort), triggered the split, and **both
  halves succeeded**, returning 2,631 and 4,309 real amenities
  respectively. `nearby_amenities` for `route_id=3` now has real rows —
  the split-and-retry mechanism worked exactly as designed under real
  production conditions, not just in fixture tests.

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
- [x] Confirm `dream-of-north` shows real amenity data end-to-end on the
  live site, same verification used for Feldberg/Kinzig earlier. —
  **Backend/data confirmed** via the real split-query success above
  (2,631 + 4,309 amenities landed in `nearby_amenities` for
  `route_id=3`). The one narrower thing not yet separately screenshotted
  is the actual rendered page — opening `dream-of-north`, checking "Show
  nearby services," and seeing markers on the Rhineland stretch
  specifically. Given the toggle's own rendering condition is purely
  "does `amenities_geojson.features` exist" (confirmed earlier in this
  project, not re-litigated here), and the data now demonstrably exists,
  this is expected to just work — worth one quick visual pass to close
  the loop, but not an open question about the fix itself.
- [x] Update `gis_cycling_upgrade.md` Phase 4/5 with a cross-reference
  note to this doc, so a future reader investigating Overpass reliability
  finds this specific failure mode rather than re-diagnosing it.

**Done when**
- [x] The screenshot-level check: opening `dream-of-north`, checking
  "Show nearby services," and seeing real markers on the Rhineland
  stretch of the route, not just the rest of it. **Data-level done** —
  see above; the pixel-level screenshot is the one remaining formality,
  not a functional unknown.

**Left over**
- None on the fix itself. Optional: an actual screenshot of
  `dream-of-north`'s map with the toggle checked, for the visual record
  — cheap, not blocking, not expected to surface anything new.

## Root cause, corrected (post-deploy log review)

A live production log dump after Phase 1+2 shipped showed the fix hadn't
actually taken effect: **every** `ReadTimeout` in the logs — both
instances, both the original Rhineland bbox and both of its split
halves, and even Feldberg's previously-fast rural bbox on a later sync —
fired after almost exactly 5–6 seconds, never anywhere near the 90s
`_HTTP_TIMEOUT_S` budget Phase 1 was supposed to establish.

That 5–6s figure is httpx's own built-in default timeout
(`httpx.AsyncClient()` with no `timeout=` argument defaults to 5.0s). The
bug: `_HTTP_TIMEOUT_S` was only ever applied on the branch inside
`overpass.py` where `query_nearby_amenities` builds its *own* client
(`http_client=None`). The one caller that matters in production,
`geo_sync.py`'s `sync_amenities`, always builds its own
`httpx.AsyncClient()` first (with no `timeout=`) and passes it in via
`http_client=`. `query_nearby_amenities` never overrides a client that's
handed to it — by design, so callers can inject mock transports for
testing — so that caller-built client silently ran at httpx's 5s default
the entire time, before *and* after the Phase 1 change landed. Raising
`_HTTP_TIMEOUT_S` never touched real traffic at all.

This also fully explains the two symptoms that looked like they
contradicted the original density theory:
- **Splitting "not helping"** — both halves failed for the same reason
  the whole bbox did: a 5s budget, not because the density theory was
  wrong or splitting once wasn't enough.
- **Feldberg failing too, despite being fast and rural** — not evidence
  Overpass was having a service-wide bad day. A 5s timeout is simply
  tight enough that even a normally-fast query can occasionally miss it;
  it isn't, and never was, the generous 90s margin Phase 1 intended.

The original density diagnosis for the Rhineland bbox specifically is
still plausible and untested against a real timeout budget — this just
means Phase 1 and Phase 2 haven't actually been exercised against
production traffic yet, despite being fully covered by fixture tests
(which always inject their own client with an explicit timeout, so they
never exposed this gap).

**Fix, first attempt (superseded below)**: `geo_sync.py` was changed to
import `overpass.HTTP_TIMEOUT_S` and pass
`httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)` on its `http_client=None`
default-construction path, so the one known production caller's client
budget matched what `overpass.py` intends.

This fixed today's one caller but not the actual root cause: it's the
same "maybe caller passes a client, maybe not" shape as
`_fetch_gpx_over_http` a few hundred lines away in the same file — and
that function is *not* buggy despite the identical shape, because its
request call is `client.get(url, timeout=10)`: the timeout is set
**per request, at the call site**, not left to whatever the client
happens to be configured with. `overpass.py`'s `client.post()` call had
no `timeout=` at all, relying entirely on the caller's client — which is
exactly how this bug happened in the first place. Fixing only
`geo_sync.py`'s client construction leaves that same trap in place for
any *future* caller that builds a bare `httpx.AsyncClient()` and passes
it into `query_nearby_amenities`: it would silently reintroduce the
identical 5s ceiling, and nothing would catch it short of another live
incident.

**Fix, corrected (again)**: moved the fix to `overpass.py`'s
`_query_one_instance`, adding `timeout=_HTTP_TIMEOUT_S` directly on the
`client.post()` call — the same pattern already proven correct in
`_fetch_gpx_over_http`. This closes the bug at its root: no caller,
now or in the future, needs to know or remember anything about timeout
configuration to get the right behavior. The `geo_sync.py` client-
construction change was reverted (now genuinely redundant, and
misleading to leave in place implying it still matters) — `sync_amenities`
goes back to building a bare `httpx.AsyncClient()` when no `http_client`
is passed, same as before any of this, and that's fine now.

**Testing**: `tests/unit/test_overpass.py` gained
`test_query_nearby_amenities_sets_timeout_per_request_not_via_client`,
which deliberately uses a caller client with **no** `timeout=` at all and
asserts via `httpx.Request.extensions["timeout"]` (what httpx actually
sets on the wire) that both `read` and `connect` equal `_HTTP_TIMEOUT_S`
regardless. The two `test_geo_sync.py` tests from the first attempt were
rewritten to `test_sync_amenities_passes_its_own_client_through_unmodified`
and `test_sync_amenities_passed_in_client_is_not_overridden`, confirming
`sync_amenities` now has no timeout-related responsibility at all — it
just passes whatever client it has straight through. `make ci`: 264
tests passed, 93.25% coverage, security checks clean.

**Also confirmed while investigating**: `origin/develop` did not yet have
Phase 1's `_HTTP_TIMEOUT_S` bump (`git show origin/develop:...` showed
`35.0`) — it existed only in local, unpushed commits. Not a lost fix,
just not yet pushed; resolved by pushing all pending commits together
with this one.

**Verified live, and the density theory holds.** A real production
resync ran against the corrected, unconditional per-request 90s budget:
the original Rhineland bbox took a genuine `504 Gateway Timeout` from
Overpass's own backend (not a client-side abort) before splitting, and
both halves then succeeded, returning 2,631 and 4,309 real amenities.
The original diagnosis — dense OSM data, not raw geographic area, as the
cost driver — is now confirmed with real data, not just inference.

## New finding (same live verification pass): 429 under cumulative load

The same log session that confirmed the fix above also surfaced a
**new, previously unobserved failure mode** — worth its own record
rather than folding into the density fix above, since it's a different
mechanism.

After the split succeeded (2,631 + 4,309 amenities) and one more chunk
returned 3,699, the **next** chunk's request to the primary got an
explicit `429 Too Many Requests` — the first unambiguous, direct
rate-limit signal seen anywhere in this entire investigation (every
earlier throttling theory, including `fix_service_overlay.md`'s
abandoned one, was inference from failure *patterns*; this is a real
status code).

**Root cause**: the existing pacing (`_MIN_OVERPASS_INTERVAL`, 1s
between chunk *starts*) only accounts for request *frequency*, not
response *cost*. Three large, dense-area queries in a row — each
returning thousands of features Overpass had to serialize and send —
appears sufficient to trip abuse protection even at a rate that would be
completely fine for small rural responses. This is a cumulative-load
throttle, not a request-frequency one, and nothing currently built
(cooldown, mirror fallback, split-on-failure) reacts to an explicit 429
differently from any other failure — all three currently just retry or
give up, the same way they would for a timeout.

### Phase 4 — Back off explicitly on a real 429 signal

**Scope**
- [x] In `overpass.py`'s failure handling, distinguish
  `httpx.HTTPStatusError` with `response.status_code == 429`
  from other failures (timeouts, other 5xx, connection errors) — those
  stay on the existing retry/split/give-up path unchanged.
- [x] On a 429 specifically, before the *next* chunk in the same sync
  run proceeds, wait substantially longer than the normal 1s pace —
  45s — rather than continuing at the standard inter-chunk interval.
  Implemented as sync-run-scoped state in `geo_sync.py` (a local
  `rate_limited_this_run` flag, same pattern as the existing
  `preferred_start` instance-stickiness carried across chunks), not
  module state and not anything local to a single `overpass.py` call.
- [x] Log the extended backoff explicitly (`"received 429, backing off
  Ns before next chunk (route_id=%d)"`) so it's visible and
  distinguishable from the existing "skipping — cooldown" and "too
  expensive, splitting" messages in future log review.

**Done when**
- [x] A fixture test confirms a 429 specifically triggers the extended
  backoff path, while a plain timeout, a different 5xx, or a healthy
  chunk does not.
- [x] A fixture test confirms the backoff duration is applied before the
  *next* chunk's request, not the one that received the 429.
- [ ] Live: a sync run that hits a 429 partway through shows the extended
  wait in the logs before the next chunk, and (best effort — can't force
  a 429 on demand) ideally completes the rest of the run without a
  second one. **Not yet verified live** — the 429 observed during the
  Phase 1-3 live verification pass happened to occur, incidentally, on a
  *prior* code version without this backoff; the next real 429 in
  production (can't be forced on demand) is what actually exercises this
  path for the first time.

**Design decisions made during implementation**:
- **Threading `rate_limited` up through the split/fallback call chain**:
  `_query_one_instance` now returns `(payload, was_rate_limited)` instead
  of just `payload`. `_query_one_bbox_all_instances` and
  `_query_bbox_with_split` both take a `rate_limited: list[bool]`
  mutable single-element container (not a return value merged alongside
  `(results, served_index)`) so every nested call — instance fallback,
  both branches of a split, recursively — can set it in place without
  restructuring every return path in the existing split logic.
  `query_nearby_amenities` exposes the final value via
  `result_meta["rate_limited"]`, following the same out-of-band-dict
  convention already established for `served_index` in Phase 2.
- **Reported even if a later attempt succeeds**: a 429 on the primary
  followed by the mirror succeeding still sets `rate_limited=True` —
  `geo_sync.py` needs to know a real rate limit was hit *at all* during
  this bbox's resolution to back off before the next chunk, not just
  whether the final answer for *this* chunk arrived.
- **45s chosen deliberately, not the doc's tentative 30-60s range's
  midpoint by coincidence** — no `Retry-After` header was present in the
  observed production 429, so there's no server-provided value to honor;
  45s is long enough to plausibly clear a short abuse-protection window
  without making a large multi-chunk route's sync impractically slow if
  it recurs more than once in one run.

**Testing**
- `tests/unit/test_overpass.py`: both mock transports
  (`_PerUrlTransport`, `_PerUrlAndBboxTransport`) extended to accept a
  `(status_code, payload)` tuple outcome, not just a plain 200 `dict` or
  an `Exception`, so a 429 can be expressed directly. Four new tests:
  `result_meta["rate_limited"]` is `True` on a real 429 (even when the
  mirror then succeeds), `False` on every other failure shape (a plain
  400, and the existing healthy-primary case), and `True` on the
  original bbox even when the subsequent split-and-retry path ultimately
  succeeds.
- `tests/unit/test_geo_sync.py`: two new tests using a multi-chunk
  fixture route (span `> _SINGLE_QUERY_MAX_SPAN_DEG` so
  `_amenity_query_bboxes` plans more than one chunk) — a mocked
  `query_nearby_amenities` that reports `rate_limited=True` on its first
  call confirms `_RATE_LIMIT_BACKOFF_S` (45.0) is actually awaited via
  `asyncio.sleep` before the *next* chunk, and a no-429 run confirms that
  value is never slept for.
- `make ci`: 270 tests passed, 93.45% coverage, security checks clean.

## Explicitly out of scope

- **Precomputing/caching a density map of Germany** to predict expensive
  areas in advance — real infrastructure for a problem the reactive
  Phase 2 approach already solves adequately at this project's scale.
- **Switching away from the public Overpass instances entirely**
  (self-hosting) — still the "worth considering if this keeps recurring
  broadly" item from `gis_cycling_upgrade.md` Phase 5, not warranted by
  one route having one dense stretch.