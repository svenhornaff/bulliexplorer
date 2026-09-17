# Fix: decouple Overpass amenity discovery from the blocking startup path

> Root cause and fix plan for the container reporting `unhealthy` for
> several minutes after a normal deploy — not a crash, but the natural
> consequence of every resilience feature added in
> `fix_overpass_urban_density_timeout.md` (90s timeouts, mirror fallback,
> bbox splitting, 45s rate-limit backoff) stacking up inside a *blocking*
> startup call. Each of those fixes was correct on its own; together they
> pushed worst-case sync time past what's reasonable to block app startup
> on at all.

---

## Symptom

`docker compose ps` showed `bulliexplorer-app-1` as `unhealthy` several
minutes after a routine deploy. Not a crash — `docker compose logs app`
showed the sync pipeline actively working: content synced, GPX fetched,
amenity queries succeeding, splitting, and correctly backing off 45s on
a real 429 — exactly as designed. The container simply hadn't finished
starting up yet.

## Root cause

`app/main.py`'s `lifespan` awaits `sync_posts()` directly, inline, before
`yield` — and FastAPI/Starlette don't start accepting *any* request,
including `/health`, until the lifespan's startup phase completes.
`sync_posts()` loops over every post and calls `sync_route(...,
enable_amenity_discovery=True)` for each one — which, for a route like
Dream of North, means synchronous Overpass calls with:

- up to 90s per request attempt,
- retried against a second instance on failure,
- split into halves (each retried against both instances again) if both
  instances fail the whole bbox,
- and now, correctly, a 45s mandatory wait if any of that hits a 429 —
  potentially several times across a 30-chunk sync.

None of that is wrong *in isolation*. **The mistake is architectural,
not in any individual fix**: a best-effort, already-designed-to-tolerate-
failure enhancement (amenities have *always* degraded gracefully —
`leaving existing NearbyAmenity rows untouched` has been the behavior
since Phase 4 shipped) is sitting in the one place in the whole
application that's allowed to block traffic entirely. Every fix that
made amenity discovery *more resilient* also made it *slower in the
worst case* — and resilience and startup-blocking latency were never
supposed to trade off against each other.

## What should and shouldn't block startup

Worth being explicit about the actual correctness requirement, not just
"make it faster":

- **Content sync (Markdown → `posts` table, GPX → `routes` table + ride
  stats) should stay blocking.** A reader hitting `/posts/{slug}` needs
  the post to actually exist and be correct. This part is fast (no
  external network calls beyond the already-quick R2 GPX fetch) and
  failure-here genuinely should hold up startup.
- **Amenity discovery should not.** It was designed from Phase 4 onward
  to be an optional enhancement a page renders correctly without (the
  "Show nearby services" toggle simply doesn't appear if there's no
  data yet). Making it block startup contradicts that design — the one
  place it's currently *not* allowed to fail gracefully is the one place
  failure/slowness is most visible (the whole app refusing to come up).

## Options considered

**A. Cap total amenity-sync time at startup with a hard deadline
(e.g. `asyncio.wait_for`).** Simple, bounds the worst case. Real
downside: it doesn't fix the underlying mismatch, just papers over it —
routes that need more time than the cap silently never get amenity data
synced at startup at all, with no natural retry until the next deploy or
webhook.

**B. Move amenity discovery to a background `asyncio.Task`, started
during lifespan but not awaited before `yield` — recommended.** The app
becomes healthy as soon as content sync (fast) finishes; amenity
discovery keeps running concurrently and updates the DB whenever it
actually completes, same end state as today, just not gating startup.
Needs care at shutdown (see below) so an in-flight task isn't abruptly
killed mid-Overpass-call on every redeploy.

**C. Move amenity discovery out of the app process entirely** (a
separate worker/cron, decoupled from both startup and request
handling). Real architectural change — a second deployable, its own
scheduling, its own failure modes to reason about. Worth keeping in mind
if this project's sync needs grow substantially, not warranted by the
problem as it exists today.

**Recommendation: B.** Smallest change that actually fixes the mismatch,
keeps the existing graceful-degradation philosophy intact, no new
deployable or infrastructure.

## The same problem exists in two other places, not just startup

Worth checking rather than assuming this is startup-specific — it isn't:

- **`POST /internal/resync`** calls `sync_posts()` the same way, awaited
  directly in the request handler. A manual resync of a route like Dream
  of North would hold the HTTP connection open for the same multi-minute
  worst case.
