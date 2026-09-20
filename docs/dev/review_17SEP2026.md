# BulliExplorer — Implementation Review (Sept 2026)

> Full-codebase review after the Maps & GIS / R2 / Overpass / amenity
> overlay arc. Companion to the KPI rating table (presented in chat,
> reproduced in short form at the end). Every finding below was verified
> against the actual code or observed production behavior — file/line
> references included so nothing here needs re-diagnosing.
>
> Baseline at review time: 248 unit tests passing, 84.16% unit coverage
> (~93% incl. integration), `make ci` green, all three routes serving
> correctly in production with live amenity data.

---

## Top findings, prioritized

### F1 — ~3.7MB of GeoJSON inlined into the HTML document (HIGH, performance)

**Evidence**: `templates/post.html:76` — `const AMENITIES_GEOJSON =
{{ amenities_geojson | tojson }};`. Dream of North has 15,686 amenities;
with `tags` now included per `fix_amenity_overlay_ux.md` Phase 3, the
serialized FeatureCollection is roughly **3.7MB inside the HTML
document itself**. Dynamic pages are deliberately not cached (correct,
per the static-caching fix), so **every visit re-downloads it** — and
the "Show nearby services" toggle defaults *off*, so most readers pay
the full cost for data they never look at.

**Recommendation**: move amenities out of the page into
`GET /posts/{slug}/amenities.geojson`, fetched **lazily on first toggle
check**. Most readers then transfer zero amenity bytes; the endpoint
can carry an ETag (data only changes on sync), so even repeat toggle
users revalidate cheaply. Route/POI GeoJSON can stay inline — they're
small and always needed. This is the single highest-value remaining
performance fix, and it's a contained one: one new route handler, one
`fetch()` in the toggle handler, `setData()` on the existing source.

### F2 — `javascript:` scheme survives into amenity website links (MEDIUM, security)

**Evidence**: `templates/post.html:201-204` — `tags.website` (raw OSM
third-party data) is rendered as `<a href='...'>` after `escapeHtml()`.
Escaping prevents breaking out of the attribute, but a `javascript:...`
value is a perfectly valid escaped string — it survives intact as a
clickable link. Requires a click, and requires someone planting a
malicious `website` tag in OSM near a route, so exploitability is low —
but it's real third-party data flowing into an executable context.

**Recommendation**: scheme allowlist before rendering — only emit the
link when the value starts with `http://` or `https://`. One `if`, and
the popup already handles "no website" gracefully.

### F3 — Resync token compared with plain `!=` (LOW-MEDIUM, security consistency)

**Evidence**: `app/routes/internal.py:99` — `token !=
settings.resync_token`, a non-constant-time comparison, while
`_verify_github_signature` (line 227, same file) correctly uses
`hmac`-based verification. Timing attacks against this are impractical
over the public internet for this threat model, but the inconsistency
is exactly the kind that gets copied into the next endpoint.

**Recommendation**: `secrets.compare_digest(token, settings.resync_token)`.
One line, matches the standard the webhook already sets.

### F4 — `templates/post.html` is a 768-line inline-JS monolith (MEDIUM, architecture)

**Evidence**: all map logic — route rendering, POI markers, the
clustered amenity overlay, icon canvas generation, popup building,
theme-swap `transformStyle`, fullscreen modal — lives inline in one
Jinja template. Consequences, all concrete: the JS can't be cached by
the browser (re-downloaded with every HTML response, compounding F1),
can't be linted (`djlint` checks the template, nothing checks the JS),
and can't be unit-tested even where pieces are testable in isolation
(`escapeHtml`, `buildAmenityPopupHtml`, the phone-parsing logic —
pure functions currently untestable only because of where they live).

