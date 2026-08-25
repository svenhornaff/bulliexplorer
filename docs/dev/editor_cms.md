# BulliExplorer — Content Editor (Sveltia CMS)

> Adds a browser-based WYSIWYG editor for posts and images, without adding a
> CMS backend to the app. See `bulliexplorer_stack_concept.md` for overall
> architecture, `post_and_backend.md` for the blog-post slice this builds on,
> and `AGENTS.md` for rules this work must follow.

---s

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

### Phase 1 — GitHub personal access token

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

### Phase 2 — Editor page + config

**Scope**
- `static/editor/index.html` — minimal HTML loading the Sveltia CDN
  bundle, served by the existing FastAPI static mount (no new route
  needed beyond exposing the path — confirm `/editor/` isn't shadowed by
  anything in `app/routes/`).
- `static/editor/config.yml` — the schema above.
- Caddy: no change needed — already serves everything under `static/`.

**Done when**
- `https://bulliexplorer.com/editor/` loads the Sveltia UI and completes
  GitHub login via the PAT from Phase 1.
- Existing posts (synced from `content/posts/`) are visible and editable
  in the Sveltia UI, fields matching `PostFrontmatter` correctly.

### Phase 3 — End-to-end publish test

**Scope**
- Create one new post entirely through the editor: title, summary, cover
  image upload, body — save.
- Confirm the commit landed on `develop` in GitHub.
- `git pull` + `/internal/resync` on the server, confirm it's live.

**Done when**
- A post created start-to-finish in the browser, with zero terminal use
  except the final `git pull` + resync call, is live and correctly
  rendered.

---

## Explicitly deferred (Phase 4, later, not now)

- **Webhook auto-pull**: GitHub webhook → authenticated endpoint on the
  server that runs `git pull` + `/internal/resync` automatically, removing
  even the SSH step from publishing. Real value, but the manual two-command
  version from Phase 3 is a small enough friction to defer until it's
  actually annoying — not worth the webhook-signature-verification code
  and the new public endpoint's attack surface before that's proven true.
- **R2 for uploaded images** (already deferred from `post_and_backend.md`)
  — Sveltia's `media_folder` config would need to change from
  `static/uploads` to an S3-compatible target if/when this happens. Small
  config change, not a redesign — fine to defer independently.

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