- **The GitHub webhook handler** does the same. This one is more urgent
  than it sounds: GitHub expects a webhook response within a short
  window and may mark the delivery as failed (visible in the repo's
  webhook delivery log as a timeout) even though the sync keeps running
  server-side regardless — a confusing false-negative for anyone
  checking whether a publish worked.

The fix in Phase 1 below should apply to all three call sites, not just
the lifespan, since it's the same root cause in three places.

## Phased implementation plan

### Phase 1 — Split content sync from amenity discovery

**Scope**
- [x] In `geo_sync.py`, split `sync_route`'s current combined behavior
  into two callable pieces: the existing fast path (GPX parse, ride
  stats, `Route` row upsert) stays as-is and stays synchronous; the
  Overpass-dependent amenity discovery becomes its own function,
  `sync_route_amenities(session, route_id, ...)`, callable
  independently.
- [x] `sync_posts()` stops taking `enable_amenity_discovery` as a
  same-call flag threaded into `sync_route`. Instead, it returns the
  list of route IDs that actually need amenity discovery this run —
  callers decide *when* to act on that list, not `sync_posts` itself.

**Done when**
- [x] A fixture test confirms content sync (post + route + stats) completes
  and is queryable even when amenity discovery is mocked to hang
  indefinitely — proves the two are genuinely decoupled, not just
  reordered. (`test_amenity_discovery_not_run_unless_explicitly_invoked`
  in `tests/integration/test_geo_sync_integration.py` — confirms
  `sync_posts()` alone makes zero Overpass calls and still correctly
  reports the route as needing amenity discovery via
  `amenity_route_ids`.)
- [x] Existing content-sync tests still pass unmodified — this is a
  refactor of *when* amenity discovery is invoked, not a behavior change
  to content sync itself.

