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
  default:
    name: cloudflare
    config:
      bucket: bulliexplorer
      account_id: <cloudflare-account-id>       # same account as the tiles bucket
      access_key_id: <access-key-id>             # NOT the secret — that's entered in-browser
      public_url: https://pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev
      path: media                                 # keeps uploads separate from tiles/
```

⚠️ **Field names above are reconstructed from the official docs, not
copy-pasted from a working config** — verify exact keys (`bucket` vs
`bucket_name`, whether `region` is required for R2) against
`sveltiacms.app/en/docs/media/cloudflare-r2` directly during Phase 1
implementation, same as the CORS-format lesson from the tiles setup.

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
- Create a **dedicated** Account API token (Object Read & Write, scoped
  to the `bulliexplorer` bucket) for Sveltia's media use — separate from
  the token used for the manual PMTiles upload, so each credential's
  blast radius and rotation stay independent (same least-privilege
  pattern used everywhere else in this project).
- Add the `media_libraries` block to `static/editor/config.yml` (verify
  exact schema against Sveltia's docs per the warning above).
- **Update `docs/dev/r2-cors.json` — the existing policy only allows
  `GET`/`HEAD`, which is correct for reading tiles but will reject
  browser uploads outright.** Add `PUT` (and `POST`/`DELETE` if the
  media library needs to support replacing/removing assets), and expand
  `AllowedHeaders` to cover what a SigV4-signed request sends
  (`Authorization`, `x-amz-date`, `x-amz-content-sha256`, `Content-Type`
  at minimum — confirm the full list against a real failed request in
  the browser console, same troubleshooting approach used for the tiles
  CORS fix).
- Re-apply the updated CORS policy to the bucket (dashboard or
  `wrangler`, per `cloudflare_r2_setup.md`'s two-format note).

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
- Upload every currently-committed upload to R2 under `media/`, same
  pattern as the PMTiles upload:
  ```bash
  aws s3 cp static/uploads/kinzig_valley_oop.jpeg s3://bulliexplorer/media/kinzig_valley_oop.jpeg --endpoint-url $S3_ENDPOINT_URL
  # repeat for: nc4200_cover.png, SCR-20260825-mtsh.jpeg,
  # kinzig-valley-loop.gpx, dream_of_north.gpx, galleries/*.jpg
  ```
- Update every affected post's frontmatter (`cover_image`,
  `route.gpx_file`, gallery entries) from `/static/uploads/...` to the
  new R2 public URL + `media/` path.
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
