# AGENTS.md — bulliexplorer

## Project overview

Solo-authored gravel/adventure blog. FastAPI + Jinja2 + HTMX + Alpine.js —
server-rendered HTML, no client-side build step, no npm. SQLAlchemy +
GeoAlchemy2 + PostgreSQL/PostGIS for campsites/routes. Markdown files for
blog post content. `uv` for all Python tooling.

Architecture and hosting decisions live in `bulliexplorer-tech-concept.md`;
dev-environment conventions live in `bulliexplorer-boilerplate.md`. This
file is agent-facing instructions only — don't duplicate either doc here,
link to them.

## Setup

```bash
uv sync
```

That's the only setup command. Requires local Postgres/PostGIS —
`docker compose up -d` (uses the `db` service in `docker-compose.yml`) —
before running migrations or integration tests.

## Commands

Run from the project root:

```bash
make dev          # uv run uvicorn app.main:app --reload
make lint         # ruff format --check + ruff check + pyright
make format       # ruff format + ruff check --fix (mutating)
make test         # pytest, coverage floor enforced via pyproject addopts
make security      # bandit + detect-secrets + pip-audit
make db-upgrade    # alembic upgrade head
make ci            # lint + test + security — run before considering any change done
```

## Code style

- `tsc`-equivalent gate here is `pyright` (basic mode) — must be clean.
- `ruff check` must be clean; `ruff format` is the formatter, don't
  hand-format.
- No new dependencies without a concrete need — check `pyproject.toml`'s
  existing set before adding one that overlaps (e.g. don't add `pillow`'s
  image logic redundantly if a util already wraps it).
- `app/services/` stays framework-free — no `fastapi`, `jinja2`, or `sqladmin`
  imports there. Routes and admin views are a thin layer on top of services,
  not where business logic lives.
- **No JS build step, ever.** HTMX/Alpine/MapLibre are vendored script tags
  in `static/`, not npm packages. If a task seems to need `npm install`,
  `vite`, or a bundler, stop — that's the wrong direction for this project;
  flag it instead of adding it.
- **No working defaults for secrets.** Settings like `secret_key` must have
  no default value — missing config should crash on startup, not silently
  run with a placeholder. If bandit flags a hardcoded secret, fix the
  default; don't suppress the warning.
- **Logging: always lazy `%`-style args** (`logger.info("x=%d", x)`), never
  f-strings inside a log call (`logger.info(f"x={x}")`) — the former skips
  string formatting entirely when the log level filters the line out, the
  latter always pays the cost. Already the convention throughout the
  codebase — keep it that way as it grows.
- **`# noqa` always pairs a specific code with a one-line reason** —
  `# noqa: S101 — guaranteed by init_engine()`, not a bare `# noqa` or a
  code with no explanation. Nearly every suppression in the codebase
  already does this correctly; the one exception (`config.py`'s old
  `secret_key` line) is the bug above, not a style to follow.
- **Public functions get a NumPy-style docstring** (summary line, then
  `Parameters`/`Returns` sections for anything non-trivial) — matches
  `post_sync.py` and `db.py` already. Internal `_prefixed` helpers can stay
  terser.

## Testing

- `tests/unit/` — no DB, tests `services/` directly.
- `tests/integration/` — needs the local Postgres/PostGIS container.
- New or changed behavior needs a test in the same change.
- Tests must pass with no external API keys or R2 credentials in the
  environment — mock `boto3`/S3 calls, don't hit real R2 in tests.
- Any change touching `models/route.py` or `models/campsite.py` (the
  PostGIS-backed models) needs at least one integration test that
  round-trips the geometry through the DB — this is the part of the stack
  most likely to break silently on a schema or query change.

## Content schema — keep it in sync

Blog post frontmatter (`content/posts/*.md`) is validated against a Pydantic
schema. If a change adds, removes, or renames a frontmatter field:

- Update the Pydantic schema in the same change.
- Update every existing post under `content/posts/` to match — don't leave
  posts that will fail validation on next build.
- Note the schema change in `CHANGELOG.md` if one exists yet, or start one
  once this happens for the first time.

## Security baseline — don't relax without saying so

The day-1 security baseline (2FA on `/admin`, security-headers middleware,
`/health` endpoint gated correctly, no secrets in `.env` committed) is
intentional, documented in the tech concept doc. Don't remove or weaken any
of it as a side effect of an unrelated change — if a task seems to require
that, stop and flag it rather than proceeding.

## PR / change checklist

1. Code change made.
2. `make ci` green.
3. If `content/posts/*.md` frontmatter schema changed — see above, synced.
4. If a PostGIS model changed — integration test added/updated.
5. New/changed behavior has a test that doesn't depend on ambient secrets.

## Rules

1. Never work outside this project's own directory — no scratch files in
   `/tmp` or elsewhere; if a scratch file is needed, put it in a gitignored
   path inside the project root.
2. Don't add compliance/audit tooling (SBOM generation, license gates,
   `semgrep`, `radon`) — deliberately out of scope for this project, see
   `bulliexplorer-boilerplate.md` §5 for why.