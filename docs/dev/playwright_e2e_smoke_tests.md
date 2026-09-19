# Playwright — a browser-level test tier, scoped to what unit tests can't see

> Direct response to a real production bug: a MapLibre style-validation
> failure took down the entire map (base tiles included), while 405
> unit tests passed and CI stayed green. Root cause of the *miss*, not
> just the bug: every `post-map.js`/`elevation-chart.js` test in this
> project checks that certain strings exist in the file — none of them
> execute the JavaScript. That's not a gap in test count, it's a
> category of failure the current approach cannot see at any coverage
> percentage.

---

## What actually needs catching, grounded in the real incident

The bug: `adjustLocalityLabelPriority()` composed a filter mixing
legacy MapLibre filter syntax (the vendored library's own
`["==", "kind", "locality"]`) with modern expression syntax
(`["!=", ["get", "kind_detail"], "locality"]`) inside one `"all"`
combinator — invalid, and severe enough that the *entire* style
failed to load, not just the one layer.

**The precise, minimal thing that would have caught this**: MapLibre
emits a real `error` event on the map instance when style loading
fails. A test that loads a real page in a real browser, attaches an
error listener before the map initializes, and asserts zero fired,
would have failed immediately and specifically — not a vague "the page
looks different" visual-diff signal, the actual mechanism.

## Scope — deliberately narrow, not "full UI test coverage"

**This is a smoke-test tier, not a comprehensive one.** The goal is
catching exactly the class of failure that just shipped — a script
error that silently breaks a page while every existing test stays
green — not exhaustively testing every interaction. Concretely, for
each of the three post types (with route, with POIs but no route, with
neither):

- [ ] Page loads with HTTP 200 and no `console.error`/`pageerror`
  events at all during load.
- [ ] For posts with a route: the map canvas exists and MapLibre's
  `error` event never fired — the direct check for exactly this bug
  class.
- [ ] The elevation chart canvas exists and has non-trivial rendered
  content (not a blank canvas) — same reasoning, different renderer.