**Design decisions made during implementation** (confirmed with the
user before proceeding, since both were judgment calls rather than
mechanical refactors):
- **`sync_posts()`'s return type**: introduced a `SyncResult` frozen
  dataclass (`upserted`, `deleted`, `skipped`, `amenity_route_ids:
  list[int]`) rather than widening the existing `dict[str, int]` return
  type with a new key. The dataclass is the honest type — it forces
  callers to read `amenity_route_ids` explicitly rather than via a
  magic dict key — and every call site needed updating either way.
  `sync_route()` itself now returns `int | None` (the route id, or
  `None` if there's no route for this post after the call), which
  `sync_posts()` collects into `amenity_route_ids`.
- **`sync_route_amenities(session, route_id, ...)`** loads the `Route`
  by id (`session.get`) and converts `route.track` back to a shapely
  linestring (`geoalchemy2.shape.to_shape`) before delegating to the
  existing `sync_amenities(session, route, linestring, ...)` — the
  re-fetch is necessary, not just convenient: by the time amenity
  discovery actually runs (Phase 2/3, a background task), the original
  content-sync session that upserted the route has already committed
  and closed, so the in-memory `Route` ORM object and its parsed
  `linestring` no longer exist. `sync_amenities` itself is unchanged and
  remains the lower-level primitive tests can call directly when they
  already have an in-memory route + linestring.
- **Integration tests that previously asserted `NearbyAmenity` rows
  existed immediately after `sync_posts(..., enable_amenity_discovery=
  True)`** now call `sync_route_amenities()` explicitly, synchronously,
  after `sync_posts()` returns — tests the amenity-sync behavior
  directly rather than depending on background-task timing, which
  would otherwise couple these tests to `app.state` / lifespan
  internals for no real benefit.

**Testing**
- Unit tests in `tests/unit/test_geo_sync.py`:
  `test_sync_route_amenities_loads_route_and_delegates` and
  `test_sync_route_amenities_missing_route_is_a_noop` (the route was
  deleted between being scheduled and actually running — entirely
  possible for the background-task path).
- `tests/unit/test_resync.py` and `tests/unit/test_webhook.py` updated
  for the `SyncResult` dataclass (were asserting on plain dicts).
  `tests/integration/test_geo_sync_integration.py`,
  `test_geocoding_integration.py`, `test_post_sync_integration.py`
  updated from `counts["upserted"]`-style dict access to
  `counts.upserted`-style attribute access.

### Phase 2 — Background task for amenity discovery at startup

**Scope**
- [x] `app/main.py`'s `lifespan`: after the (now amenity-free, fast)
  content sync completes and commits, start amenity discovery for the
  routes that need it via `asyncio.create_task(...)` — **not** awaited
  before `yield`. Task reference stored on `app.state` (a
  `set[asyncio.Task]`, not a single slot — see Phase 3's concurrency
  note below) so shutdown can find it.
- [x] On shutdown, before `dispose_engine()`: any still-running
  background task is cancelled and awaited to completion
  (`cancel_amenity_sync_tasks`). The next startup or webhook sync picks
  up where it left off — amenities are always resynced from scratch
  per route, so there's no partial-route state to lose.
- [x] `/health` reflects only content-sync readiness, unchanged from
  today's actual behavior — it never depended on amenities, this just
  makes that already-true fact also true in practice (no longer
  incidentally gated by a slow background task sharing the same
  lifespan).

**Done when**
- [x] A fixture-level equivalent of the live-deploy check: the
  lifespan's pre-`yield` phase completes well within a short timeout
  even with `enable_amenity_discovery` forced on
  (`test_lifespan_completes_without_waiting_for_amenity_discovery`,
  `tests/integration/test_lifespan_amenity_sync_integration.py`). The
  live-deploy version of this check (`docker compose ps` showing
  `healthy` in seconds regardless of Dream of North's amenity sync
  time) is **not yet verified live** — no production access from this
  sandbox; left for the user's next deploy.
- [x] A background task interrupted mid-flight by shutdown is actually
  cancelled and awaited to completion, not left racing a disposed
  engine (`test_lifespan_background_task_is_cancelled_on_shutdown`) —
  the fixture-level equivalent of "a deploy triggered while a previous
  deploy's amenity discovery is still running doesn't error." The full
  live version (two real deploys in quick succession) is likewise not
  yet verified live.

**Design decisions made during implementation:**
- **Shared driver module**: created `app/services/background_sync.py`
  (framework-free per AGENTS.md — no fastapi/jinja2/sqladmin imports,
  even though its only real caller is FastAPI's lifespan/routes) rather
  than putting scheduling logic inline in `main.py`/`internal.py`.
  Reused unchanged by all three callers (startup, resync, webhook) in
  Phase 3, so there's exactly one shutdown-cancellation code path to
  reason about.
- **`set[asyncio.Task]` on `app.state`, not a single slot**: a single
  slot would be overwritten by a second concurrent caller (e.g. a
  resync landing while the webhook's amenity task is still running),
  silently dropping the first task's only strong reference and risking
  GC before it completes. `schedule_amenity_sync()`'s task removes
  itself from the set via a done-callback on completion, so the set
  only ever holds genuinely in-flight tasks.
- **A done-callback logs any unhandled exception**
  (`_log_task_exception`) — a bare background task's exception would
  otherwise only ever surface as "Task exception was never retrieved"
  at GC time, with no useful context for debugging a real failure.
- **Errors isolated per route within the batch**
  (`sync_amenities_for_routes`): one route's Overpass failure (or any
  other exception) is logged and the loop continues to the next route
  — the existing best-effort philosophy (`sync_amenities` already
  tolerates and logs its own per-chunk failures) extended to apply
  across routes within one background batch too. `asyncio.CancelledError`
  is deliberately *not* caught the same way — it's re-raised so the
  task's own cancellation actually completes rather than being
  swallowed like a generic exception.
- **Commit ownership**: `sync_amenities_for_routes` commits once per
  route, in its own fresh session, immediately after that route's sync
  — not batched into one commit at the end. A route's amenities become
  visible as soon as they're ready rather than held back by however
  long the rest of the batch takes.

**Testing**
- `tests/unit/test_background_sync.py` (new, 10 tests): per-route
  session isolation, per-route error isolation, `CancelledError`
  propagation, empty-route-ids no-op, task registration/de-registration
  on the state set, concurrent-callers-don't-drop-references, unhandled-
  exception logging via the done-callback, and the shutdown
  cancellation path (both an in-flight task and an already-done one).
- `tests/integration/test_lifespan_amenity_sync_integration.py` (new, 2
  tests): the lifespan itself, called directly as an async context
  manager (no `asgi-lifespan` dependency added — not warranted per
  AGENTS.md's "no new dependency without a concrete need," `lifespan`
  is already just a plain async generator function, directly callable).

### Phase 3 — Apply the same fix to resync and the webhook

**Scope**
- [x] `POST /internal/resync`: same split — content sync awaited and
  reflected in the response, amenity discovery for affected routes
  kicked off as a background task via the same
  `schedule_amenity_sync()` helper, **not** held up as part of the HTTP
  response. Response body gained `"amenity_sync": "started"|"skipped"`
  so a caller isn't misled by an unqualified "done" (`"skipped"` when
  `enable_amenity_discovery` is off or there was nothing to sync).
- [x] The GitHub webhook handler: same pattern — responds to GitHub
  once content sync completes; amenity discovery continues
  independently via the same shared helper.

**Done when**
- [x] A fixture-level equivalent: a mocked amenity-sync driver that
  never gets awaited by the request/webhook handler itself, confirmed
  actually scheduled and run on the event loop *after* the response is
  already returned
  (`test_resync_schedules_amenity_task_without_blocking_response`,
  `test_webhook_schedules_amenity_task_without_blocking_response`). The
  live version (a real resync/webhook against a route needing several
  minutes of amenity discovery, confirmed via a real GitHub delivery
  log and a real `nearby_amenities` query) is **not yet verified live**
  — left for the user's next deploy + resync/webhook trigger.

**Testing**
- `tests/unit/test_resync.py` and `tests/unit/test_webhook.py`: one new
  test each, mirroring Phase 2's integration tests but at the unit
  level (FastAPI dependency overrides, no real DB) — both patch
  `sync_amenities_for_routes` itself so the test can assert it was
  awaited on the event loop without ever being awaited *by* the request
  handler.

## Explicitly out of scope

- **Moving amenity discovery to a fully separate process/worker**
  (Option C) — real infrastructure, not warranted by the problem as it
  exists today; revisit only if background-task-in-process proves
  insufficient in practice.
- **A user-facing "amenity data is still loading" indicator** on the
  post page — the toggle already correctly hides when there's no data;
  a reader hitting the page seconds after a deploy simply doesn't see
  the toggle yet, same as any other case where amenity sync hasn't
  happened, and it appears on a later page load once it has. Consistent
  with the existing best-effort philosophy, not a new UX gap to solve.

## Summary

All three phases implemented. Content sync (`sync_posts`/`sync_route`)
no longer touches Overpass at all; amenity discovery is a separate,
explicitly-scheduled step (`sync_route_amenities`) run as a background
`asyncio.Task` via a shared driver (`app/services/background_sync.py`)
from all three call sites that previously blocked on it inline: the
lifespan startup, `POST /internal/resync`, and the GitHub webhook
handler. A `set[asyncio.Task]` on `app.state` (not a single slot) tracks
in-flight tasks across all three so concurrent callers don't drop each
other's references, and one shutdown handler
(`cancel_amenity_sync_tasks`) cancels and awaits every still-running one
before the DB engine is disposed.

`make ci`: 286 passed, 95.57% coverage, security checks clean.

## Recommended next steps

- **Live verification (all three phases)** — not possible from this
  sandbox, no production access. On the next deploy:
  - Phase 2: `docker compose ps` should show `healthy` within seconds,
    not the several-minutes wait this whole doc exists to fix, even
    while Dream of North's amenity discovery keeps running in the
    background (watch `docker compose logs app | grep -i "amenity"`
    for the background task's own log lines continuing after
    `/health` is already serving 200s).
  - Phase 3: trigger a manual resync of a route needing amenity
    discovery and confirm the HTTP response returns in roughly
    content-sync time alone, with `"amenity_sync": "started"` in the
    body; separately confirm a real GitHub webhook delivery shows `200`
    in the repo's delivery log (not a timeout) even when that push
    touches a slow-to-discover route.
  - Also worth confirming directly: a redeploy triggered while a
    previous deploy's background amenity task is still mid-Overpass-
    call doesn't error or leave `nearby_amenities` in a partial state —
    the cancel-on-shutdown path is only proven safe here against a
    fixture-level mock, not a real in-flight httpx call being
    interrupted.
- **Phase 3's noted concurrency question** (flagged during planning,
  not blocking): a resync and a webhook delivery landing close together
  now each schedule their own background amenity task independently.
  `sync_amenities`'s rate-limit clock (`_last_overpass_time`) is
  module-level/process-global, so two concurrent tasks calling it
  should still serialize against each other rather than doubling
  Overpass's effective request rate — this was reasoned about but not
  exercised under real concurrent load. Worth confirming with a real
  double-trigger (e.g. a resync fired manually right after a webhook
  push) if it comes up in practice; not worth a synthetic test for a
  scenario that may never actually occur given the existing per-route
  cooldown already discourages rapid re-triggering of the same route.