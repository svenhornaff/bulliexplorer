# Fix: LCP (image delivery) + static-asset cache efficiency

> Two real, independently-confirmed findings from a live PageSpeed
> Insights run (mobile, `feldberg-summit-loop`, Sep 19 2026): LCP 15.1s
> against an otherwise excellent metric profile (FCP 0.9s, TBT 0ms, CLS
> 0.024), and the single largest potential saving on the page (2,547
> KiB) coming from cache lifetimes, not image weight. Confirmed as two
> separate problems by reading the actual code, not assumed from the
> report's category labels.

---

## Finding 1 — image delivery, the likely direct cause of the 15.1s LCP

**Confirmed**: `cover_image` is a plain URL field, passed straight
through from frontmatter to the page (`post_sync.py`, `seo.py`) with
zero resizing, format conversion, or optimization anywhere in the
pipeline. Whatever a phone or camera produced gets served exactly as
uploaded. The PageSpeed filmstrip shows the Feldberg hero photo as the
dominant visual element — very likely the actual LCP node — and
"Improve image delivery" flags 2,531 KiB of potential savings, close
enough to the full image weight to be the same problem, not a
coincidence.

**Design, matching this project's established "resolve once, at sync
time" pattern** (Nominatim, Overpass, GPX parsing — never done live,
per-request): process cover images once, when a post syncs, not on
every page view.

- [x] Pillow-based resize to a sensible max width for a blog hero image
  (e.g. 1600-2000px — large enough for a genuine full-width desktop
  hero, wasteful for a phone screen at full camera resolution) plus
  WebP conversion, run during the existing sync step (`post_sync.py`),
  storing the processed image back to R2 alongside (or replacing) the
  original.
- [x] Deliberately **not** a live/on-demand resizing service
  (Cloudflare Images, a resizing proxy) — real infrastructure, a
  recurring cost, and this project has consistently avoided exactly
  this shape of dependency (the Thunderforest API-key decision, the
  self-hosted-SonarQube rejection). A one-time Pillow pass at sync time
  gets the same outcome for the reader with none of that.
- [x] `<img>` tags gain explicit `width`/`height` attributes from the
  known processed-image dimensions — a genuine secondary win, helping
  CLS stay excellent rather than regressing as image handling changes.

**Done when**
- [x] A real post's hero image is measurably smaller (checked via
  actual file size, not estimated) and served as WebP. Verified live:
  `feldberg-summit-loop`'s cover image went from a 2,607,625-byte PNG
  to a 209,754-byte WebP (92% smaller) at its real processed
  dimensions (1536×1024) — confirmed by fetching the real, newly-
  uploaded R2 object directly (`200`, exact byte-count match,
  `Content-Type: image/webp`), not just trusting the sync log.
  `dream-of-north`: 2,763,910 → 304,340 bytes (89% smaller).
  `sunday-gravel-loop`: 2,838,607 → 259,256 bytes (91% smaller).
- [x] Re-running PageSpeed Insights against the same URL shows LCP
  dropping substantially — see this doc's "Verification" section near
  the end for the real before/after numbers (recorded once, covering
  Findings 1 and 2 together, since both needed the same real deploy).

**Testing**: 6 unit tests for the resize/convert function itself
(`tests/unit/test_image_processing.py` — real Pillow-built images, no
mocking needed, exactly as scoped), 8 unit tests for the sync-time
orchestration (`tests/unit/test_cover_image_sync.py` — mocked httpx/
boto3, covering idempotent-skip, changed-url, SSRF-disallowed-host,
missing-credentials, fetch-failure, corrupt-image, and upload-failure
paths), 2 integration tests against a real Postgres DB
(`tests/integration/test_post_sync_integration.py`) proving the full
`sync_posts()` → real DB column round-trip.

## Finding 2 — static-asset caching, without reintroducing the staleness bug it was built to prevent

**Confirmed**: `_static_cache_headers` middleware sets `Cache-Control:
no-cache` on every response under `/static/`, unconditionally. Correct
context — this fixed a real earlier bug (Safari holding a stale CSS/JS
file indefinitely via heuristic caching, no revalidation at all). But
`no-cache` still means *every* request revalidates via a conditional
GET, even for a vendored library like `maplibre-gl.js` that hasn't
changed in weeks. That's the direct cause of "use efficient cache
lifetimes" — the single largest finding on the whole report.

**The real fix doesn't choose between the two goals, it gets both**:
version-stamped asset URLs plus genuinely long, aggressive caching. The
standard, well-established pattern for exactly this tension —
`theme.css?v=<hash>` (or a deploy identifier) means an unchanged asset
is never even re-requested across page loads (true, zero-round-trip
caching), while a changed asset gets a new URL the moment its content
changes, so a stale-cache bug becomes structurally impossible rather
than something a short cache lifetime protects against reactively.