**Recommendation**: extract to `static/js/post-map.js`, template passes
data via the existing inline `const` block (which stays — data belongs
in the page, behavior doesn't). No bundler needed — one plain script
file, consistent with the project's no-build-step architecture. Do this
*before* the next map feature, not after; the file only grows.

### F5 — Duplicate per-worker startup sync (LOW-MEDIUM, architecture)

**Evidence**: `Dockerfile:49` runs uvicorn `--workers 2`; each worker
process runs the full lifespan, so **content sync runs twice on every
deploy** (harmless but wasteful — double parsing, double upserts racing
on the same rows) and the amenity cooldown check has a small race
window (both workers can read a stale `amenities_synced_at` before
either commits). Observed directly in production logs earlier in this
project (the staggered double "Skipping..." batches).

**Recommendation**: cheapest correct fix is a Postgres advisory lock
(`pg_try_advisory_lock`) around the startup sync — first worker takes
it and syncs, second sees it held and skips. No new infrastructure,
one well-documented Postgres feature.

### F6 — No Docker log rotation configured (LOW-MEDIUM, operations)

**Evidence**: `docker inspect` earlier showed `LogConfig: {"Type":
"json-file","Config":{}}` — daemon defaults, no explicit `max-size`/
`max-file`. Two consequences already experienced: the unexplained
missing 08:46-08:48 log window during the sync investigation, and
unbounded log growth risk on a 4GB host from a chatty app (Overpass
warnings alone are high-volume on bad days).

**Recommendation**: `logging: driver: json-file, options: {max-size:
"10m", max-file: "5"}` on the app service in `docker-compose.prod.yml`.
Also fixes reproducibility of future log investigations (a known
window, not a mystery).

### F7 — Mixed log formats: uvicorn plain-text, app JSON (LOW, operations)

**Evidence**: every production log dump this project has examined shows
`INFO: 172.18.0.2:... "GET / HTTP/1.1" 200 OK` (plain) interleaved
with `{"time":..., "level":...}` (JSON). Any future log ingestion or
even careful grepping has to handle both formats.

**Recommendation**: configure uvicorn's access logger through the
existing `log_factory` JSON formatter (uvicorn supports `--log-config`
/ programmatic logging config), or accept and document the split
deliberately. Low urgency; becomes real the day logs get shipped
anywhere.

**Doc-drift audit correction**: the *specific* per-request example
cited above (`"GET / HTTP/1.1" 200 OK`) no longer reproduces —
`Dockerfile`'s uvicorn `CMD` gained `--no-access-log` in `cb4fb03`
("Add German legal pages and minimize monitoring data"), a later,
unrelated commit, which suppresses exactly that per-request access-log
line. Confirmed this landed *after* this review was written (`cb4fb03`
is not an ancestor of this doc's own creation commit `d38e705`), so the
evidence was accurate at the time, just never revisited once an
unrelated change happened to resolve part of it. The narrower general
finding still holds, unresolved: uvicorn's own startup/lifecycle
messages (`INFO: Application startup complete`, etc.) remain
plain-text, still distinct from the app's JSON logs — just not via the
specific access-log example originally given.

---

## Tech debt register (smaller items, tracked so they don't need re-finding)

| Item | Where | Status/note |
|---|---|---|
| `post_sync.py` 47% unit coverage | `tests/` | Core loop covered only via integration tests; a DB-mocked unit path for the parse/upsert loop would catch regressions without a live Postgres. |
| Curated-POI popup doesn't escape `name`/`notes` | `post.html:511-513` | Author-controlled data, so not third-party-exploitable — but `escapeHtml` exists 300 lines above and should simply be used consistently. |
| `.js.map` 404s | `static/vendor/` | Cosmetic console noise. Either vendor the two map files or strip the `sourceMappingURL` comment from the vendored bundles. |
| `TILES_URL` on free `pub-*.r2.dev` | server `.env` | The documented rate-limit risk class from `fix_service_overlay.md` (the incident was a false alarm; the structural concern was validated as real). Custom-domain migration remains the eventual fix. |
| R2 API token possibly still Admin R&W | Cloudflare dashboard | Left over from a debugging detour (`media_storage_r2.md` housekeeping); should be Object R&W scoped to the one bucket. |
| Orphan R2 test object | R2 bucket | Tracked in `media_storage_r2.md`; delete whenever convenient. |
| GitHub PAT rotation | — | Tracked earlier; owner has explicitly deferred. Listed for completeness only. |
| ~~No DB backups~~ — 🚧 scripted, restore untested | bucket #7 | **Implemented** — see "Housekeeping batch" below. `scripts/backup_db.py` + host crontab, 14-day retention, unit-tested. Still open: installing the crontab on the real production host and running one real restore test — both need production/R2 access this environment doesn't have. |
| ~~`docs/dev/` sprawl~~ — ✅ done | 22 files | **Implemented** — see "Housekeeping batch" below. `docs/dev/README.md` added (active / historical / documented-false-lead / config groupings). |

## Architecture anti-patterns — named honestly, with the defense where one exists

1. **Behavior in templates** (F4) — the only finding here that's a
   genuine anti-pattern by any standard. Grew incrementally for locally
   good reasons (each phase added "just a bit more" inline); the sum is
   now past the threshold.
2. **Module-level mutable state as rate limiter** (`_last_overpass_time`,
   `geo_sync.py`) — fine within one process, silently wrong across
   workers (2 procs = 2× the intended rate). Defensible at current
   scale; should be *documented as per-process* at minimum, fixed via
   the F5 advisory lock at best (a single syncing worker makes the
   question moot).
3. **Lifespan work coupled to worker count** (F5) — the framework runs
   lifespan per worker; the code assumes it runs once. Classic
   FastAPI/uvicorn footgun, now with an observed symptom here.
4. **Not an anti-pattern, worth saying**: the five-layer Overpass
   resilience stack (timeout → mirror → split → 429 backoff →
   incremental writes) could read as over-engineering out of context.
   It isn't — every layer maps to a distinct, observed, logged
   production incident. That's the correct amount of engineering,
   arrived at the correct way.

## What's genuinely strong (so the register above reads in proportion)

- **Evidence-first debugging culture**: two false leads
  (R2-throttling, `.js.map` 404s / extension noise) were caught
  *before* building fixes for non-problems, and documented rather than
  deleted. The Admin-R&W-vs-CORS lesson was learned once and applied
  repeatedly.
- **Schema discipline**: 7 clean Alembic migrations, zero
  `create_all` mixing (verified by grep, not assumed).
- **Testing that maps to behavior**: test names read as claims about
  the system (`...rate_limited_reported_even_when_split_eventually_succeeds`),
  and the subtle cases (boundary dedup, split-area coverage, cooldown-
  on-failure) are the ones covered — not just happy paths.
- **Graceful degradation as a consistent philosophy**: amenities,
  geocoding, and tile coverage all fail toward "less enrichment,"
  never toward a broken page.

## Recommended order of attack

1. **F1** (lazy amenity endpoint) — biggest reader-facing win, contained.
2. **F2 + F3 + POI-popup escaping** — one small security-consistency
   commit, three one-liners.
3. **F6** (log rotation) — two lines of YAML, prevents the next
   missing-logs mystery.
4. **F4** (extract post-map.js) — before the next map feature lands.
5. **F5** (advisory lock) — with F4's commit or after.
6. Backup cron + docs index — housekeeping batch, no urgency.

## KPI summary (full table in the chat review)

Coverage 8 · Docs 9 · Architecture 7 · Resilience 9 · Security 6 ·
Performance 6 · Ops 6 · Data 7 · Frontend 6 · Process 9 — **~7.3/10
overall**: concentrated, known weak spots against a genuinely strong
foundation; nothing here requires rework, only completion.

---

## Implementation log

Working through the "Recommended order of attack" above, one commit per
item, `make ci` green before each commit. Each task gets a **Done when**
defined *before* implementation starts, then a **Summary** once finished.

### F1 — Lazy amenity GeoJSON endpoint

**Done when**
- [x] A new `GET /posts/{slug}/amenities.geojson` route returns the same
  `FeatureCollection` shape `_amenities_to_geojson()` already produces,
  200 with an `ETag` header derived from the route's
  `amenities_synced_at` (or a fixed value when there's no route/no
  amenities), 404 for an unknown slug, and an empty `FeatureCollection`
  (not 404) for a post with a route but zero amenities.
- [x] `templates/post.html` no longer inlines `AMENITIES_GEOJSON` —
  `amenities_geojson` is dropped from `post.html`'s Jinja context/inline
  `<script>` block entirely.
- [x] The amenities GeoJSON source is populated lazily: fetched with
  `fetch()` only the first time the "Show nearby services" checkbox is
  checked, then `map.getSource('amenities').setData(...)` — not fetched
  on page load, not re-fetched on subsequent toggles within the same
  page view.
- [x] Unchecking/rechecking the toggle after the first successful fetch
  does not re-fetch — same in-memory data is reused, only visibility
  changes. Implemented via `amenitiesLoaded`/`amenitiesLoading` closure
  flags; **not yet verified live in a browser** — same sandbox
  limitation already documented for every other MapLibre-interaction
  phase in this project's docs.
- [x] A post with no route, or a route with zero amenities, never
  triggers the fetch and never shows the toggle — `has_amenities`
  (a `SELECT id ... LIMIT 1` existence check) replaces
  `amenities_geojson.features` truthiness as the toggle's render
  condition.
- [x] `make ci` green: existing unit/integration tests updated for the
  new route/removed inline data pass, plus new unit tests for the
  endpoint (404 on unknown slug, empty collection for a route with no
  amenities, correct FeatureCollection for a route with amenities,
  ETag present).
- [x] `templates/post.html`'s byte size for a page with 15k+ amenities
  drops by the amenities payload — confirmed by a new integration test
  (`test_post_detail_no_longer_inlines_amenity_data`) asserting the
  amenity's name does not appear anywhere in the post-detail HTML
  response when an amenity exists for the route.

**Summary**: Added `GET /posts/{slug}/amenities.geojson`
(`app/routes/posts.py`) returning the same `FeatureCollection` shape
`_amenities_to_geojson()` already produced, with an `ETag` derived from
`route.amenities_synced_at` (or `"never"` when unset). `post_detail` no
longer queries/serializes the full `NearbyAmenity` row set — it now runs
a cheap `SELECT id ... LIMIT 1` existence check (`has_amenities`) purely
to decide whether to render the "Show nearby services" toggle at all,
replacing the pattern of materializing every amenity server-side just to
test `amenities_geojson.features` truthiness in the template. The inline
`<script>` block in `templates/post.html` no longer defines
`AMENITIES_GEOJSON`; the amenities GeoJSON source is registered on
`map.on("load", ...)` with an empty `FeatureCollection` placeholder, then
populated via one `fetch()` + `source.setData()` the first time the
toggle is checked (guarded by `amenitiesLoaded`/`amenitiesLoading` flags
so it fires exactly once per page view, not on every toggle). A failed
fetch is caught and logged, not surfaced as a broken page — same
graceful-degradation philosophy as the rest of the project.
`templates/partials/route_stats.html`'s toggle-visibility condition moved
from `amenities_geojson.features` to `has_amenities`.

Tests: 5 new unit tests (`tests/unit/test_amenities_endpoint.py`) cover
404 on unknown slug, 404 on a route-less post, empty `FeatureCollection`
for a route with zero amenities, correct feature/tag serialization, and
the `ETag` header. 4 new integration tests added to
`tests/integration/test_post_map_integration.py` round-trip a real
`NearbyAmenity` row's PostGIS geometry through the live endpoint
end-to-end (required per AGENTS.md — any change touching `NearbyAmenity`
needs a real-DB geometry round-trip test, and this change touches how
its data reaches the browser), and confirm the amenity's name no longer
appears anywhere in the post-detail HTML response. Existing
`test_templates.py` mock-session fixtures updated: the fourth
`db.execute()` call in the post-detail path now returns a
`scalar_one_or_none()` result (existence check) instead of a
`scalars().all()` list.

`make ci`: 305 passed (was 293), 95.88% coverage, security checks clean.

**Files touched**: `app/routes/posts.py`, `templates/post.html`,
`templates/partials/route_stats.html`, `tests/unit/test_templates.py`,
`tests/unit/test_amenities_endpoint.py` (new),
`tests/integration/test_post_map_integration.py`.

### F2 + F3 + POI-popup escaping — one security-consistency commit

**Done when**
- [x] `buildAmenityPopupHtml`'s website link only renders when
  `tags.website`/`tags["contact:website"]` starts with `http://` or
  `https://` (case-insensitive scheme check) — a `javascript:`,
  `data:`, or any other scheme is silently dropped, same as the "no
  website" case today (no empty placeholder row).
- [x] `app/routes/internal.py`'s `_require_resync_token` uses
  `secrets.compare_digest(token, settings.resync_token)` instead of
  `token != settings.resync_token`.
- [x] The curated-POI popup in `templates/post.html` (`buildCategoryMarkerElement`'s
  popup, currently `"<strong>" + props.name + "</strong>"` +
  `props.notes` unescaped) uses `escapeHtml()` for `name`/`notes`, same
  as the amenity popup already does — author-controlled data, so not
  exploitable today, but inconsistent with the escaping convention used
  two hundred lines below for a reason that no longer applies once both
  paths are equally safe to make consistent.
- [x] `make ci` green — existing resync-token tests
  (`tests/unit/test_resync.py`) continue to pass with the swapped
  comparison (a `compare_digest` mismatch/match behaves identically to
  `!=` for the existing correct/incorrect-token test cases, confirmed —
  no existing assertions needed to change, only the implementation
  underneath them). No new automated test for the scheme-allowlist/
  popup-escaping — client-side WebGL/DOM logic, same "not meaningfully
  unit-testable" reasoning already established throughout this
  project's map-feature docs.

**Summary**: Three one-line-ish fixes in one commit, as planned:

1. **F2** — `buildAmenityPopupHtml`'s website link in `templates/post.html`
   now only renders when `tags.website`/`tags["contact:website"]` matches
   `/^https?:\/\//i` — a `javascript:`/`data:`/any-other-scheme value is
   silently dropped, same as the pre-existing "no website tag" case (no
   placeholder row). `escapeHtml()` was already correctly preventing an
   attribute break-out; this closes the remaining gap where an escaped-
   but-still-executable scheme could survive as a clickable link.
2. **F3** — `app/routes/internal.py`'s `_require_resync_token` now uses
   `secrets.compare_digest(token, settings.resync_token)` instead of
   `token != settings.resync_token`, matching the constant-time standard
   `_verify_github_signature` already sets in the same file.
3. **POI-popup escaping** (tech-debt register) — the curated-POI popup's
   `name`/`notes` now go through the same `escapeHtml()` the amenity
   popup already uses, removing the one asymmetry between the two popup
   builders (author-curated content, so not exploitable today, but
   inconsistent for no remaining reason).

**Testing**: F2/POI-escaping are client-side WebGL/DOM logic — same
"not meaningfully unit-testable" reasoning already established
throughout this project's map-feature docs (verified instead via
`node -c` syntax-checking the extracted script with Jinja placeholders
substituted, and `djlint templates/ --check` staying clean). F3 is
covered transitively by the existing `tests/unit/test_resync.py` token
tests (`test_resync_wrong_token_returns_401`,
`test_resync_correct_token_returns_200`) — a `compare_digest` mismatch/
match behaves identically to `!=` for both cases, so no test assertions
needed to change, only the implementation underneath them.

`make ci`: 305 passed, 95.89% coverage, security checks clean.

**Files touched**: `app/routes/internal.py`, `templates/post.html`.

### F6 — Docker log rotation

**Done when**
- [x] `docker-compose.prod.yml`'s `app` service has an explicit `logging`
  block (`driver: json-file`, `max-size: "10m"`, `max-file: "5"`) instead
  of relying on the Docker daemon's unbounded defaults.
- [x] The YAML change alone doesn't need `make ci` (no Python/JS touched)
  but must still parse — verified with `python3 -c "import yaml;
  yaml.safe_load(open('docker-compose.prod.yml'))"`.

**Summary**: Added a `logging` block to the `app` service in
`docker-compose.prod.yml` — `json-file` driver, `max-size: "10m"`,
`max-file: "5"` (50MB rolling cap total). No `db`/`caddy` service change —
the finding was specifically about the app's own log volume (Overpass
warnings are the high-volume case named in the finding); `db`/`caddy` log
at a much lower, unremarkable rate. Directly addresses both symptoms in
the finding: unbounded growth risk on the 4GB host, and the unexplained
missing 08:46-08:48 log window from an earlier investigation (a future
investigation now has a known, bounded log retention window instead of an
unexplained gap).

