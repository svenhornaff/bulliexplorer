# BulliExplorer — Media Storage on R2

> Closes bucket #5 from `buckets.md`. Moves GPX/image uploads off git onto
> Cloudflare R2, using Sveltia's native R2 media library — direct
> browser-to-R2 uploads, no backend proxy. See `editor_cms.md` for the CMS
> this extends and `cloudflare_r2_setup.md` for the R2 account/bucket
> already provisioned (currently used for PMTiles basemap tiles).

**Priority note:** unlike most items in `buckets.md`, this one is
deliberately **not** sequenced behind content growth. The cost driver —
git repo size, forever, via history — only gets worse the longer it's
left, unlike the UI/UX refresh where deferring genuinely cost nothing.
Same reasoning that justified retiring Bootstrap "now, not later," applied
here: cheapest to fix while only a handful of files are affected.

---

## Why this is a real problem, not just untidy

Every image and GPX file uploaded through Sveltia today gets committed to
git as a binary blob (confirmed: `kinzig_valley_oop.jpeg`,
`nc4200_cover.png`, `SCR-20260825-mtsh.jpeg`, two `.gpx` files, and
gallery images all sit in `static/uploads/` as tracked files). Git has no
meaningful compression for JPEGs/PNGs, and — critically — **a deleted
binary never actually leaves the repo**; it stays in history forever.
Every future `git clone` downloads every photo ever uploaded, not just
the current ones. Fine at 6 files. Not fine at 600.

This was a known, documented trade-off from the start — `post_and_backend.md`
and `editor_cms.md` both flagged R2 as "explicitly deferred" specifically
so the webhook publish pipeline could ship without also standing up R2
media auth at the same time. That sequencing call was correct; revisiting
it now, before the file count grows further, is the other half of it.

---

## How it actually works — Sveltia's native R2 integration

Checked against Sveltia's official R2 integration docs
(`sveltiacms.app/en/docs/media/cloudflare-r2`) rather than assumed:

- Sveltia supports Cloudflare R2 as a **media library backend**, separate
  from the git backend used for post content. File and Image widgets
  (`cover_image`, `route.gpx_file`, gallery entries) route through it
  automatically — **no change to the field widgets themselves**, only to
  where their uploads land.
- Uploads go **directly browser → R2** using AWS Signature V4 — no
  backend proxy, no new endpoint in `app/routes/` to build or secure.
- The R2 **Secret Access Key is never stored in `config.yml`** — Sveltia
  prompts for it in the browser UI on first use, same security model
  already in place for the GitHub PAT. Nothing new lands in the repo.
- A `public_url` is required for asset previews (R2's S3 API endpoint
  itself requires auth; the public URL is what serves the preview/final
  image). This project already has one — the same `pub-<hash>.r2.dev`
  URL set up for PMTiles — reusable here with a different path prefix.

**Config addition to `static/editor/config.yml`:**

```yaml
media_libraries:
  cloudflare_r2:
    access_key_id: <access-key-id>              # NOT the secret — that's entered in-browser
    bucket: bulliexplorer
    account_id: <cloudflare-account-id>          # same account as the tiles bucket
    public_url: https://pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev
    prefix: media/                                # NOT "path" — keeps uploads separate from tiles/
```

✅ **Verified against the official docs** (`sveltiacms.app/en/docs/media/cloudflare-r2`)
and, since those docs are flagged as still-in-development, against the
Sveltia CMS source itself (`services/integrations/media-libraries/cloud/`),
after the first draft's schema turned out wrong, exactly as its own
warning predicted it might. Corrections: no `default:`/`name:`/`config:`
nesting — it's flat. The key is **not** an arbitrary library name: it
must be exactly `cloudflare_r2`, one of the fixed provider names in
Sveltia's `allCloudStorageServices` map. The path field is `prefix`,
not `path`. No `region` field — the integration hardcodes `auto` (with
an optional `jurisdiction` for EU/FedRAMP endpoints, not needed here).

Verified behavior that shaped the phases below: configuring the library
at site level auto-enables it for **every** File/Image widget (no
per-field changes needed — confirmed by the integration's
`isEnabled(fieldConfig) ?? siteConfig` fallback), and R2 assets are
**hotlinked**: what lands in frontmatter is the full URL
`{public_url}/{prefix}filename`, which is exactly the URL shape
Phase 2's `geo_sync.py` fix anticipates. While `media_folder` still
exists, the editor shows a provider picker (internal git storage vs
R2) on every upload — removal of `media_folder` belongs in Phase 2,
after frontmatter migration.

