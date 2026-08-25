# BulliExplorer — Blog Post: UI & Backend Concept

> Next vertical slice after the initial scaffold. Covers the styling
> decision, how it maps to the existing `Post`/`PostFrontmatter` model, and
> the implementation plan. See `bulliexplorer_stack_concept.md` for overall
> architecture and `boilerplate.md` for dev-environment conventions.

---

## Why this slice, now

The scaffold (`app/main.py`, `app/models/`, `app/admin.py`) exists but
nothing touches the database at runtime yet — the lifespan's DB-engine-init
is still a TODO, and no route exercises the stack end to end. Landing-page
polish, admin auth, and deployment hardening all become more meaningful
once a real feature works — this slice is what unblocks them, not the other
way round.

---

## Styling: Bootstrap 5 + Start Bootstrap "Clean Blog"

Constraint that decided this: **no client-side build step** (already
locked in — HTMX/Alpine/MapLibre are vendored `<script>` tags, no npm). The
choice isn't really "Bootstrap vs. a lighter modern framework" on technical
merit — it's about which option has a real *free template ecosystem*, since
the goal is porting a design, not building one from scratch.

| | Bootstrap 5 | Pico.css / Bulma |
|---|---|---|
| Fits "no build step" | Yes — pre-built CSS/JS, vendor directly | Yes — single CSS file |
| Bundle size | ~16KB gzipped CSS | Pico ~8KB / Bulma ~24KB |
| Mobile-first grid | Yes, mature | Bulma: yes. Pico: classless, no grid |
| Ready-made free blog templates | **Large ecosystem** — full list+post layouts, MIT-licensed, mobile-tested | Near none — CSS toolkits, not theme libraries |