**Testing**: no test suite covers Docker Compose YAML (nothing in this
project exercises `docker-compose.prod.yml` under pytest — it's deploy
configuration, not application code). Verified by parsing the file with
PyYAML directly (`yaml.safe_load`) to confirm it's still valid YAML, and
by diffing against `git show HEAD:docker-compose.prod.yml` to confirm the
two pre-existing lint findings on this file (a long line in the
healthcheck command, no trailing newline at EOF) predate this change and
aren't newly introduced.

**Files touched**: `docker-compose.prod.yml`.

### F4 — Extract `templates/post.html`'s inline JS to `static/js/post-map.js`

**Done when**
- [x] All post-map behavior code (route rendering, curated-POI markers,
  the clustered amenity overlay, runtime icon-canvas generation, popup
  builders, the theme-swap `transformStyle` carry-over, the full-screen
  modal) moves out of `templates/post.html`'s inline `<script>` into a
  new plain `static/js/post-map.js` — no bundler, one script file,
  consistent with the project's no-build-step architecture.
- [x] `templates/post.html` keeps a small inline `<script>` block that
  only sets data (`window.BULLIEXPLORER_MAP_DATA = { routeGeojson,
  poisGeojson, amenitiesGeojsonUrl, tilesUrl }`) via the existing
  `|tojson` filter — data belongs in the page, behavior doesn't — then
  loads `static/js/post-map.js` via a normal `<script src>` tag, after
  the existing vendor `<script>` tags.
