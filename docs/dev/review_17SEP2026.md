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
| No DB backups | bucket #7 | Still defensible (everything re-derivable from git + OSM) but the calculus shifted: `nearby_amenities` is now 15k+ rows that are *expensive* to re-derive against a flaky public API. Worth a periodic `pg_dump` to R2 — small, no new services. |
| `docs/dev/` sprawl | 22 files | Six `fix_*.md` docs, one documented false lead, one ambiguously-named `issues_phase4.md`. A short `docs/dev/README.md` index (active / historical / superseded) would keep the culture's value without the navigation cost. |

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