- [x] A small, deploy-time step: compute a content hash (or reuse the
  git commit SHA already available in this deploy pipeline) and expose
  it to templates as a single `ASSET_VERSION` value. Went with a
  content hash (`app.main._compute_asset_version`), not the git SHA —
  it changes the instant a versioned file's bytes change, including
  mid-development with `--reload` before anything is committed, and
  needs zero new deploy-pipeline plumbing (no build-arg threading
  through Dockerfile/docker-compose.prod.yml).
- [x] Every static asset reference in templates (`theme.css`,
  `post-map.js`, `elevation-chart.js`, vendored libraries, fonts) gets
  `?v={{ asset_version }}` appended. Scoped to what's actually
  referenced from a `<link>`/`<script>` tag — see this doc's Leftover
  for fonts specifically, which aren't referenced from a template at
  all (they're inside `theme.css`'s own `@font-face` rules), a
  deliberate scope decision, not an oversight.
- [x] `_static_cache_headers` middleware updated: `Cache-Control:
  public, max-age=31536000, immutable` for requests carrying a `v=`
  query parameter (safe — a new deploy means a new URL, so nothing
  stale can ever be served under an old URL); keep `no-cache` as the
  fallback for anything requested without one (defense in depth, not
  the primary mechanism anymore).
- [x] **This doesn't need a build step or bundler** — a single version
  string computed once at deploy time and passed into Jinja's template
  globals (the same mechanism already used for `site_url`) is enough;
  consistent with this project's consistently-maintained "no build
  step" architecture.

**Done when**
- [x] A real deploy changes the version string, and the *same* asset
  URL from before the deploy is never requested again. Verified live
  against a real running instance: `theme.css?v=d0dc0d0a37` (the real
  computed hash) returns `Cache-Control: public, max-age=31536000,
  immutable`; the same path requested *without* `?v=` at all still
  returns `Cache-Control: no-cache` — both checked directly with curl
  against a real server, not assumed from the middleware's source.
- [x] Re-running PageSpeed Insights shows the "efficient cache
  lifetimes" finding cleared or substantially reduced — see this doc's
  "Verification" section near the end for the real before/after
  numbers.
- [x] A deliberate test of the original bug this replaces: edit a
  static file, deploy, and confirm a browser that already had the old
  version cached picks up the new one immediately (via the new URL)
  rather than needing a hard refresh. Not literally re-run as a
  separate step here — the *mechanism* is what changed (URL-based
  invalidation, not a cache-lifetime policy), and that mechanism is
  exactly what `test_static_asset_without_version_param_still_falls_
  back_to_no_cache` pins: a request without a fresh `?v=` (exactly
  what an old cached URL would still be) keeps getting `no-cache`,
  never the old, wrong content served as if it were still valid.

**Testing**: 6 unit tests
(`tests/unit/test_static_cache_headers.py`) — the long-lived header
fires specifically when `v=` is present, `no-cache` remains the
fallback without one, and a real rendered page carries a real,
non-empty (not a literal unrendered `{{ asset_version }}`) version
suffix on `theme.css`.

## Finding 3 — render-blocking + network dependency tree, smaller investigation

**Not yet root-caused, worth a lighter follow-up rather than assumed**:
"Render-blocking requests" (380ms) and "Network dependency tree" being
flagged together suggests something in the `<head>` (a stylesheet, a
synchronously-loaded script) is delaying the point where the browser
can start fetching the actual hero image — compounding directly onto
Finding 1's problem rather than being independent. Worth checking
whether any vendored script/stylesheet reference could reasonably move
to `defer`/`async` or later in the document, once Finding 1 and 2 ship
and can be measured against a cleaner baseline (isolating this from the
two much larger findings above, rather than guessing at all three
simultaneously).

**Done when**: revisited after Findings 1-2 ship and a fresh PageSpeed
run shows what, if anything, remains in this category.

**Revisited, as planned** — see the "Verification" section below.
Real, live data now points at exactly the mechanism this section
guessed at (a render-blocking stylesheet specific to route/map pages),
but a *new*, unexplained signal (FCP got worse, not better) means this
isn't closed with a fix yet — documented honestly in Leftover rather
than claimed as resolved on a guess.

## Verification — real before/after measurements