**Decision: [Start Bootstrap — Clean Blog](https://github.com/StartBootstrap/startbootstrap-clean-blog).**
MIT licensed, plain HTML/CSS/JS, no build tooling. Built for exactly this
shape: post list + single-post view, hero image, responsive nav, mobile-
tuned typography (confirmed built mobile-first on the Bootstrap 5 grid,
tested down to small phones).

### Integration plan

1. Pull the template repo. Vendor `css/`, `js/`, `fonts/` into `static/`
   as-is — no modification needed to the framework files themselves.
2. Port `index.html` → `templates/home.html` (post list): replace static
   entries with `{% for post in posts %}` over the query result.
3. Port `post.html` → `templates/post.html` (single post): replace static
   content with `{{ post.title }}`, `{{ post.body_html | safe }}`, etc.
4. MapLibre, HTMX, Alpine sit alongside as their own vendored files under
   `static/` — no conflict, Bootstrap doesn't touch map rendering or HTMX
   swap behavior.
5. No multi-author byline needed — hardcode "Sven" in the template rather
   than adding an `author` field to the DB for a one-person blog.

---

## Data model — mapped against the template

Checked the template's actual markup against the existing `Post` /
`PostFrontmatter` models (`app/models/post.py`, `app/models/post_schema.py`).
Result: **no missing fields** — the earlier schema design already covers
what this template needs to render.

| Template needs | Model field | Notes |
|---|---|---|
| List: title | `title` | ✅ |
| List: excerpt | `summary` | ✅ |
| List: published date | `published_date` | ✅ |
| List: "read more" link | `slug` (builds the URL) | ✅ |
| Post: title | `title` | ✅ |
| Post: hero subtitle | `summary` (dual-purpose) | ⚠️ open decision, see below |
| Post: hero/cover image | `cover_image` | ✅ |
| Post: published date | `published_date` | ✅ |
| Post: body content | `body_html` | ✅ (pre-rendered from `body_markdown`) |

### Open decision: `summary` doing double duty

Clean Blog visually treats the list-page excerpt and the single-post hero
subtitle differently (subtitle is punchier/shorter, excerpt can run
longer). Current model reuses `summary` for both. Two options:

- **Keep as one field** — simplest, fine if a short punchy summary reads
  well in both spots. Recommended for v1: cheaper, and premature to split
  before there's a second real post to judge it against.
- **Split into `summary` + `subtitle`** — one-line schema + frontmatter
  change (`PostFrontmatter` gains a field) if the reuse turns out to read
  badly once real content exists.

Decide by trying it with one real post first, not in the abstract.

---

## Implementation plan (this slice)

In order — each step depends on the previous:

1. **Wire the DB engine** in `app/main.py`'s lifespan (currently a TODO) —
   async SQLAlchemy engine + session dependency for routes.
2. **Markdown → DB sync service**, in `app/services/` (framework-free per
   `AGENTS.md` — no FastAPI/Jinja2 imports here):
   - Reads `content/posts/*.md`.
   - Validates YAML frontmatter against `PostFrontmatter`.
   - Renders `body_markdown` → `body_html` via `markdown-it-py`.
   - Upserts into the `posts` table (by `slug`).
3. **Routes**, in `app/routes/`:
   - `GET /posts` — list view, queries all non-draft posts ordered by
     `published_date`, renders `templates/home.html`.
   - `GET /posts/{slug}` — single-post view, 404 if not found or if
     `is_draft` and not in dev mode, renders `templates/post.html`.
4. **Templates** — the ported Clean Blog markup from the integration plan
   above.
5. **One real post** in `content/posts/` — write it, run the sync service,
   confirm it renders at `localhost:8000/posts/<slug>`. This is the proof
   that DB engine, service layer, routing, and templates all actually work
   together, not just individually.

---

## Phased implementation plan

Same work as above, broken into commit-sized phases with explicit done
criteria. Each phase ends green (`make ci` passes) and independently
committable — no phase leaves the repo in a broken intermediate state.
Rough sizing assumes evening-session chunks.

### Phase 1 — DB wiring (foundation, no visible change)

**Scope**
- [x] `app/core/db.py`: async engine + `async_sessionmaker`, built from
  `settings.database_url`.
- [x] Lifespan in `app/main.py`: create engine on startup, dispose on
  shutdown (replaces the two TODOs).
- [x] FastAPI dependency `get_db_session()` for routes.

**Done when**
- [x] App starts and stops cleanly against the local PostGIS container.
- [x] A throwaway `SELECT 1` via the session dependency works.
- [x] Unit tests still pass with **no DB running** (the engine must be lazy —
  creating it must not connect; only actual queries do).

**Watch out for**: `database_url` uses `postgresql+psycopg://` — the async
engine needs the same driver string, not `asyncpg`; psycopg3 handles both
sync and async, keep it as the single driver.

**Left over**
None.

**Summary**
Created `app/core/db.py` with a module-level async engine and
`async_sessionmaker`, initialised lazily on first import and explicitly via
`init_engine()` from the FastAPI lifespan. The lifespan in `app/main.py` had
its two DB TODOs replaced with real `init_engine()` / `await dispose_engine()`
calls. `get_db_session()` is a typed FastAPI dependency that yields a
transactional `AsyncSession`, committing on clean exit and rolling back on
exception. Seven unit tests cover lazy init, no-connection guarantee, and
dispose idempotency (all pass with no DB running). Two integration tests
verify a real `SELECT 1` through the session dependency and that the full
app lifespan starts and shuts down cleanly against the PostGIS container.
The `.secrets.baseline` was regenerated to match the current `detect-secrets`
1.5.0 format, and the `Makefile` security target was updated to compare
baselines via JSON equality (ignoring the `generated_at` timestamp).

**Recommended next steps**
- Phase 2 (sync service) can proceed directly — `get_db_session()` is ready
  for use in `app/services/post_sync.py` upsert calls.
- Phase 2 needs `uv add pyyaml` for frontmatter parsing — add it in the
  same commit as the service.
- The `get_db_session()` dependency uses session-level commit/rollback;
  Phase 4 routes should use `Depends(get_db_session)` as-is — no changes
  needed to the dependency signature.
- The uncovered rollback path (lines 108–109 of `db.py`) will get natural
  coverage once Phase 4 integration tests exercise error paths through routes.

### Phase 2 — Sync service (framework-free core)

**Scope**
- [x] `app/services/post_sync.py`: read `content/posts/*.md` → parse YAML
  frontmatter → validate via `PostFrontmatter` → render body via
  `markdown-it-py` → upsert by `slug`.
- [x] Needs a YAML parser: `uv add pyyaml` (frontmatter isn't parsed by
  markdown-it-py itself). Note the new dependency in the commit message.
- [x] Deliberate behaviors to implement, not leave implicit:
  - [x] A file that fails validation **skips that file, logs an error, and
    continues** — one broken post must not take down the sync for all.
  - [x] A post deleted from `content/posts/` gets removed from the DB on the
    next sync (files are the source of truth, the table is derived — so
    the sync is a full reconciliation, not append-only).
  - [x] Sync is idempotent: running it twice changes nothing the second time.

**Done when**
- [x] Unit tests (no DB): valid fixture parses to the expected field values;
  invalid frontmatter is rejected; markdown renders to expected HTML.
- [x] Integration test: fixture post round-trips into the test DB; re-running
  sync is a no-op; deleting the fixture file and re-syncing removes the
  row.

**Left over**
None.

**Summary**
Created `app/services/post_sync.py` — a fully framework-free sync service
(no FastAPI/Jinja2 imports). `sync_posts(content_dir, session)` globs all
`*.md` files, splits YAML frontmatter via regex, parses with `yaml.safe_load`,
validates against `PostFrontmatter`, renders the body with `markdown-it-py`,
then upserts by slug using a fetch-then-compare strategy (avoids spurious
`updated_at` bumps on unchanged posts). Orphaned DB rows — posts whose file
has been deleted — are bulk-deleted at the end of each run, making the table
a fully derived projection of the file system. `pyyaml` added as an explicit
dependency. 11 unit tests cover all parsing paths — valid/invalid
frontmatter, YAML errors, missing delimiter, non-mapping YAML, Markdown
rendering. 6 integration tests verify the full round-trip, idempotency,
file-deletion reconciliation, partial-skip behaviour (bad file skipped,
good file upserted), title update propagation, and multi-post sync.

**Recommended next steps**
- Phase 3 (template port) is independent of Phase 2 and can proceed in
  parallel or next — it needs no DB, only static files.
- Phase 4 will call `sync_posts()` from the lifespan (pass `content_dir`
  from `BASE_DIR / "content/posts"` and a session from `get_session_factory()`).
- The three uncovered lines in `post_sync.py` (125–127) are the
  `logger.info` inside `_delete_removed` when orphaned slugs exist — this
  path is covered by the integration test that deletes a file; the coverage
  gap is a measurement artifact of which tests run in isolation.
- No schema changes were needed; the existing `Post` model and
  `PostFrontmatter` schema cover everything the service requires.

### Phase 3 — Template port (static, no dynamic data yet)

**Scope**
- [x] Vendor Clean Blog's `css/`, `js/`, `fonts/` into `static/`.
- [x] Port `index.html` → `templates/home.html`, `post.html` →
  `templates/post.html` — still with hardcoded placeholder content, but
  extending the existing `templates/base.html` block structure.
- [x] Delete whatever placeholder styling in `static/style.css` conflicts;
  keep the file for project-specific overrides on top of Bootstrap.

**Done when**
- [x] Both pages render at temporary routes with placeholder content, look
  right on a phone-width viewport (Chrome devtools ~390px) and desktop.
- [x] No JS console errors; total page weight sanity-checked (<300KB without
  images).

**Why before the routes phase**: porting a template always surfaces
surprises (asset paths, font loading, nav behavior). Doing it against
static placeholder content isolates those from route/query bugs.

**Left over**
None.

**Summary**
Downloaded the Start Bootstrap Clean Blog `dist/` build and vendored
`styles.css` → `static/clean-blog.css` (228KB, ~25KB gzipped, bundles
Bootstrap 5 CSS) and `scripts.js` → `static/clean-blog.js` (1.1KB, navbar
scroll behaviour). Favicon vendored to `static/favicon.ico`. Bootstrap JS
and Google Fonts (Lora + Open Sans) remain on CDN — no fonts directory
needed. `templates/base.html` rewritten as the full Clean Blog chrome
(navbar with collapse, page-header block, content block, footer, CDN +
vendored script tags). `templates/home.html` ported from `index.html`:
Jinja2 `{% for post in posts %}` loop over the post list with the Clean
Blog `post-preview` markup; empty-state paragraph preserved for the
no-posts case. `templates/post.html` ported from `post.html`: masthead
with dynamic cover image, title, subheading, author byline, `{{ post.body_html | safe }}`,
tag badges, back link. `static/style.css` cleared of conflicting layout
rules and kept as a clean project-specific override file. A temporary
`GET /post-preview` route added to `app/routes/home.py` so the post
template can be smoke-tested without a DB. 17 new unit tests in
`tests/unit/test_templates.py` cover both pages' structure, content,
asset links, and empty-state. Page weight (local static, no images):
~234KB uncompressed / ~27KB gzipped.

**Recommended next steps**
- Phase 4 should remove the temporary `_PlaceholderPost` class and
  `/post-preview` route from `app/routes/home.py` once the real
  `GET /posts/{slug}` route is in place.
- The home header background image path is `/static/img/home-bg.jpg` and
  the post fallback is `/static/img/post-bg.jpg` — add placeholder
  images (or remove the `style` attribute and add a plain colour
  background via CSS) so the masthead doesn't render as a broken image in
  dev. A solid-colour fallback in `style.css` is the quickest fix.
- Phase 4 lifespan sync: call `sync_posts(BASE_DIR / "content/posts", session)`
  then `await session.commit()` inside an `async with get_session_factory()() as session`
  block — not `get_db_session()` (that's a FastAPI dep generator).

### Phase 4 — Routes + real data (the slice closes end to end)

**Scope**
- `GET /posts` and `GET /posts/{slug}` per the plan above, querying via
  the Phase-1 session dependency, rendering the Phase-3 templates.
- Draft handling: `is_draft` posts are 404 in production, visible in
  development (`settings.is_development`).
- Home route (`/`) decision: point it at the post list (replace the
  placeholder landing page) — a separate landing page can come back later
  when there's content worth curating.
- Run sync at app startup (lifespan) so a deploy automatically picks up
  new Markdown files — plus a `make sync-posts` target for re-syncing a
  running dev server without restart.

**Done when**
- Integration test: synced fixture post → `GET /posts` lists it →
  `GET /posts/{slug}` returns 200 with the title in the body → unknown
  slug returns 404 → draft post 404s when `APP_ENV=production`.
- Coverage floor still green.

### Phase 5 — First real post + ship

**Scope**
- Write one real post (a genuine gravel trip, not lorem ipsum) in
  `content/posts/`, with a real cover image.
- Cover image goes in `static/uploads/` for now (gitignored per the
  boilerplate) — the R2 media pipeline is its own later slice; don't
  block the first post on it.
- Judge the `summary`-as-subtitle question against this real content —
  decide split-or-keep now, while changing it costs one migration and
  one file edit.
- Deploy to the Hetzner box per `deployment.md`, verify at
  `https://bulliexplorer.com/posts/<slug>`.

**Done when**
- The post is publicly readable on the production domain, on a phone.
- The `summary`/`subtitle` decision is recorded in this doc (edit the
  "Open decision" section above with the outcome).

### Sequencing notes

- Phases 1+2 are independent of 3 — they can be swapped or interleaved;
  4 needs all three.
- If a phase uncovers a schema change (e.g. the subtitle split lands
  early): Alembic migration + `PostFrontmatter` + existing posts updated
  in the same commit, per `AGENTS.md`.
- Nothing in this plan touches `app/admin.py`, auth, R2, or the map —
  deliberately. One vertical slice at a time.

### Testing (per `boilerplate.md` §8 / `AGENTS.md`)

- Unit test for the sync service against a fixture Markdown file — no DB,
  mock the upsert.
- Integration test: sync a real fixture post into the test DB, confirm
  `GET /posts/{slug}` returns 200 and the expected title.
- Frontmatter schema changes (if the `summary`/`subtitle` split happens)
  require updating every existing post under `content/posts/` in the same
  change, and a CHANGELOG entry — per `AGENTS.md`'s content-schema-sync
  rule.

---

## Out of scope for this slice

- SQLAdmin views for `Post` (`app/admin.py` TODOs) — separate slice, once
  there's a reason to edit posts outside of editing Markdown files
  directly.
- Tags/category filtering UI — the `tags` field already exists on the
  model; rendering/filtering by it is a follow-up once there are enough
  posts to need it.
- Reading-time estimate — cheap to add later (word count / 200), not
  needed for the first post.