- [x] `static/js/post-map.js` contains zero Jinja templating — reads its
  input exclusively from `window.BULLIEXPLORER_MAP_DATA`, so the browser
  can cache it across page loads/posts instead of re-downloading
  identical behavior code with every HTML response.
- [x] `djlint templates/ --check` (the CI-gating template linter) stays
  clean, and the extracted file has no JS syntax errors — verified with
  `node -c static/js/post-map.js` (this file, unlike the inline block it
  replaced, has no Jinja placeholders to substitute first — it's now
  parseable by a plain JS tool directly, which is itself part of the
  point of this fix).
- [x] `make ci` green — existing tests that asserted on inlined JS
  behavior code (`function cyclingLayers(flavor)`, `kind_detail`
  filters, etc.) updated to read `static/js/post-map.js` directly
  instead of the post-detail HTML response; tests that only asserted on
  *data* (`routeGeojson`/`poisGeojson` values, `FeatureCollection`,
  `LineString`) continue to check the HTML response, since that data
  legitimately still lives there.

**Summary**: Extracted ~750 lines of inline JS from
`templates/post.html` into `static/js/post-map.js`, verbatim in
behavior — no logic changes, purely a move. The only edits inside the
moved code were the four data-injection lines at the top, which now read
from `window.BULLIEXPLORER_MAP_DATA` (set by the small inline block that
remains in `post.html`) instead of Jinja `{{ ... | tojson }}`
placeholders directly. `templates/post.html` dropped from 819 to 87
lines. The new file is loaded via a plain `<script src="/static/js/
post-map.js"></script>` tag positioned after the vendor scripts
(`maplibre-gl.js`, `pmtiles.js`, `basemaps.js`) and after the small data
block, same load order as before. `StaticFiles`'s existing `no-cache`
`Cache-Control` header (set by `app/main.py`'s `_static_cache_headers`
middleware for everything under `/static/`) already applies to this new
file with no further change needed — a conditional GET on every request,
but a 304 (not a full re-download) for an unchanged file, which this file
now structurally can be across pages/posts since it carries no
per-request data.