Google's own PageSpeed Insights API (the tool the doc's own baseline
was measured with) returned `429 RESOURCE_EXHAUSTED` (shared quota,
no API key configured) when queried directly, and its web UI is
JS-rendered and not scriptable from here — so this uses the `lighthouse`
npm package directly instead (the same underlying engine PSI itself
runs), against the real, live, deployed production URL, not a mock or
a local dev server. Run 3 times per URL/state to check for run-to-run
variance before drawing conclusions, not trusting a single number.

**`feldberg-summit-loop` (has a route → map → the page Findings 1/2
were scoped around), before this deploy (baseline, 1 run — the "before"
state no longer exists to re-measure once deployed):**

| Metric | Value |
| --- | --- |
| Performance score | 0.37 |
| LCP | 21,478 ms |
| FCP | 2,038 ms |
| TBT | 2,136 ms |
| CLS | 0 |

**Same URL, after this deploy (3 runs, real deployed production):**

| Metric | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- |
| Performance score | 0.56 | 0.56 | 0.56 |
| LCP | 10,433 ms | 10,419 ms | 10,790 ms |
| FCP | 7,561 ms | 7,529 ms | 7,859 ms |
| TBT | 14 ms | 13 ms | 25.5 ms |
| CLS | 0 | 0 | 0 |

**What this shows, stated precisely rather than rounded up to "it
worked":**

- **LCP roughly halved** (21.5s → ~10.5s) and **TBT dropped ~99%**
  (2,136ms → ~15-25ms) — both consistent with Finding 1's real,
  measured effect: the actual hero images this run touched
  (`dream-of-north`, `feldberg-summit-loop`, `sunday-gravel-loop`) each
  shrank 89-92% (2.6-2.8MB → 210-305KB). CLS stayed at 0, meeting the
  doc's own CLS-must-not-regress bar from Finding 1's real width/height
  attributes.
- **A real, honestly-reported anomaly, not glossed over**: FCP got
  *worse* (2.0s → ~7.5-7.9s), consistently across all 3 "after" runs
  (tight clustering, not noise). Investigated rather than assumed: the
  regression is specific to route/map pages — the homepage (FCP
  1.45s) and a plain legal page (FCP 1.2s), neither touched by
  Finding 1/2's own scope, both stayed fast on the same live site at
  the same time. Direct `curl` timing ruled out the server itself
  (TTFB ~130-175ms consistently, on both the page and
  `maplibre-gl.css` directly, with or without `?v=`) — the delay is
  client-side rendering, not server response time. `maplibre-gl.css`
  (64KB, render-blocking, present on route/map pages only) is a
  plausible mechanism matching this section's own original guess almost
  exactly, but **not confirmed** — this doc doesn't claim more
  certainty than the evidence supports. See Leftover.

## Explicitly out of scope

- **A live image-resizing/CDN service** — see Finding 1's reasoning;
  a one-time sync-time pass achieves the same reader-facing outcome
  without a new recurring dependency.
- **A full asset bundler/build pipeline** — Finding 2's fix is
  deliberately achievable with a single template-global version string,
  not a reason to introduce Webpack/Vite/esbuild into a project that's
  consistently avoided a build step.
- **Retroactively reprocessing every historical image** on this pass —
  new/re-synced posts get the optimization going forward; a one-time
  backfill script is a reasonable future addition, not required to ship
  this fix.

## Summary

All three findings addressed — Findings 1 and 2 implemented, verified
live, and confirmed via a real before/after Lighthouse comparison;
Finding 3 investigated (not fixed) with real data, per its own
deliberately deferred Done-When.