**What this does *not* touch:** `app/core/config.py`'s `S3_*` settings.
Those remain server-side credentials for a *different* future purpose —
the `monitoring_ops.md` Phase 4 backup cron (`pg_dump` → R2) — not for
Sveltia's browser-to-R2 uploads, which never go through the FastAPI app
at all. Worth keeping straight so a future change to one doesn't get
confused for touching the other.

---

## Phased implementation plan

### Phase 1 — R2 media library wired into Sveltia

**⚠️ Redesigned mid-implementation — read this before the checklist below.**
The first working version of this phase put the `media_libraries` block
(including a real `account_id` and a placeholder for `access_key_id`)
directly into `static/editor/config.yml`, commented out until the token
existed. That was flagged, correctly, as the wrong shape regardless of
whether Sveltia treats the Access Key ID as sensitive: **anything written
into a git-tracked file is permanently visible in that file's history**,
forever, in every clone — a static file being "served to the public
anyway" doesn't change that a *committed* credential-shaped value can
never actually be un-committed. Commenting it out doesn't help; the value
still exists in the commit that added it.

**The actual fix: `config.yml` is no longer a static file for this
purpose.** `GET /editor/config.yml` is now a dynamic FastAPI route
(`app/routes/internal.py`) that reads the static template from disk and
injects the `media_libraries` block only if `R2_ACCESS_KEY_ID`/
`R2_ACCOUNT_ID`/`R2_PUBLIC_URL` are set in **Settings — sourced from
`.env` on the server, never from a git-tracked file.** Unset, the
response is byte-identical to the template and Sveltia falls back to
git-based uploads, same as before this phase existed.
`static/editor/index.html` points Sveltia at this route explicitly
(`<link rel="cms-config-url" href="/editor/config.yml">`) instead of
relying on its same-directory default, so there's no ambiguity about
which config actually loads.

**Scope**

- [x] Create a **dedicated** Account API token (Object Read & Write, scoped
  to the `bulliexplorer` bucket) for Sveltia's media use — separate from
  the token used for the manual PMTiles upload, so each credential's
  blast radius and rotation stay independent (same least-privilege
  pattern used everywhere else in this project). Confirmed distinct from
  `S3_ACCESS_KEY` (the PMTiles/backup-cron token) in the live `.env`.
- [x] **`static/editor/config.yml` stays permanently credential-free.**
  No `media_libraries` block, no account ID, no placeholder — just a
  comment explaining where the real mechanism lives. Guarded by
  `tests/unit/test_editor.py::test_editor_config_route_r2_unset`, which
  asserts the *parsed* response has no `media_libraries` key when R2 is
  unconfigured (checked structurally, not by substring match — the
  template's own explanatory comment mentions "media_libraries" by name,
  which an earlier draft of this test wrongly flagged as a false
  positive).
- [x] **New dynamic route**: `GET /editor/config.yml` in
  `app/routes/internal.py`, injecting the block from `Settings` at
  request time. Guarded by
  `tests/unit/test_editor.py::test_editor_config_route_r2_set`, which
  confirms the injected block has the correct flat `cloudflare_r2`
  schema (verified against the Sveltia CMS source, not just the
  still-in-development official docs) when the three env vars are set.
- [x] **New `Settings` fields**: `r2_access_key_id`, `r2_account_id`,
  `r2_public_url` — all default to `""`, deliberately *not* following
  the "no default for secrets" rule from `AGENTS.md`. Same reasoning as
  `sentry_dsn`: a missing media-library config must degrade gracefully
  (git uploads keep working), not crash the app.
- [x] `.env.example` and `docker-compose.prod.yml` updated with the
  three new vars — passed through explicitly in the compose file's
  `environment:` block, same pattern already established for
  `TILES_URL`, gotten right on the first attempt this time rather than
  repeating that earlier gap.
- [x] **Found and fixed in the same pass, unrelated to R2 but the same
  root concern**: `.env.example` had a real, working Sentry DSN
  hardcoded instead of a placeholder — every other line in that file is
  a template value, this one had slipped through. Cleared it. Low
  severity (worst case is spam events in the Sentry project, not a
  breach) but the same class of mistake this phase exists to prevent.