Both pure-function concerns named in the original finding — testability
and cacheability — are addressed structurally by the move itself; no new
unit tests were added for the newly-extractable pure functions
(`escapeHtml`, `buildAmenityPopupHtml`, phone parsing) in this commit,
since this fix's scope was the extraction, not a follow-on JS test
suite/runner (this project has no JS test runner — adding one is a
bigger decision than this fix, and out of scope here).

**Testing**: `djlint templates/ --check` stays clean. `node -c
static/js/post-map.js` confirms the extracted file is syntactically
valid plain JS with zero parse errors (no Jinja substitution needed
first, unlike every prior phase's inline-script verification in this
project's other `fix_*.md` docs — a direct, permanent improvement in
how verifiable this code is, not just a one-time check). Two unit tests
that asserted on now-moved JS content (`test_post_with_route_and_tiles_
includes_cycling_layers`, `test_post_with_route_and_tiles_cycling_layers_
use_kind_detail`) were rewritten to read `static/js/post-map.js`
directly instead of the post-detail HTML response (renamed
`test_post_map_js_includes_cycling_layers`/`test_post_map_js_cycling_
layers_use_kind_detail`); the geojson-inlining tests were updated to
assert on the new `BULLIEXPLORER_MAP_DATA`/`routeGeojson`/`poisGeojson`
keys instead of the old `ROUTE_GEOJSON`/`POIS_GEOJSON` const names, and
a new assertion confirms `/static/js/post-map.js` is referenced.
Same "not meaningfully unit-testable" reasoning as every other
MapLibre-rendering phase in this project's docs applies to actual
browser/runtime behavior — this fix doesn't change that, it only
changes where the code lives and how testable its non-map-runtime parts
(syntax, presence of expected functions/filters) are.