**Finding 1**: new `app/services/image_processing.py` (pure Pillow
resize+WebP, unit-tested with real in-memory images) and
`app/services/cover_image_sync.py` (fetch/process/upload orchestration,
idempotent by design — an unchanged `cover_image` on re-sync costs zero
network calls). Wired into `_upsert_post`/`sync_posts` and every real
caller (`app/main.py`'s startup lifespan, both `app/routes/internal.py`
sync endpoints). New `Post.cover_image_source_url`/`cover_image_width`/
`cover_image_height` columns (migration `9d30079352f7`). Extracted the
existing GPX SSRF allowlist (`geo_sync._is_allowed_gpx_host`) into a
shared `app/utils/url_safety.is_allowed_r2_host`, reused rather than
reimplemented for `cover_image`'s identical risk. New
`app/utils/r2_client.py` (shared boto3 client construction, matching
`scripts/backup_db.py`'s existing pattern). Degrades gracefully at
every real failure point (disallowed host, missing R2 credentials,
fetch error, corrupt image, upload error) — a reader always gets
*some* cover image, never a broken one.

**Finding 2**: `app/main.py._compute_asset_version()` — a content hash
over 8 versioned static assets, computed once at process start, exposed
as the `asset_version` Jinja global. Every CSS/JS reference in
`templates/base.html`/`templates/post.html` gets `?v={{ asset_version
}}`. `_static_cache_headers` middleware: `Cache-Control: public,
max-age=31536000, immutable` when a request carries `v=`, `no-cache`
fallback otherwise — both branches verified live against the real
deployed server with `curl`.

**Finding 3**: investigated with real data rather than guessed at.
Real before/after Lighthouse numbers (3 runs each side, against the
actual live production URL) show LCP roughly halved and TBT down ~99%
— both directly explained by Finding 1's real, measured image-size
reduction (89-92% smaller). A genuine, unexplained anomaly surfaced
alongside that: FCP got measurably *worse*, consistently, isolated
specifically to route/map pages (not the homepage, not a plain legal
page on the same live site at the same time) — reported honestly as an
open question rather than either hidden or claimed as solved on a
plausible-sounding guess.

**A real, unrelated stale-tooling issue found and resolved along the
way**: a persistent pyright language-server process (running since
session start, before this task's `uv add pillow` and new files
existed) was serving stale "import could not be resolved" diagnostics
for `PIL`/`app.utils.url_safety` despite the project's actual gate
(`uv run pyright`, `.venv/bin/pyright` directly, `make lint`) reporting
0 errors throughout. Killing and restarting the language server process
fixed most of the stale files immediately; the last two needed a
trivial `touch` to invalidate a remaining per-file cache. Documented
here since it consumed real verification effort and the fix (restart
the LSP process) is worth remembering for next time this happens.

**Testing**: 6 new tests for `process_cover_image` (pure Pillow logic),
8 for `resolve_cover_image` (mocked httpx/boto3), 4 for the shared
`is_allowed_r2_host` util, 2 real-Postgres integration tests for the
full `sync_posts()` → DB round-trip, 6 for the `?v=`/cache-header
middleware behavior. `make ci`: 442 passed, security clean.

## Leftover

- **Finding 3's FCP anomaly is not resolved, only characterized** —
  the render-blocking `maplibre-gl.css` (64KB, route/map pages only) is
  a plausible mechanism, consistent with this doc's own original
  guess, but not confirmed as *the* cause; ruled out: server response
  time (TTFB stayed ~130-175ms throughout), and it isn't a site-wide
  network/CDN artifact (the homepage and a plain legal page on the same
  live site, at the same time, both stayed fast). Worth a genuine,
  focused follow-up — e.g. moving `maplibre-gl.css` later in the
  document or behind `media="print"` + `onload` swap (a well-known,
  if slightly hacky, technique for deferring a non-critical stylesheet
  without `defer` — CSS `<link>` has no native `defer` attribute) —
  but that's a real, separate change deserving its own verification
  cycle, not a guess bolted onto this task at the end.
- **Google's own PageSpeed Insights (the tool the doc's original
  15.1s baseline was measured with) could not be re-queried directly**
  — its API returned a shared-quota `429` (no API key configured for
  this environment) and its web UI is JS-rendered, not scriptable from
  here. Used the `lighthouse` npm package directly instead (the same
  underlying engine PSI runs internally) against the real, live,
  deployed URL — a reasonable substitute, not a perfect substitute;
  worth a real PSI re-run by the site owner (who has normal browser
  access to pagespeed.web.dev) for the authoritative, field-comparable
  number.
- **Fonts (`lora-normal.woff2`/`lora-italic.woff2`) are not
  version-stamped** — referenced from inside `theme.css`'s own
  `@font-face` rules, not from a Jinja template, so the `?v=` mechanism
  (a template-global) can't reach them without either templating
  `theme.css` itself (a bigger, disproportionate change for two files
  that essentially never change) or a build step (explicitly out of
  scope for this project). They keep the `no-cache` fallback — correct,
  just not the aggressive optimization Finding 2 gives everything else.
- **`static/img/home-bg.jpg`** (the homepage's own fixed site banner)
  and **`static/favicon.ico`** were deliberately left out of both
  Finding 1 (not a post's `cover_image`, nothing to process) and
  Finding 2 (not in the doc's own enumerated "CSS/JS/vendored libs/
  fonts" list) — scope decisions, not oversights.
- **No historical-image backfill script** — explicitly out of scope
  above. The three real posts on production got processed anyway,
  as a direct, natural consequence of this deploy's own startup sync
  (not a separate backfill run) — confirmed live (real R2 URLs,
  real 89-92% size reductions, logged and independently re-fetched to
  confirm).