- [x] **Update `docs/dev/r2-cors.json`** — reshaped into **two rules**
  rather than replacing the single existing one. The PMTiles rule is
  preserved verbatim (public GET/HEAD, `Range`/`Accept-Encoding`,
  `Content-Range`/`Content-Length` exposure — MapLibre range reads
  depend on it), with a new upload rule added on top:

  ```json
  {
    "AllowedOrigins": ["https://bulliexplorer.com", "http://localhost:8000"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000
  }
  ```

  The first draft of this phase replaced the whole policy with just the
  Sveltia-prescribed rule — which would have silently broken the live
  map (same bucket!) by dropping `Content-Range`/`Content-Length`
  exposure and blocking local dev. Two-rule shape chosen to keep uploads
  least-privilege (editor origins only) without regressing tiles.
  Guarded by `tests/unit/test_r2_cors.py`, so a future edit to the media
  rule can't quietly break the tiles rule. `localhost:8000` is included
  so the editor's upload flow is testable in local dev.
- [x] A CSP `connect-src`/`img-src` allowance is mentioned in Sveltia's
  docs as a requirement — **moot here**, confirmed no CSP middleware
  exists anywhere in this app currently (`grep` came back empty). Worth
  a note for whenever CSP middleware does get built (it's in the
  original day-1 security baseline, still not implemented) — that's the
  moment this becomes a real requirement, not now.