`make ci`: 308 passed, 95.93% coverage, security checks clean.

**Files touched**: `templates/post.html`, `static/js/post-map.js`
(new), `tests/unit/test_templates.py`.

### F5 — Postgres advisory lock around the startup content sync

**Done when**
- [x] `app/core/db.py` gains two small, framework-free helpers —
  `try_acquire_advisory_lock(session, key)` (wraps
  `pg_try_advisory_lock`, non-blocking, returns a `bool`) and
  `release_advisory_lock(session, key)` (wraps `pg_advisory_unlock`) —
  reusable Postgres primitives, not specific to the startup-sync use
  case.
- [x] `app/main.py`'s lifespan wraps the existing `sync_posts` call: the
  worker that wins `try_acquire_advisory_lock` runs the real sync and
  releases the lock in a `finally` after commit; a worker that doesn't
  win logs and skips straight through with an empty `SyncResult()` — no
  amenity-discovery task gets (redundantly) scheduled by the losing
  worker either, since `SyncResult()`'s default `amenity_route_ids` is
  empty.
- [x] The lock key is a single fixed module-level constant
  (`_STARTUP_SYNC_LOCK_KEY`) — one lock, scoped to "has *a* worker
  already run startup sync", not per-route/per-post (there's exactly one
  thing being deduplicated across workers: the whole startup sync call).