- [ ] Each existing toggle (theme light/dark, fullscreen, "Show nearby
  services") can be clicked and doesn't throw — not verifying every
  visual outcome of each toggle, just that the interaction itself
  doesn't error.

**Explicitly not in scope for this phase**: pixel-level visual
regression testing, testing every amenity category's icon rendering
individually, cross-browser matrix testing. All real, all more than
this specific incident calls for — start with what would have caught
*this* bug, expand later only if a real gap shows up the same way this
one did.

## Where this fits — a third tier, not a philosophy change

This project already has a real precedent for "needs the actual real
thing running, not a mock": `tests/integration/` needs a real
PostGIS instance, spun up as a CI service container. Playwright tests
need the same kind of real dependency, one level up — a real running
app process for a real browser to point at. Same shape of decision
already made once, applied to the next tier:

```
tests/unit/         — no database, no external services (existing)
tests/integration/  — real PostGIS via CI service container (existing)
tests/e2e/           — real app process + real PostGIS, real browser (new)
```

## Design

**Test fixture, not real content**: a small, dedicated fixture post
with a route (checked into `tests/e2e/fixtures/`, a minimal real GPX)
rather than relying on actual blog posts — real content can be edited
or deleted over time; a stable fixture keeps these tests from breaking
for reasons unrelated to the code being tested.

**CI wiring**: start the actual app (`uvicorn app.main:app`) as a
background process against the same PostGIS service container already
used for integration tests, seed it with the fixture post via the
existing sync machinery (not a hand-rolled DB insert — exercising the
real sync path is itself worth something), point Playwright at
`localhost:8000`, run the smoke checks, tear down.

**No Allure — considered and rejected, same reasoning as self-hosted
SonarQube.** Allure's real value is rich historical trend dashboards
and shareable HTML reports for teams communicating test health to
people who don't read raw CI output. This is a solo project where
`make ci`'s plain pass/fail-plus-coverage summary has worked
consistently every time it's been checked this session. Adding a
reporting platform sized for a multi-person team's communication needs
is solving a problem this project doesn't have — the same shape of
disproportionate-tooling decision already made once and correctly
avoided.

## Phased implementation plan

### Phase 1 — Playwright setup + the fixture

**Scope**
- [x] Add Playwright as a dev dependency, Python bindings (consistent
  with the rest of the stack — no reason to introduce a Node-based test
  runner into a project that's deliberately avoided Node/npm
  everywhere else). Its own `e2e` dependency group
  (`uv add --group e2e pytest-playwright`), not folded into `dev` — so
  `uv sync --group security` (what CI's lint/test/security steps use)
  never pulls in Playwright at all, and the existing lean steps stay
  unaffected.
- [x] `tests/e2e/fixtures/` with one minimal, stable GPX + post fixture
  covering the three post-type variants (route, POIs-only, neither).
- [x] Local `make e2e` target for running this tier against a locally
  running dev stack, independent of CI.

**Done when**: Playwright installs cleanly, browsers download
successfully in this project's environment, and the fixture post syncs
and renders when manually checked once.

*Real deviation from plan*: this sandboxed dev environment's network
blocks Playwright's own browser-binary CDN (`cdn.playwright.dev`) —
confirmed via a real timeout, not assumed. `make e2e` uses
`--browser-channel=chrome` (a real Google Chrome already installed on
this machine) instead, verified working end-to-end. CI's own runners
have normal internet access, so the CI step instead uses Playwright's
conventional, portable `playwright install --with-deps chromium` —
documented as two different (both real, both verified) paths rather
than picking one and hoping it generalises.

### Phase 2 — The actual smoke checks

**Scope**
- [x] The four checks listed above, implemented as real Playwright
  tests against the fixture post(s).
- [x] Specifically: a test that would have failed against the exact
  commit that introduced the `adjustLocalityLabelPriority` bug — worth
  literally checking this out against that commit once, to confirm the
  new test actually catches it, not just that it passes against
  already-fixed code.

**Done when**
- [x] All four checks pass against current, correct code — 9/9 e2e
  tests passing.
- [x] Checking out the specific broken commit (`91f79b7`'s
  `post-map.js`, via `git show`, not a full checkout) and re-running
  shows the new test failing with a clear signal: the exact MapLibre
  `error` event strings from the real incident
  (`layers[69].filter[2][1]: string expected, array found` and
  `layers[71]...`) — proof this closes the actual gap, not just adds
  test count. Restored the working file immediately after (confirmed
  zero `git diff` afterwards).

**Testing**: this phase *is* the testing — no meta-tests needed.

### Phase 3 — CI integration

**Scope**
- [x] New CI step: start the app in the background against the
  existing PostGIS service container, run the e2e tier, tear down.
- [x] Runs alongside, not instead of, the existing unit/integration
  tiers — all three gate merges (same `ci` job, sequential steps).

**Done when**: a PR that reintroduces the exact class of bug this doc
is named for gets a red CI check specifically from the e2e tier, not
just from someone noticing manually.

*Verified indirectly, not via a live PR* (no `gh`/token access this
session, same limitation noted in `security_review_owasp.md`'s
Leftover for its own ZAP/SonarCloud workflow triggers) — Phase 2's
broken-commit check already proves the *test itself* fires correctly
on this exact bug class; what's unverified is only the *CI plumbing*
around it (browser install step, `uv run --group e2e` on a real GH
Actions runner). Flagged honestly below rather than claimed as fully
proven.

**Testing**: the CI workflow running successfully end-to-end on a real
PR is the test.

## Explicitly out of scope

- **Allure or any test-reporting dashboard** — see above.
- **Visual/pixel regression testing** — a real, different testing
  discipline (screenshot diffing, baseline management, flakiness from
  font rendering differences across environments) — worth its own
  future consideration, not bundled into catching *this* bug class.
- **Cross-browser testing** (Firefox, Safari/WebKit engines) —
  Chromium-only for this phase; real cross-browser coverage is a
  genuine future expansion, not needed to catch a style-validation
  failure that's browser-engine-independent.
- **Testing every amenity/POI category's individual rendering** — the
  smoke checks confirm the *mechanism* (map loads, no errors) works;
  exhaustive per-category visual verification is a different, much
  larger effort not justified by this specific incident.

## Summary

All three phases implemented. `tests/e2e/` is a genuinely separate
tier: real Postgres/PostGIS, a real `uvicorn app.main:app` subprocess,
a real Chrome, seeded via the real `sync_posts()` path against three
check-in fixture posts covering all three post-type variants. Ignored
by default `pytest`/`make test`/`make ci` (`--ignore=tests/e2e` in
`addopts`), run explicitly via `make e2e` locally or the CI job's own
dedicated steps.

**The regression test does what the doc set out to prove**: checked
out the exact commit that shipped the real incident's bug
(`91f79b7`'s `post-map.js`, via `git show`, not a disruptive full
checkout) and confirmed `test_map_renders_without_maplibre_error_event`
fails with the *exact* real error strings
(`layers[69].filter[2][1]: string expected, array found` /
`layers[71]...`) — not a vague signal, the precise mechanism the doc
named.

**Two real, pre-existing bugs found and fixed along the way, neither
hypothetical**:

1. **The real GitHub Actions CI has been failing on every push this
   session, silently, at the "Test" step** — `ci.yml` never applied
   Alembic migrations to its ephemeral PostGIS service container.
   `make ci` run locally always looked green because it always ran
   against the already-migrated persistent local dev DB; the real,
   pushed CI run never did. Confirmed via GitHub's own Actions API
   (every recent run showing `"conclusion":"failure"`), then
   reproduced locally against a genuinely fresh `postgis/postgis:16-
   3.4` container (62 `UndefinedTable` errors), then fixed with a new
   "Apply database migrations" step and re-verified clean against the
   same fresh container. This had nothing to do with Playwright
   directly — found only because Phase 3 required reasoning carefully
   about what the CI service container actually guarantees.
2. **This tier's own fixture seeding silently deleted the real local
   dev posts** (`dream-of-north`, `feldberg-summit-loop`,
   `sunday-gravel-loop`) the first time it ran. `sync_posts()`
   reconciles by deleting any DB row whose slug isn't in the given
   directory's file set — not scoped to that directory in any way —
   so pointing it at `tests/e2e/fixtures/` against the same shared
   `DATABASE_URL` used for local dev wiped real content. Restored
   immediately (`sync_posts()` against the real `content/posts/`
   again), then fixed at the design level: `tests/e2e/conftest.py` now
   creates and uses a dedicated `<db>_e2e` database (via the
   `postgres` maintenance DB, since `CREATE DATABASE` can't run inside
   a transaction), fully isolating this tier's destructive
   reconciliation from any real content in both local dev and CI.
   Production is a fully separate database on a different host and
   was never at risk.

**Testing**: 9 new e2e tests (`tests/e2e/test_smoke.py`), all passing
against current code, all confirmed to fail meaningfully against the
broken commit for the one test that specifically targets it. `make
ci`: 407 unit + integration tests passed, 96.33% coverage, security
clean, unaffected by the new tier (verified `--ignore=tests/e2e`
actually excludes it from the default run). `make e2e`: 9/9 passed,
run both standalone and after a full `make ci` run.

## Leftover

- **The exact same destructive-reconciliation exposure already exists
  in `tests/integration/`, and is real, not theoretical** — found
  while restoring local dev content a second time: after a full `make
  ci` run, the shared local dev DB ended up containing
  `test_routes_integration.py`/`test_post_map_integration.py`'s own
  `tmp_path`-based "kinzig" test fixtures instead of the real posts.
  Individual integration tests using `tmp_path` + `sync_posts()`
  against the real, shared `DATABASE_URL` have always had this same
  exposure; the *net* result after a full run has apparently only ever
  looked correct because some later-running test's own lifespan
  happens to re-sync the real `content/posts/` directory before the
  session ends — a coincidence of file/test collection order, not a
  guarantee. Restored real content again (confirmed:
  `dream-of-north`/`feldberg-summit-loop`/`sunday-gravel-loop` present
  after this task). Out of scope to fix here — this task's job was
  building the e2e tier without repeating the same mistake, not
  auditing/fixing the existing integration suite — but the fix would
  be the same shape as this doc's own `_ensure_e2e_database()`: give
  `tests/integration/` its own dedicated `<db>_integration` database
  too, the same way `tests/e2e/` now has `<db>_e2e`. Worth its own
  follow-up task; flagging concretely rather than leaving it to be
  rediscovered painfully again.
- **CI Phase 3's plumbing (browser install step, `uv run --group e2e`)
  verified locally with the equivalent commands, not via an actual
  GitHub Actions run** — no `gh`/token access this session to trigger
  or inspect a real push-triggered run against these exact new steps.
  The migration-gap fix (Leftover item above, no — Summary item) *was*
  independently confirmed via the real Actions API showing genuine
  past failures; the new e2e CI steps added this session haven't yet
  had a real run to inspect the same way, simply because they're new
  as of this commit.
- **`make e2e`'s local default (`--browser-channel=chrome`) requires a
  real Chrome install** — works on this machine, matches this
  session's own established workaround for the sandboxed network's
  CDN block, but isn't universally portable to every developer
  machine. Documented as a known constraint rather than silently
  assumed; a machine without Chrome installed would need to either
  install it or run `uv run --group e2e playwright install chromium`
  once (CI's own path) and drop `--browser-channel=chrome` from the
  Makefile target.
- **Amenity toggle test seeds exactly one hand-inserted `NearbyAmenity`
  row directly**, not via a real Overpass call — deliberate (a live
  Overpass dependency would make this tier flaky/slow for a reason
  unrelated to what it actually checks), documented in
  `conftest.py`'s own module docstring, but worth restating here: this
  tier does not exercise real Overpass discovery at all — that's
  `tests/integration/test_geo_sync_integration.py`'s job, already
  covered there.