- [x] Re-apply the updated CORS policy to the bucket (dashboard or
  `wrangler`, per `cloudflare_r2_setup.md`'s two-format note).

**Corrected root cause, mid-implementation** — the first live attempt
hit a real `403`/CORS failure on the R2 asset-browser's `ListObjectsV2`
call. Initial hypothesis was an R2 API token permission gap ("Object
Read & Write" not covering `ListBucket`) — checked against Cloudflare's
own docs and **ruled out**; that permission group does cover it. The
actual cause: R2 evaluates CORS rules top-to-bottom and stops at the
first `Origin` match. The wildcard PMTiles rule (`AllowedOrigins: ["*"]`)
sat *before* the specific-origin upload rule in `r2-cors.json`, so every
SigV4-authenticated request from `bulliexplorer.com` matched the tiles
rule first and got its narrower `AllowedHeaders` (no `Authorization`/
`x-amz-*`) — never reaching the upload rule at all. Fixed by reordering:
specific-origin rule first, wildcard fallback second. No permission
change was ever needed.

**Left over**

None — all three "Done when" checks passed against the live site: a
real test upload (`DSC_2655-01.jpeg`) landed in R2 under `media/`
(confirmed via the R2 dashboard), and the browser Network tab showed a
direct `PUT` to the R2 endpoint, not any BulliExplorer route.

**Housekeeping still open, not blocking Phase 1's own scope:**

- **Rotate the R2 Access Key ID/Account ID** — both were printed in
  cleartext during live in-container verification and are visible in
  this session's transcript. Access Key ID alone (without its paired
  Secret Access Key, which was never typed anywhere in-session) can't
  authenticate, so this isn't an active compromise, but a cheap,
  easy-to-do rotation given it's already sitting in history somewhere
  it doesn't need to.
- **Orphan test object in R2**: `media/DSC_2655-01.jpeg` exists in the
  bucket from the "Done when" verification upload, but no post's
  frontmatter references it (that test post's `.md` file was never
  actually saved through the CMS — see Phase 3's leftover note). Safe
  to delete from the R2 dashboard whenever convenient; not urgent, not
  costing anything meaningful at this size.

**Summary**

- Redesigned the credential-delivery mechanism mid-phase after review:
  `config.yml` moved from a static file (briefly holding a commented-out
  block with a real account ID) to a dynamic FastAPI route sourcing the
  R2 block from `Settings`/`.env` at request time. The static template
  is now permanently credential-free by construction, not by discipline.
- `docs/dev/r2-cors.json` was reshaped into two rules: the existing
  PMTiles rule preserved verbatim, plus a Sveltia upload rule
  (GET/PUT/HEAD, `AllowedHeaders: ["*"]`, `ETag` exposure) restricted
  to the editor's own origins (`bulliexplorer.com` + local dev). The
  originally drafted single-rule replacement would have broken live
  map tiles on the same bucket.
- Test suite replaced `test_config_yml_r2_media_library_block` (which
  parsed the static file directly — made obsolete by the redesign) with
  two tests hitting the live route: R2 unset → byte-identical to the
  template, R2 set → correctly shaped injection. Plus
  `tests/unit/test_r2_cors.py` guarding the tiles rule against
  regression.
- One unrelated, incidental fix: `test_index_html_is_valid_html` had an
  exact-case `<!DOCTYPE html>` assertion that broke when `djlint`'s
  formatter normalized the file to lowercase `<!doctype html>` as a side
  effect of an earlier, unrelated reformatting pass. Made the assertion
  case-insensitive — HTML doctype casing is meaningless per spec.
- Sveltia's own docs are marked still-in-development, so the R2
  integration was additionally verified in the Sveltia CMS source —
  which corrected an earlier assumption that the library key is
  arbitrary: it must be exactly `cloudflare_r2`.

**Recommended next steps**

- Confirmed, not just anticipated: Sveltia hotlinks R2 assets —
  frontmatter got **full URLs** (`{public_url}/media/filename`), exactly
  the shape Phase 2's `geo_sync.py` HTTPS-fetch fix was built for.
- **Done**: removed `media_folder`/`public_folder` from `config.yml`,
  and the gallery `Images.src` field's own field-level override (it had
  its own independent git-backed folder, confirmed by reading Sveltia's
  `getAssetLibraryFolderMap` — removing only the top-level pair would
  have left that one field still offering/defaulting to git). Verified
  safe against Sveltia's own source: `media_folder` is only required
  when there's no cloud media library configured
  (`parser/media.js::hasCloudMediaLibrary`), which no longer applies
  here. Confirmed against the live `/editor/config.yml` route — R2 is
  now the only media option anywhere in the config, no git fallback
  path left for any field.

**Done when**

- [x] Opening the media library in `/editor/` prompts for the R2 secret
  key once, then shows the asset browser without errors.
- [x] A test image uploaded through the editor lands in R2 under the
  `media/` prefix — confirmed via the R2 dashboard, not just "the editor
  didn't error." (`DSC_2655-01.jpeg`, verified in the bucket listing.)
- [x] The browser network tab shows the upload as a direct `PUT` to the
  R2 endpoint, not a request to any BulliExplorer server route —
  confirms no backend proxy accidentally got involved.

### Phase 2 — Migrate existing committed files

**Scope**

- [x] **Before touching any frontmatter** — `app/services/geo_sync.py`'s
  `_resolve_gpx_path` (line 324) currently only resolves *filesystem*
  paths. It has no branch for an `https://` URL at all. Pointing
  `route.gpx_file` at an R2 URL without fixing this first means the
  route silently fails to resolve — no error, just a skipped route, and
  the map/stats quietly disappear from every migrated post. This is a
  real gap the original draft of this doc missed entirely; caught in
  review before Phase 2 started, not after.

  Fix: teach `_resolve_gpx_path`/`_parse_gpx` to fetch over HTTPS when
  the value starts with `http`. `httpx` is already a project dependency
  — no new package needed, just a branch:

  ```python
  if gpx_file.startswith(("http://", "https://")):
      response = httpx.get(gpx_file, timeout=10)
      response.raise_for_status()
      # parse response.text instead of reading from a local Path
  ```

  Add this **as its own sub-step with its own test** (a fixture route
  pointing at a mocked HTTPS URL, resolving correctly) before migrating
  any real post — this is exactly the kind of thing that must be proven
  working on a throwaway fixture first, not discovered via a real post's
  map going blank.

  Implemented as `httpx.AsyncClient`-based (not the doc's original sync
  `httpx.get` sketch) — matches the existing dependency-injection
  convention already used by `sync_pois`/`_geocode` in the same module
  (optional `http_client` kwarg, default-create-and-close when `None`),
  so it's mockable in tests without a real network call and doesn't
  block the event loop. New `_fetch_gpx_over_http` helper; `_parse_gpx`
  and `sync_route` both gained an `http_client: httpx.AsyncClient | None
  = None` kwarg. Guarded by 5 new tests in `tests/unit/test_geo_sync.py`
  (mocked https/http fetch, network error, non-2xx, and the
  no-client-given default path) plus the 8 pre-existing `_parse_gpx`
  tests converted to `async`/`await` for the now-async signature.
- [x] Upload every currently-committed upload to R2 under `media/`, same
  pattern as the PMTiles upload:

  ```bash
  aws s3 cp static/uploads/kinzig_valley_oop.jpeg s3://bulliexplorer/media/kinzig_valley_oop.jpeg --endpoint-url $S3_ENDPOINT_URL
  # repeat for: nc4200_cover.png, SCR-20260825-mtsh.jpeg,
  # kinzig-valley-loop.gpx, dream_of_north.gpx, galleries/*.jpg
  ```

  Done via a one-off `boto3` script in `.scratch/` (gitignored, deleted
  after use per `AGENTS.md` rule 1) using the existing `S3_*` backup-cron
  credentials — the `aws`/`wrangler` CLIs above aren't installed locally,
  and installing a CLI for a single migration run isn't worth it when
  `boto3` is already a project dependency.
- [x] Update every affected post's frontmatter (`cover_image`,
  `route.gpx_file`, gallery entries) from `/static/uploads/...` to the
  new R2 public URL + `media/` path. Images are unaffected by the
  HTTPS-fetch gap above — they're rendered as plain `<img src>` URLs in
  templates, never read from local disk by app code.