- [x] `make ci` green, plus new integration tests (real Postgres
  required — advisory locks are a genuine server-side primitive, not
  mockable meaningfully) proving: (a) the low-level helpers' actual lock/
  blocked/release/reacquire semantics, (b) a lifespan skips `sync_posts`
  entirely when the lock is already held by another connection, and (c)
  a lifespan that wins the lock releases it afterward — not leaked, so a
  subsequent acquire attempt succeeds.

**Summary**: `app/core/db.py` gained `try_acquire_advisory_lock`/
`release_advisory_lock`, thin wrappers around `pg_try_advisory_lock`/
`pg_advisory_unlock` executed via the existing `AsyncSession`. Both are
session-scoped (not transaction-scoped, per Postgres's own two lock
flavors) — deliberate, since the lock needs to be held across the whole
sync-and-commit sequence, then explicitly released, rather than
auto-released at a `COMMIT` that happens partway through. `app/main.py`'s
lifespan now acquires `_STARTUP_SYNC_LOCK_KEY` on the same session used
for `sync_posts`, before calling it: on success, runs the sync, commits,
then releases the lock in a `finally` (so a failed sync still releases,
rather than leaking the lock on the next deploy); on failure to acquire,
logs `"Startup sync lock held by another worker — skipping"` and
continues with an empty `SyncResult()` — the rest of the lifespan
(amenity-discovery scheduling, the `yield`, shutdown) proceeds
identically either way, just with nothing new to schedule on the losing
worker.

This directly closes both consequences named in the finding: with two
`uvicorn --workers 2` processes racing on startup, only one now performs
the actual parse/upsert work (no more double parsing/double upserts
racing the same rows), and the amenity-sync cooldown check downstream
only ever sees `amenities_synced_at` written once per deploy, closing the
small race window where both workers could read a stale value before
either committed.

**Explicitly not changed**: the module-level `_last_overpass_time` rate
limiter in `geo_sync.py` (named in the review's anti-patterns section as
related but distinct) — F5 makes the *startup* sync single-worker, which
is the scope this fix targeted, but amenity discovery scheduled from
that sync still runs as its own background task and could still
theoretically run in more than one worker's process space if
`enable_amenity_discovery` triggers it from more than one place in the
future. Per-process rate limiting remains a known, now-more-clearly-
scoped limitation, not silently fixed by this change — worth documenting
explicitly rather than leaving it implied.

**Testing**: `tests/integration/test_startup_sync_lock_integration.py`
(new, requires the PostGIS container) — three tests: the raw lock
helpers' acquire/blocked/release/reacquire cycle against two real
connections; a lifespan skipping `sync_posts` (patched, asserted
`not_called()`) when another connection already holds the lock; a
lifespan that completes a (patched) sync and is confirmed to have
released the lock afterward by successfully reacquiring it in a fresh
session. No unit-level (mocked-DB) test was added for the lock helpers
themselves — `pg_try_advisory_lock`/`pg_advisory_unlock` are genuine
Postgres server-side primitives with no meaningful mock; the integration
tests are the real coverage here, consistent with AGENTS.md's testing
split (`tests/unit/` — no DB; `tests/integration/` — needs Postgres).

`make ci`: 308 passed (was 305), 95.93% coverage, security checks clean.

**Files touched**: `app/core/db.py`, `app/main.py`,
`tests/integration/test_startup_sync_lock_integration.py` (new).

### Housekeeping batch — backup cron + docs index

**Done when**
- [x] A backup script exists that dumps the production `db` container,
  gzips it, and uploads it to R2 with 14-day retention — reusing the
  `s3_*` settings/`boto3` dependency already in place for media storage
  rather than introducing new config or a new dependency.
