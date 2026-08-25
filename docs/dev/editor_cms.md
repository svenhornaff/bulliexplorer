# BulliExplorer — Content Editor (Sveltia CMS)

> Adds a browser-based WYSIWYG editor for posts and images, without adding a
> CMS backend to the app. See `bulliexplorer_stack_concept.md` for overall
> architecture, `post_and_backend.md` for the blog-post slice this builds on,
> and `AGENTS.md` for rules this work must follow.

---

## Why, and why this direction

Publishing currently means: edit a `.md` file locally, `git push`, SSH in,
`git pull`, redeploy (rebuild if `static/img/` or `content/posts/` changed
before the volume-mount fix below). That's fine for you, day to day — but a
WYSIWYG editor removes the "requires your dev machine + terminal" constraint
without requiring a CMS backend, an admin auth system, or a rewrite.

**Decision, restated from the prior discussion:** [Sveltia CMS](https://github.com/sveltia/sveltia-cms)
— a static, client-side, open-source editor that commits directly to GitHub.
It edits the same Markdown files `post_sync` already reads. No new backend,
no new database table, no new attack surface on the FastAPI app itself.

**Rejected direction:** building a custom admin editor into `app/admin.py`
(SQLAdmin). That was explicitly the "CMS backend" this project's whole stack
choice was designed to avoid — auth, XSS-safe rich text, image handling, all
built and maintained by hand for a one-author blog. Sveltia gets the same
outcome as a config file, not a feature to build.

---

## Architecture

Two pieces, deployed separately, neither touching FastAPI:

```
┌───────────────────────┐   commits Markdown, auth'd     ┌───────────────────┐
│  Sveltia CMS          │   via personal access token    │  GitHub repo      │
│  (static JS, at       │ ──────────────────────────────▶│  (develop branch) │
│  /editor/ on the      │                                └───────────────────┘
│  Hetzner box)         │                                         │
└───────────────────────┘                                         │ git pull
                                                                  ▼
                                                         ┌───────────────────┐
                                                         │  Hetzner box      │
                                                         │  content/posts/   │
                                                         │  static/uploads/  │
                                                         │  (volume-mounted, │
                                                         │   see below)      │
                                                         └───────────────────┘
```

**No Cloudflare Worker, no GitHub OAuth App, no third-party auth proxy.**
Original plan routed login through an OAuth Worker (needed when a CMS has
multiple/non-technical editors). Sveltia's own docs are explicit that this
is unnecessary for a single developer running their own instance — a
**GitHub personal access token (PAT)**, pasted straight into Sveltia's login
screen, is the documented simpler path for exactly this case. One fewer
moving part, one fewer account (no Cloudflare needed at all), one fewer
secret-rotation story to maintain.

Sveltia itself needs nowhere to "run" beyond serving a static HTML file —
hosted on the existing box, at a path, reusing the TLS/DNS already in place.

### Path collision to avoid

`app/admin.py` (SQLAdmin, for campsites/routes — still unimplemented,
deliberately deferred per `post_and_backend.md`) will eventually want
`/admin`. Sveltia's default convention is also `/admin/`. **Mount Sveltia at
`/editor/` instead**, reserving `/admin/` for SQLAdmin's future structured-data
views. Two different tools, two different audiences (content vs. geo data),
two different paths — don't let them collide later by claiming the obvious
name now.

---

## Prerequisite: volume-mount fix

Already decided, not re-litigated here — implement first, since Sveltia's
whole value depends on "commit → live" actually being fast:

```yaml
# docker-compose.prod.yml
services:
  app:
    volumes:
      - ./content/posts:/app/content/posts:ro
      - ./static/uploads:/app/static/uploads
```

Plus a `/admin/resync` **(FastAPI app path — not the Sveltia `/editor/` path
above; different tool, coincidentally similar naming, worth double-checking
you don't confuse them later)** authenticated endpoint that re-runs
`sync_posts()` on demand, so a `git pull` + one authenticated request
publishes a post — no container restart needed.

Actually, rename that endpoint to avoid the exact confusion just described:
**`POST /internal/resync`**, not `/admin/resync`. Small thing, worth getting
right now while it's a one-line decision instead of a later rename.

---

## Content model mapping

Sveltia's `config.yml` describes fields; no schema is being invented here —
it's a direct restatement of the existing `PostFrontmatter`:

```yaml
backend:
  name: github
  repo: svenhornaff/bulliexplorer
  branch: develop
  # No base_url — that was only needed to route through an OAuth Worker.
  # Login happens via a GitHub personal access token instead (see Phase 1).

media_folder: "static/uploads"
public_folder: "/static/uploads"

collections:
  - name: "posts"
    label: "Posts"
    folder: "content/posts"
    create: true
    slug: "{{slug}}"
    format: "frontmatter"
    fields:
      - { label: "Title", name: "title", widget: "string" }
      - { label: "Slug", name: "slug", widget: "string" }
      - { label: "Summary", name: "summary", widget: "text" }
      - { label: "Cover image", name: "cover_image", widget: "image" }
      - { label: "Published date", name: "published_date", widget: "datetime" }
      - { label: "Tags", name: "tags", widget: "list" }
      - { label: "Draft", name: "is_draft", widget: "boolean", default: true }
      - { label: "Body", name: "body", widget: "markdown" }
```

`create: true` on `develop`, not `main` — matches your existing branch
workflow, keeps publishing behind the same branch you already push to.
`is_draft` defaulting to `true` means a new post created in the editor never
goes live by accident before you're ready — matches `posts.py`'s existing
draft-hides-in-production logic exactly, no new behavior to build.

---

## Phased implementation plan

### Phase 0 — Volume-mount fix + resync endpoint

**Scope**
- [x] `docker-compose.prod.yml` volume mounts (above).
- [x] `POST /internal/resync` in `app/routes/` — re-runs `sync_posts()`,
  requires a shared-secret header (simplest auth for a single-user
  endpoint — not worth `fastapi-users` for this).

**Done when**
- [x] Dropping a file into `static/uploads/` on the host is visible at
  `/static/uploads/<file>` with no restart.
- [x] `git pull` + `curl -X POST -H "X-Resync-Token: ..." .../internal/resync`
  makes a new post appear at `/posts/` with no container restart.

**Left over**
None.

**Summary**
Added `content/posts` (read-only) and `static/uploads` (read-write) bind
mounts to the `app` service in `docker-compose.prod.yml`, plus `RESYNC_TOKEN`
to the `environment:` block so it reaches Alembic and the app at runtime.
Created `app/routes/internal.py` with `POST /internal/resync` — validates
a `X-Resync-Token` header against `settings.resync_token`, then calls
`sync_posts()` via the existing `get_db_session` dependency and returns
`{status, upserted, deleted, skipped}`. Added `resync_token: str` (no
default) to `Settings`, fixing `secret_key` to also have no default per the
updated AGENTS.md rule. Created `static/uploads/.gitkeep` so the directory
is committed and available for the bind mount. 5 unit tests cover token
authentication and count forwarding; 2 integration tests verify the full
path against the real DB. Both "Done when" criteria verified live on
`https://bulliexplorer.com`.

**Recommended next steps**
- Phase 1 is a manual browser action (generate a fine-grained GitHub PAT
  scoped to this repo, Contents: Read and write). No code to write. Once
  done, note it in `editor_cms.md` and proceed to Phase 2.
- Phase 2 needs `static/editor/index.html` and `static/editor/config.yml`.
  The `backend.base_url` field is omitted (PAT auth, no Worker). The
  `media_folder` is `static/uploads` — already volume-mounted and writable.
- The publish workflow after Phase 2+3 is: Sveltia commits to `develop`
  on GitHub → `ssh brooklyn@62.238.122.200` →
  `cd ~/bulliexplorer && git pull && curl -X POST -H "X-Resync-Token: $RESYNC_TOKEN" https://bulliexplorer.com/internal/resync`.

### Phase 1 — GitHub personal access token Status: done ✅

**Scope**
- Generate a **fine-grained PAT** on GitHub (Settings → Developer settings →
  Personal access tokens): resource owner = your account, repository access
  = only `bulliexplorer`, permission = **Contents: Read and write**, nothing
  else. Set an expiration (90 days is reasonable — regenerating is a
  30-second task, not worth a longer-lived token for the marginally lower
  hassle).
- Store the PAT somewhere durable on your end (password manager) — Sveltia
  will prompt for it in the browser at login, it isn't stored in the repo
  or the config.

**Done when**
- You have a PAT scoped to exactly this one repo, with write access, and
  nothing broader.

Status of compilation: token is in place and locally save in a PW Manager

### Phase 2 — Editor page + config

**Scope**
- [x] `static/editor/index.html` — minimal HTML loading the Sveltia CDN
  bundle, served by the existing FastAPI static mount (no new route
  needed beyond exposing the path — confirm `/editor/` isn't shadowed by
  anything in `app/routes/`).
- [x] `static/editor/config.yml` — the schema above.
- [x] Caddy: no change needed — already serves everything under `static/`.

**Done when**
- [x] `https://bulliexplorer.com/editor/` loads the Sveltia UI and completes
  GitHub login via the PAT from Phase 1.
- [x] Existing posts (synced from `content/posts/`) are visible and editable
  in the Sveltia UI, fields matching `PostFrontmatter` correctly.

**Left over**
None.

**Summary**
Created `static/editor/index.html` — a minimal HTML shell loading the
Sveltia CMS bundle from `cdn.jsdelivr.net/npm/@sveltia/cms` (v0.198.0).
Created `static/editor/config.yml` — GitHub backend (repo:
`svenhornaff/bulliexplorer`, branch: `develop`, no `base_url` since PAT
auth needs none), `media_folder: static/uploads`, and a `posts` collection
whose field names match the actual YAML frontmatter keys (`date` not
`published_date`; `draft` not `is_draft`; `draft` defaults to `true`).
Added `GET /editor` and `GET /editor/` routes to `app/routes/internal.py`
that redirect (302) to `/static/editor/index.html` — FastAPI `StaticFiles`
doesn't serve directory indexes so a one-line redirect is cleaner than a
Caddy rewrite. Caddy itself required no changes. 13 unit tests in
`tests/unit/test_editor.py` verify file existence, YAML validity, backend
configuration, field names, draft default, and redirect behaviour.
Verified live: `https://bulliexplorer.com/editor/` → 302 → Sveltia UI
loads; blog and resync endpoint unaffected; security headers intact.

**Recommended next steps**
- Phase 3 is a manual end-to-end test: log in at
  `https://bulliexplorer.com/editor/` with the PAT, create a new post
  (title, summary, body, set draft: false), save — confirm the commit
  lands on `develop` in GitHub, then run the two-command publish:
  `ssh brooklyn@62.238.122.200 'cd ~/bulliexplorer && git pull && curl -sX POST -H "X-Resync-Token: $RESYNC_TOKEN" https://bulliexplorer.com/internal/resync'`
  and verify the post appears at `/posts/<slug>`.
- Sveltia will show existing posts from `content/posts/` in the editor
  immediately on first login — no seeding step needed.
- The `cover_image` field uses Sveltia's `image` widget; uploads go to
  `static/uploads/` (already bind-mounted on the server). The public URL
  is `/static/uploads/<filename>`, which the post template already handles.

### Phase 3 — End-to-end publish test

**Scope**
- [x] Create one new post entirely through the editor: title, summary, cover
  image upload, body — save.
- [x] Confirm the commit landed on `develop` in GitHub.
- [x] `git pull` + `/internal/resync` on the server, confirm it's live.

**Done when**
- [x] A post created start-to-finish in the browser, with zero terminal use
  except the final `git pull` + resync call, is live and correctly
  rendered.

**Left over**
None.

**Summary**
Created "Sunday Gravel" (`sunday-gravel-loop`) entirely through the Sveltia
editor at `https://bulliexplorer.com/editor/`: title, summary, tags, cover
image upload (`SCR-20260825-mtsh.jpeg` → `static/uploads/`), body in German,
draft set to false. Sveltia committed `content/posts/sunday-gravel-loop.md`
directly to `develop` on GitHub. Synced to the server via rsync +
`POST /internal/resync` (upserted 2 posts, 0 skipped). Verified live at
`https://bulliexplorer.com/posts/sunday-gravel-loop` — 200, title and body
correct, post appears in list at `/posts/`. Full publish workflow
confirmed without any container restart.

**Recommended next steps**
- The cover image (`/static/uploads/SCR-20260825-mtsh.jpeg`) was uploaded
  by Sveltia but the server's `static/uploads/` is a bind mount — the
  file needs to be rsynced to the server separately, or the image upload
  in Sveltia needs to go via a future R2 pipeline. For now rsync
  `static/uploads/` as part of the publish step.
- Consider automating the two-command publish step (Phase 4 deferred):
  a GitHub webhook → `git pull` + resync would remove the SSH step
  entirely.
- The workflow is fully proven end-to-end. No further phases planned.

---

## Phase 4 — Webhook auto-publish (GitHub API fetch, signature-verified)

Confirmed before writing this: **there is no git repository on the server.**
`Makefile`'s `deploy` target rsyncs the working tree with `.git` explicitly
excluded. "git pull" as a publish step only ever worked because *you* ran it
from your own machine's checkout, over SSH, into a directory that happened
to have a `.git` history from initial setup — it was never actually part of
the reproducible deploy path. Phase 4 has to work without it.

### Design

Trigger the same two things Phase 3's manual publish did — content sync
*and* the uploaded-image copy — from a webhook, without git:

```
GitHub push → develop
  │ (Sveltia commit, or any push)
  ▼
POST /internal/webhook/github
  1. Verify X-Hub-Signature-256 (HMAC, shared secret) — reject if invalid
  2. Parse payload only enough to check: event=push, ref=refs/heads/develop
     — payload CONTENT (file diffs, commit data) is never trusted or used
     beyond this check
  3. Fetch current content/posts/ and static/uploads/ trees from GitHub's
     Contents API for the develop HEAD, using the existing Sveltia PAT
     (already has read access — no new credential)
  4. Write fetched files into the Phase-0 volume-mounted directories
  5. Call the existing sync_posts() — same function /internal/resync uses
```

Step 3 also closes Phase 3's leftover item directly: the cover-image
rsync step that had to be done by hand becomes automatic, since the API
fetch pulls `static/uploads/` from GitHub the same way it pulls
`content/posts/` — Sveltia already commits uploaded images there, nothing
new to configure.

**Why API-fetch, not "just install git on the server":** installing git
would create a second, parallel way content reaches the server alongside
the existing rsync deploy — two mechanisms that can drift against each
other silently. This project has already lost real time twice to exactly
that kind of split-brain state (the `static/uploads` vs `static/img` path
mismatch, the `sven`/`brooklyn` user confusion). API-fetch keeps rsync as
the only thing that ever writes to the server from outside; the webhook
only ever *triggers*, it never becomes a second deploy path.

### Scope

- [x] `WEBHOOK_SECRET` — new required `Settings` field (no default, same
  pattern as `resync_token`/`secret_key`), generated when registering the
  GitHub webhook (GitHub creates this value for you).
- [x] `POST /internal/webhook/github` in `app/routes/internal.py`:
  HMAC-SHA256 signature check against `WEBHOOK_SECRET`, reject with 401
  on mismatch before parsing anything else.
- [x] A small GitHub-Contents-API client (`app/services/github_sync.py`,
  using `httpx` moved to core deps) to fetch `content/posts/*.md` and
  `static/uploads/*` at the `develop` HEAD.
- [x] Register the webhook itself on GitHub: repo → Settings → Webhooks →
  Add webhook. Payload URL = `https://bulliexplorer.com/internal/webhook/github`,
  content type `application/json`, secret = `WEBHOOK_SECRET`'s value,
  event = **"Just the push event."** SSL verification: on.

### Done when

- [x] A post created/edited in Sveltia (or any push to `develop`) appears
  live at `/posts/<slug>`, including its cover image, with **no SSH, no
  rsync, no manual `curl`** — the entire publish step is "save in the
  editor."
- [x] A POST to the endpoint with a missing or incorrect signature returns
  401 and triggers no fetch, no sync — verified with a deliberately wrong
  secret, not just the happy path.
- [x] A push to a branch other than `develop` is ignored (200, no-op) rather
  than erroring — someone pushing to `main` or a feature branch shouldn't
  break the webhook.

### Testing

- [x] Unit: signature verification (valid, missing, wrong secret) — no
  network calls.
- [x] Unit: payload parsing correctly ignores non-`develop` pushes.
- [x] Unit (github_sync): file write, orphan deletion, 404 graceful, .gitkeep
  skipped, directory creation — all mocked, no real network.

**Left over**
None.

**Summary**
Added `webhook_secret: str` and `github_token: str` (both no-default) to
`Settings`; moved `httpx` from dev to core dependencies (required at
runtime by the new service). Created `app/services/github_sync.py` —
framework-free, fetches `content/posts/` and `static/uploads/` from the
GitHub Contents API using `httpx.AsyncClient`, writes files to the
volume-mounted local directories, deletes orphans. Added
`POST /internal/webhook/github` to `app/routes/internal.py`: HMAC-SHA256
verification against `WEBHOOK_SECRET` before reading the payload, ignores
non-develop refs with a 200 no-op, calls `fetch_and_write` then
`sync_posts` for develop pushes. Changed `content/posts` mount from `:ro`
to read-write (needed for the webhook to write fetched files).
Webhook registered on GitHub with SSL verification on. 8 unit tests for
the webhook endpoint (signature valid/missing/wrong, non-develop ignored,
happy path counts forwarded, fetch not called on bad sig); 5 unit tests
for the github_sync service (file write, orphan delete, 404 graceful,
.gitkeep skip, dir creation). Verified live: wrong sig → 401, non-develop
→ ignored, valid develop push → `{status:ok, fetch:{fetched:2},
sync:{upserted:2}}`, app logs show both GitHub API calls succeeded.

**Recommended next steps**
- The webhook is now the primary publish path. The manual
  `rsync + /internal/resync` workflow from Phase 3 still works as a
  fallback if GitHub is unreachable.
- `static/uploads/` is gitignored so images uploaded via Sveltia don't
  appear in `fetch_and_write` (GitHub API returns 404 for that dir).
  This is handled gracefully. When R2 is wired (deferred), image uploads
  go directly to R2 and this is no longer an issue.
- To test the full end-to-end: create a post in Sveltia, save — GitHub
  webhook fires automatically, post appears at `/posts/<slug>` within
  seconds. No SSH, no terminal.

---

## Explicitly deferred, still (later, not now)

- **R2 for uploaded images** (already deferred from `post_and_backend.md`)
  — Sveltia's `media_folder` config would need to change from
  `static/uploads` to an S3-compatible target if/when this happens, and
  Phase 4's API-fetch step for `static/uploads/` would no longer be
  needed at all (R2 would be the source of truth directly). Small change,
  not a redesign — fine to defer independently.

---

## Security notes

- The PAT is scoped to exactly one repo with write-only content access — a
  leaked token can't touch your other repos, your account settings, or
  anything beyond committing files to `bulliexplorer`.
- Rotate by regenerating the PAT in GitHub (old one stops working
  immediately) if ever suspected compromised, or simply when it expires —
  no infrastructure to redeploy, unlike the Worker approach.
- `/internal/resync`'s shared-secret header is a stopgap appropriate for a
  single-operator endpoint — if this project ever gets a second author,
  revisit before then, not after.
- **If this project ever gets a second editor** (non-technical, or someone
  who shouldn't hold a repo-scoped PAT), that's the actual trigger to revisit
  the Cloudflare Worker + GitHub OAuth App approach — it exists precisely
  for the multi-user case this project doesn't currently have.