- [x] Verify each post still renders correctly (images, GPX-derived map and
  stats) before removing anything from git.
- [x] `git rm` the migrated files from `static/uploads/`, commit.

**Left over**

None.

**Summary**

- Fixed the real gap this phase's scope called out: `_parse_gpx` (and
  its new `_fetch_gpx_over_http` helper) now fetches `http(s)://` GPX
  URLs instead of only resolving local filesystem paths, using an
  injectable `httpx.AsyncClient` for testability — consistent with the
  module's existing `sync_pois`/`_geocode` pattern rather than the
  doc's original blocking-`httpx.get` sketch. `sync_route` and
  `_parse_gpx` both became `async`.
- Also fixed, found while touching the file: an unguarded `float()`
  conversion in `_geocode` on a malformed Nominatim response, and a
  latent `NameError` in `_parse_gpx`'s "fewer than 2 track points" log
  line (referenced a `path` variable that was never defined on the
  URL branch).
- Uploaded all 7 committed files (`kinzig_valley_oop.jpeg`,
  `nc4200_cover.png`, `SCR-20260825-mtsh.jpeg`, `kinzig-valley-loop.gpx`,
  `dream_of_north.gpx`, `galleries/1000088777.jpg`,
  `galleries/15152.jpeg`) to R2 under `media/`, verified `200` on every
  resulting `pub-<hash>.r2.dev/media/...` URL.
- Migrated all three posts' frontmatter to the new R2 URLs and verified
  by actually running the app against the real `content/posts/` and the
  local DB: all three posts return `200`, both GPX-backed posts
  (`dream-of-north`, `kinzig-valley-loop`) show the R2 GPX fetch
  succeeding live in the startup logs and render map/stats data, and
  `sunday-gravel-loop` (no route field) is unaffected. Only then were
  the 7 files `git rm`'d from `static/uploads/`.

**Recommended next steps**

- Phase 3's `github_sync.py` simplification can proceed — nothing new
  writes into `static/uploads/` (Phase 1) and the 7 pre-existing files
  are now gone from the working tree (this phase), so the webhook's
  fetch step has nothing left to fetch there. `galleries/.gitkeep` is
  the only thing left in `static/uploads/` — kept deliberately, as the
  git-based upload fallback directory when R2 isn't configured.
- Phase 3 should double check `docker-compose.prod.yml`'s volume mount
  note against issue #10's fix as planned, but there's no *new* wrinkle
  from this phase to fold in beyond what's already documented there.
- One schema implication worth flagging for whoever edits `geo_sync.py`
  next: `sync_route`/`_parse_gpx` are no longer purely-local-filesystem
  functions — a route sync now makes a real network call whenever
  `gpx_file` is a URL. Currently only exercised at app startup and via
  the webhook resync; nothing in this phase needed retry/backoff logic
  beyond letting `httpx.HTTPError` propagate to "skip this route,
  log a warning" (already `sync_route`'s existing behavior for a bad
  GPX), and that seemed sufficient for R2's actual reliability — not
  revisited further, but worth knowing if it ever needs to.

### Phase 3 — Simplify `github_sync.py`

**Scope**

- [x] Remove the `static/uploads/` fetch step from the webhook sync — it
  exists specifically because uploads used to arrive via git; once
  Phase 1+2 land, nothing new writes there and Phase 2 emptied out what
  did.
- [x] Update `docker-compose.prod.yml`: the `static/uploads/` case for the
  volume mount is now folded into the broader `static/` mount from issue
  #10's fix — confirm no dangling reference to the old narrower mount
  remains.

