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

**Scope**

- [ ] Create a **dedicated** Account API token (Object Read & Write, scoped
  to the `bulliexplorer` bucket) for Sveltia's media use — separate from
  the token used for the manual PMTiles upload, so each credential's
  blast radius and rotation stay independent (same least-privilege
  pattern used everywhere else in this project).
- [x] Add the `media_libraries` block to `static/editor/config.yml` —
  landed fully formed but **commented out**, pending the token above:
  activation is uncomment + paste the Access Key ID, not a rewrite. The
  schema was verified against the Sveltia CMS source, not just the
  still-in-development official docs (see the ✅ note above). Shape is
  guarded by `tests/unit/test_editor.py::test_config_yml_r2_media_library_block`.
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
- [ ] Re-apply the updated CORS policy to the bucket (dashboard or
  `wrangler`, per `cloudflare_r2_setup.md`'s two-format note).

**Left over**

- **Token creation** — needs the Cloudflare dashboard; nothing in the
  repo can do it. The config.yml block stays commented until it exists.
- **`config.yml` activation** (uncomment + paste Access Key ID) —
  blocked on the token above.
- **Re-applying `r2-cors.json` to the bucket** — manual Cloudflare-side
  step; can be done any time with existing tiles credentials, but must
  land before the first upload test.
- **All three "Done when" checks** (in-browser secret prompt, test
  upload under `media/`, direct `PUT` in the network tab) — blocked on
  the three items above; they are browser/dashboard steps, not repo
  work.

**Summary**

- `docs/dev/r2-cors.json` was reshaped into two rules: the existing
  PMTiles rule preserved verbatim, plus a Sveltia upload rule
  (GET/PUT/HEAD, `AllowedHeaders: ["*"]`, `ETag` exposure) restricted
  to the editor's own origins (`bulliexplorer.com` + local dev). The
  originally drafted single-rule replacement would have broken live
  map tiles on the same bucket.
- `static/editor/config.yml` gained the verified
  `media_libraries.cloudflare_r2` block, commented out pending the
  dedicated token — including the real account ID and the existing
  `pub-…r2.dev` public URL, so activation is a paste-only step.
- Two new test guards landed: `tests/unit/test_r2_cors.py` (tiles rule
  cannot silently regress; upload rule matches Sveltia's documented
  requirements) and `test_config_yml_r2_media_library_block` in
  `tests/unit/test_editor.py` (the R2 block parses as valid YAML with
  the required flat-schema keys in both its commented and active
  states).
- Sveltia's own docs are marked still-in-development, so the R2
  integration was additionally verified in the Sveltia CMS source —
  which corrected the doc's earlier claim that the library key is
  arbitrary: it must be exactly `cloudflare_r2`.

**Recommended next steps**

- Create the dedicated token (Object Read & Write, scoped to
  `bulliexplorer`), activate the config block, re-apply the CORS
  policy, then run the three "Done when" checks in the browser —
  everything left in Phase 1 is Cloudflare/dashboard work.
- Sveltia hotlinks R2 assets: frontmatter will get **full URLs**
  (`{public_url}/media/filename`) — exactly the shape Phase 2's
  `geo_sync.py` HTTPS-fetch fix anticipates. No plan change needed.
- Phase 2 should additionally plan to **remove
  `media_folder`/`public_folder`** from config.yml after frontmatter
  migration: while they exist, every upload widget shows a provider
  picker (git vs R2) and drag-and-drop is disabled — and removing them
  is what makes accidental git uploads impossible. Note the editor's
  previews of *existing* posts depend on `public_folder` until their
  frontmatter is migrated to R2 URLs, so the removal must follow, not
  lead, the migration.

**Done when**

- Opening the media library in `/editor/` prompts for the R2 secret key
  once, then shows the asset browser without errors.
- A test image uploaded through the editor lands in R2 under the `media/`
  prefix — confirmed via the R2 dashboard, not just "the editor didn't
  error."
- The browser network tab shows the upload as a direct `PUT` to the R2
  endpoint, not a request to any BulliExplorer server route — confirms
  no backend proxy accidentally got involved.

### Phase 2 — Migrate existing committed files

**Scope**

- **Before touching any frontmatter** — `app/services/geo_sync.py`'s
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
- Upload every currently-committed upload to R2 under `media/`, same
  pattern as the PMTiles upload:

  ```bash
  aws s3 cp static/uploads/kinzig_valley_oop.jpeg s3://bulliexplorer/media/kinzig_valley_oop.jpeg --endpoint-url $S3_ENDPOINT_URL
  # repeat for: nc4200_cover.png, SCR-20260825-mtsh.jpeg,
  # kinzig-valley-loop.gpx, dream_of_north.gpx, galleries/*.jpg
  ```

- Update every affected post's frontmatter (`cover_image`,
  `route.gpx_file`, gallery entries) from `/static/uploads/...` to the
  new R2 public URL + `media/` path. Images are unaffected by the
  HTTPS-fetch gap above — they're rendered as plain `<img src>` URLs in
  templates, never read from local disk by app code.
- Verify each post still renders correctly (images, GPX-derived map and
  stats) before removing anything from git.
- `git rm` the migrated files from `static/uploads/`, commit.

**Done when**

- Every existing post (`sunday-gravel-loop`, `kinzig-valley-loop`,
  `dream-of-north`) renders identically to before — cover image, gallery,
  map, and stats all unchanged from a reader's perspective, just served
  from a different URL.
- `git log --stat` on the removal commit shows the binaries leaving the
  working tree (their *history* remains, expected and fine — see note
  below).
- `curl -I` on each new R2 URL returns `200`.

### Phase 3 — Simplify `github_sync.py`

**Scope**

- Remove the `static/uploads/` fetch step from the webhook sync — it
  exists specifically because uploads used to arrive via git; once
  Phase 1+2 land, nothing new writes there and Phase 2 emptied out what
  did.
- Update `docker-compose.prod.yml`: the `static/uploads/` case for the
  volume mount is now folded into the broader `static/` mount from issue
  #10's fix — confirm no dangling reference to the old narrower mount
  remains.

**Done when**

- `github_sync.py`'s test suite still passes with the simplified fetch
  logic — one less thing to fetch means one less thing that can fail
  (e.g. the earlier `IsADirectoryError` bug class shrinks in surface
  area, not just gets patched).
- A new post created through Sveltia, with a new image, still publishes
  correctly end-to-end via the webhook — proves the simplified sync still
  does its actual job, not just that it runs without erroring.

### Phase 4 — Verification and close-out

**Scope**

- Full read-through of all three real posts on the live site, mobile and
  desktop, confirming nothing regressed.
- Update `buckets.md` bucket #5 to done.
- Update `issues_phase4.md` if this surfaces anything unexpected (matches
  the project's established pattern of a running issues log for anything
  found mid-implementation, not just planned work).

**Done when**

- `buckets.md` accurately reflects reality — same discipline as every
  other bucket closed in this project.

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