- [x] Scheduled via a host crontab entry, documented in
  `docs/dev/deployment.md` — explicitly **not** a new docker-compose
  service, per the review's "small, no new services" framing for this
  item.
- [x] The script's own logic (retention selection, dump invocation,
  upload, credential-missing guard) is unit-tested with `boto3`/
  `subprocess` mocked — the part verifiable without production/R2
  access.
- [x] A `docs/dev/README.md` index exists, grouping the (at the time of
  this review) 22+ files under `docs/dev/` into active reference /
  historical (implemented, kept as the record of why) / documented
  false leads / config, so a future reader doesn't need to open every
  file to find the one they need.
- [x] `make ci` green with the new script + tests included in the
  linted/type-checked surface (`scripts/` added to `Makefile`'s `SRC`
  and `pyproject.toml`'s `[tool.pyright]` `include`).
- [ ] **Explicitly not achievable from this sandbox**: a real backup
  file actually landing in R2 on the production host, and one real
  restore test against a throwaway local Postgres — both require
  production SSH access and live R2 credentials that don't exist in
  this environment. Tracked as an open item in `docs/dev/
  monitoring_ops.md` Phase 4 and `docs/dev/buckets.md` bucket #7, not
  silently checked off.

**Summary**: Two independent, low-urgency items from the review's
housekeeping batch, done together as planned:

1. **Backup cron** — `scripts/backup_db.py` dumps the `db` service via
   `docker compose exec -T db pg_dump`, gzips the output in memory,
   uploads to R2 as `backups/backup-YYYY-MM-DD.sql.gz` via `boto3`
   (reusing `s3_endpoint_url`/`s3_access_key`/`s3_secret_key`/
   `s3_bucket` — declared in `app/core/config.py` for media storage back
   in `media_storage_r2.md`, but never actually called from anywhere in
   the codebase until now, since media uploads ended up going
   browser-to-R2 directly via Sveltia instead), then prunes any backups
   beyond the newest 14 (plain lexicographic sort on the date-formatted
   key — correct without parsing dates back out, since the key format
   sorts in date order by construction). Aborts loudly
   (`sys.exit(1)`) rather than silently no-op-ing when R2 credentials
   aren't configured, so a misconfigured cron entry fails visibly
   instead of looking identical to a successful no-op. Exposed as
   `make backup`; a host crontab entry (03:00 nightly) documented in
   `docs/dev/deployment.md` §6, deliberately not a new docker-compose
   service. Full phase write-up (scope/done-when/left-over) lives in
   `docs/dev/monitoring_ops.md` Phase 4, which this also un-gates from
   its original "before SQLAdmin ships" trigger — that trigger no
   longer applies (`buckets.md` bucket #6: SQLAdmin is superseded, not
   shipping), and this review's own tech-debt finding re-triggers the
   work independent of it.
2. **Docs index** — `docs/dev/README.md` groups every existing file into
   active reference, historical-but-still-the-record-of-why, documented
   false leads, and non-prose config, with a one-line note on what each
   is for. Framed explicitly as something that goes stale exactly as
   fast as any other doc if new files aren't added to it in the same
   change — not a one-time artifact.

**Testing**: `tests/unit/test_backup_db.py` — 10 tests. `select_keys_to_
delete()` (the retention logic) is tested as a pure function with no
mocking at all, at each boundary (under/exactly-at/over the 14-backup
limit). `dump_database()`, `prune_old_backups()`, and `run_backup()` are
tested with `subprocess.run`/`boto3.client` mocked (AGENTS.md: tests
must pass with no real R2 credentials, must mock boto3/S3 calls) —
covering a failed `pg_dump` propagating rather than being swallowed, the
credential-missing abort path, and the full upload-then-prune
orchestration calling both with the right arguments. The docs index has
no automated test (it's prose, matching every other `docs/dev/*.md` file
in this project) — correctness here means every existing file appearing
in exactly one section, checked manually against `ls docs/dev/`.

`make ci`: 318 passed (was 308), 95.93% coverage, security checks clean.

**Files touched**: `scripts/backup_db.py` (new),
`tests/unit/test_backup_db.py` (new), `docs/dev/README.md` (new),
`Makefile`, `pyproject.toml`, `docs/dev/deployment.md`,
`docs/dev/monitoring_ops.md`, `docs/dev/buckets.md`.