**Done when**

- [x] `github_sync.py`'s test suite still passes with the simplified fetch
  logic — one less thing to fetch means one less thing that can fail
  (e.g. the earlier `IsADirectoryError` bug class shrinks in surface
  area, not just gets patched).
- [ ] A new post created through Sveltia still publishes correctly
  end-to-end via the webhook (the `.md` file, specifically — images no
  longer touch this path at all post-Phase-1/2, so a new image isn't
  actually part of what this check is proving) — confirms the
  simplified sync still does its actual job, not just that it runs
  without erroring.

**Left over**

- The full live check (create a post through Sveltia's UI, confirm the
  `.md` file publishes via a real GitHub webhook push) still needs a
  browser and a real webhook trigger on the deployed server — neither
  available to the agent. What *was* verified instead: the full unit
  test suite (5 tests, including a new explicit assertion that
  `static/uploads` is never requested) passes, and an attempt to
  exercise `fetch_and_write` against the *real* GitHub Contents API
  failed only because the local `.env`'s `GITHUB_TOKEN` is a dev
  placeholder (`dev-github...`, not a real PAT) — expected, since local
  dev edits `content/posts/` directly on disk and never needs a working
  token; the production server has the real one.

  **Checked explicitly, not assumed**: a real test upload was made
  through the live Sveltia editor during Phase 1's verification
  (`DSC_2655-01.jpeg`, landed in R2 — see Phase 1). That upload was
  **not** followed by an actual "Save" in the CMS — confirmed via
  `git log`, no commit exists anywhere past `095e877` from a Sveltia-
  style auto-commit, and no post's frontmatter references that file.
  So it doesn't satisfy this item; the orphaned R2 object is noted in
  Phase 1's housekeeping instead. This is still the one "Done when"
  item this phase leaves unchecked — needs a real post *saved* via
  Sveltia + a real webhook push against the deployed server to close
  out.

**Summary**

- Removed `("static/uploads", "static/uploads")` from `github_sync.py`'s
  `_SYNC_DIRS`, so the webhook sync now only ever fetches
  `content/posts/`. Updated the module and `fetch_and_write` docstrings,
  and `app/routes/internal.py`'s `github_webhook` docstring, to match.
- Removed dead unreachable code found while touching the file: a
  `logger.info(...)` + `return counts` block sitting after an earlier
  `return counts` in `_sync_dir` that could never execute.
- `docker-compose.prod.yml` already used the broader `./static:/app/static`
  mount (issue #10's fix predates this phase) — confirmed no dangling
  narrower `static/uploads`-only mount exists anywhere; nothing to change
  there.
- Updated `tests/unit/test_github_sync.py`'s 5 tests to drop the
  now-dead `static/uploads` mocking branches, and added an explicit
  assertion that the client never requests a `static/uploads` URL.

**Recommended next steps**

- Phase 4's "full read-through of all three real posts" should happen
  on the *deployed* site, not just local dev — that's also the natural
  moment to close out this phase's one open item (create a real post
  through Sveltia with a new image, confirm it lands correctly through
  the real webhook), since both need the production `GITHUB_TOKEN` and
  `WEBHOOK_SECRET` that aren't available locally.
- No code-side surprises to fold into Phase 4's scope — the
  `docker-compose.prod.yml` mount was already correct going in, and
  removing the fetch step was a clean subtraction with no ripple effects
  found elsewhere in the codebase (`app/main.py`'s startup sync only
  ever touched `content/posts/` anyway, independent of the webhook
  path).

### Phase 4 — Verification and close-out

**Scope**

- [ ] Full read-through of all three real posts on the live site, mobile
  and desktop, confirming nothing regressed.
- [x] Update `buckets.md` bucket #5.
- [~] Update `issues_phase4.md` if this surfaces anything unexpected
  (matches the project's established pattern of a running issues log for
  anything found mid-implementation, not just planned work). **Not
  done as written** — that file is titled/scoped to the UI/UX refresh's
  own Phase 4 (`ui_ux_refresh.md`), not a generic project-wide issues
  log; adding an unrelated media-storage bug there would be scope-mixing
  under a misleading title. Documented the finding here instead (see
  Summary). Flagging the cross-reference in this doc's own scope
  section as likely just meaning "follow the same *pattern*", not
  literally that file — worth a human call either way.

**Done when**

- [x] `buckets.md` accurately reflects reality — same discipline as every
  other bucket closed in this project. (Reflects Phases 1-3 done and
  verified in production, Phase 4's visual pass and one Phase 3 item
  still open — not claiming full closure it hasn't earned.)

**Left over**

- The human visual read-through (mobile + desktop, live site) is
  unavoidably a browser task — MapLibre rendering and responsive layout
  aren't remotely verifiable. Everything checkable without a browser was
  checked instead (below).
- Phase 3's one open item (a real post created through Sveltia + a live
  webhook push, confirmed correct) is still open — rolled forward from
  Phase 3, not newly discovered here.

**Summary**

- Found and fixed a real, currently-live production bug while doing
  this phase's verification: the webhook only ever syncs *data*
  (`content/posts/`, previously also `static/uploads/`) — it never
  redeploys the app's Python code. Phase 1's `make deploy` was the only
  deploy run during this whole migration; Phases 2 and 3's code changes
  sat undeployed on the server for about two days while the webhook had
  already pushed Phase 2's R2-URL frontmatter to production. Result:
  the *old* `_parse_gpx` (no HTTPS-fetch support) tried to resolve
  `https://pub-...r2.dev/media/dream_of_north.gpx` as a local path,
  logged `GPX file not found`, and silently dropped the route — both
  `dream-of-north` and `kinzig-valley-loop` lost their live map/stats
  in production without anyone noticing, confirmed from the container's
  own logs (`docker compose logs app`), not inferred.
- Fixed by running `make deploy` for real during this phase. Confirmed
  from the post-deploy logs that both GPX fetches now succeed
  (`HTTP/1.1 200 OK` against the R2 URLs) and `_SYNC_DIRS` inside the
  running container no longer includes `static/uploads`.
- Verified all three posts live on production (not local dev): all
  return `200`, all cover/gallery images resolve to R2 with correct
  `Content-Type`, both GPX-backed posts show non-zero distance/stats
  again, and zero remaining `/static/uploads` references in any
  rendered page.
- Updated `buckets.md` bucket #5 to reflect the true state — Phases 1-3
  done and production-verified, Phase 4's visual pass and Phase 3's
  webhook-created-post check still open, image optimization still a
  separately-tracked, larger, explicitly deferred gap.

**Recommended next steps**

- **Process fix, not just a one-off**: this migration's own "Done when"
  checks nearly passed on stale production code because content and
  code deploy through two entirely different paths (webhook vs.
  `make deploy`) with no automatic link between them. Worth a real
  decision, outside this doc's scope: either the webhook path should
  trigger a deploy check, or `make ci`/the PR checklist should gain an
  explicit "does this change require a `make deploy`" reminder
  whenever a commit touches both `app/` and `content/`. Flagging, not
  solving, here.
- You (not me) still need to: do the mobile+desktop visual read-through
  on the live site, and create one real post via Sveltia with an image
  to confirm the full webhook path end-to-end — both are what's left
  before bucket #5 can honestly move to fully ✅ done.
- Resolve the `issues_phase4.md` cross-reference ambiguity noted above
  — either this doc meant "follow that file's *pattern*" (in which case
  no rename needed, just don't literally write into it) or a dedicated
  `issues_media_storage.md` should exist. Either is fine; picking one
  avoids the next agent guessing again.

---

## What happens to what's already in git history

Migrating files out of `static/uploads/` removes them from the *working
tree*, not from git's history — the commits that originally added
`kinzig_valley_oop.jpeg` etc. still exist and still take up space in
every clone. **Not fixing that with a history rewrite (`git filter-repo`
or similar)** — a handful of MB isn't worth the disruption of rewritten
commit hashes on a repo with active local clones (yours, and this
review's). The fix here is stopping the bleeding going forward, not
erasing the past.

## Explicitly deferred

- **Production custom domain for the R2 bucket** (`media.bulliexplorer.com`
  via Route 53, instead of the rate-limited `pub-<hash>.r2.dev` dev URL).
  Same nuance already flagged in `cloudflare_r2_setup.md` for the tiles
  bucket — worth doing eventually, not blocking this migration. The
  `r2.dev` URL is already proven working in production for tiles.
- **Image optimization/WebP conversion on upload** — Sveltia's R2
  integration docs mention this is currently a Git-backend-only feature,
  not yet available for external media libraries. Real gap, tracked here
  so it's not forgotten, not solved in this pass.
