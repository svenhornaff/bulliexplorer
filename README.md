# BulliExplorer

[![Uptime Robot status](https://img.shields.io/uptimerobot/status/m800000000000000-0000000000000000000000000)](https://bulliexplorer.com/health)
<!-- ^ Replace with your real UptimeRobot monitor-specific API key:
     My Monitors → monitor → gear icon → Monitor-Specific API Key -->

A gravel & adventure blog with interactive maps, points of interest, and GPX
routes. Server-rendered with **FastAPI + Jinja2 + HTMX** — no client-side
build step, no npm. Content is authored through a browser-based CMS and
publishes automatically via a GitHub webhook — no SSH required for day-to-day
posting.

## Stack

| Layer | Tech |
|---|---|
| Runtime | Python 3.13, managed with [uv](https://docs.astral.sh/uv/) |
| Web | FastAPI, Jinja2, HTMX, Alpine.js |
| Maps | MapLibre GL JS |
| Database | PostgreSQL + PostGIS (SQLAlchemy, GeoAlchemy2, Alembic) |
| Blog content | Markdown files (`content/posts/`), rendered via markdown-it-py |
| Content editing | [Sveltia CMS](https://github.com/sveltia/sveltia-cms) at `/editor/` — GitHub-backed, PAT auth, no separate backend |
| Auto-publish | GitHub webhook → `/internal/webhook/github` → fetches via GitHub API, syncs, live within seconds of a Sveltia save |
| Geo data | `PointOfInterest` (campsites, restaurants, hotels, etc. via a `category` field) + `Route` (GPX tracks), both owned by their post |
| Admin (planned, not yet built) | `app/admin.py` — SQLAdmin + fastapi-users (2FA), currently stub |
| Media | Local `static/uploads/`, git-committed (R2 migration planned, not yet done) |
| Monitoring | UptimeRobot (`/health`) + Sentry (error tracking, opt-in via `SENTRY_DSN`) |
| CI | GitHub Actions (`.github/workflows/ci.yml`) — lint/test/security on every push |
| Dependency updates | Dependabot (`.github/dependabot.yml`, `uv` ecosystem, weekly) |
| Hosting | Hetzner CX23, Docker Compose, Caddy (auto TLS) |

**Note on the Admin row:** SQLAdmin was the original plan for entering geo
data directly. That was superseded — points of interest and routes are now
authored *through Sveltia, alongside their post* (see `docs/dev/maps_gis.md`
for why). `app/admin.py` still exists as a stub for possible future use, but
nothing in the current architecture depends on it shipping.

## Quick start

### Prerequisites

- [uv](https://docs.astral.sh/uv/) installed (`brew install uv`)
- Docker (for local Postgres/PostGIS)

### Setup

```bash
git clone <repo-url> && cd bulliexplorer

# Install everything — creates .venv, installs all deps from lockfile
uv sync

# Start local PostGIS database
docker compose up -d

# Copy env template and edit as needed
cp .env.example .env

# Run database migrations
make db-upgrade

# Start the dev server
make dev
```

The app runs at `http://localhost:8000`. Health check at `/health`.

### Install pre-commit hooks

```bash
uv run pre-commit install
```

## Publishing content

**Day-to-day posting doesn't need a terminal.** Open `https://bulliexplorer.com/editor/`,
sign in with a GitHub personal access token (fine-grained, scoped to this
repo only, `Contents: Read and write`), and write. Saving commits directly
to `develop`; a GitHub webhook fires, the server fetches the change via the
GitHub API, and it's live within seconds. See `docs/dev/editor_cms.md` for
the full design and `docs/dev/maps_gis.md` for how routes/points of interest
attach to a post through the same editor.

**Code changes** are a separate path — `make deploy` (rsync-based, see
`docs/dev/deployment.md`). The two are intentionally decoupled: publishing a
post never triggers a code deploy, and deploying code never touches content.

## Project structure

```
bulliexplorer/
├── app/
│   ├── main.py               # create_app() factory + lifespan
│   ├── core/
│   │   ├── config.py         # pydantic-settings
│   │   └── db.py             # async engine + session factory
│   ├── models/                # SQLAlchemy + GeoAlchemy2 models
│   │   ├── base.py            # shared DeclarativeBase
│   │   ├── post.py            # blog posts
│   │   ├── post_schema.py     # Pydantic frontmatter validation
│   │   ├── point_of_interest.py  # PostGIS Point — campsites, restaurants, etc.
│   │   └── route.py           # PostGIS LineString (GPX tracks) + ride stats
│   ├── services/               # business logic (no framework imports)
│   │   ├── post_sync.py        # Markdown → DB sync
│   │   ├── github_sync.py      # webhook-triggered GitHub API fetch
│   │   └── geo_sync.py         # GPX parsing, POI geocoding
│   ├── routes/                 # FastAPI routers
│   │   ├── home.py
│   │   ├── posts.py
│   │   └── internal.py         # /internal/resync, /internal/webhook/github
│   ├── admin.py                 # SQLAdmin views — stub, see note above
│   └── utils/
│       └── log_factory.py       # centralised logging
├── templates/                    # Jinja2 server-rendered HTML
├── static/
│   ├── editor/                   # Sveltia CMS (config.yml, index.html)
│   └── uploads/                  # user-uploaded media, git-committed
├── content/
│   └── posts/                    # Markdown blog posts with YAML frontmatter
├── tests/
│   ├── unit/                     # no DB required
│   └── integration/               # needs PostGIS container
├── alembic/                       # database migrations
├── .github/
│   ├── workflows/ci.yml           # lint/test/security on every push
│   └── dependabot.yml             # weekly uv-ecosystem dependency updates
├── pyproject.toml
├── uv.lock                        # committed — reproducible installs
├── Makefile
├── docker-compose.yml              # local dev: PostGIS
├── docker-compose.prod.yml         # production: app + PostGIS + Caddy
└── .pre-commit-config.yaml
```

**Key conventions:**

- `app/services/` is framework-free — no FastAPI, Jinja2, or SQLAdmin imports. Business logic stays testable without spinning up the web layer.
- `Path(__file__)`-anchored paths everywhere — no relative-path fragility.
- No JS build step. HTMX, Alpine.js, MapLibre GL JS, and the Sveltia CMS bundle are all vendored `<script>` tags — nothing here runs through npm.

## Make targets

```bash
make dev          # uvicorn with --reload
make lint         # ruff format --check + ruff check + pyright
make format       # ruff format + ruff check --fix (mutating)
make test         # pytest (coverage floor: 60%)
make security     # bandit + detect-secrets + pip-audit
make db-upgrade   # alembic upgrade head
make db-revision m="description"  # autogenerate a migration
make ci           # lint + test + security (also runs automatically on every push via GitHub Actions)
make deploy       # rsync-based code deploy (does not touch content)
make clean        # remove __pycache__, .pytest_cache, htmlcov
```

## Configuration

All config flows through `app/core/config.py` (pydantic-settings). Copy
`.env.example` to `.env` for local overrides. Fields with no default are
required — the app fails to start rather than silently running with a
placeholder (see `AGENTS.md`'s "no working defaults for secrets" rule).

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development` / `production` |
| `DEBUG` | `false` | Debug mode |
| `LOG_JSON` | `false` | JSON log output (enable on server) |
| `DATABASE_URL` | `postgresql+psycopg://…` | PostGIS connection string |
| `SECRET_KEY` | *required* | Auth secret — no default, fails loud if unset |
| `RESYNC_TOKEN` | *required* | Shared-secret header for `POST /internal/resync` |
| `GITHUB_TOKEN` | *required* | PAT used by Sveltia and by the webhook's GitHub API fetch |
| `WEBHOOK_SECRET` | *required* | HMAC secret for verifying `POST /internal/webhook/github` (GitHub generates this when you register the webhook) |
| `S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | `""` | Cloudflare R2 (not yet wired up — provisioned for later) |
| `S3_BUCKET` | `bulliexplorer` | R2 bucket name |
| `SENTRY_DSN` | `""` (disabled) | Sentry error tracking — deliberately *not* required; a missing DSN must never crash the app, see `docs/dev/monitoring_ops.md` |

## Blog posts

Posts live as Markdown files in `content/posts/` with YAML frontmatter:

```markdown
---
title: First Gravel Ride
slug: first-gravel-ride
published_date: 2025-06-01
summary: Opening day on the new bike.
tags:
  - gravel
  - alps
cover_image: /static/uploads/first-ride.jpg
is_draft: false
---

Post body in Markdown here…
```

Frontmatter is validated against `app/models/post_schema.py`. If the schema
changes, **all existing posts must be updated to match** — see `AGENTS.md`
for the full contract. Optional `route` and `points_of_interest` fields
attach a GPX track and/or geo-tagged points to a post — see
`docs/dev/maps_gis.md` for the full authoring workflow.

## Testing

```bash
make test
```

- **Unit tests** (`tests/unit/`) — no database, no external services.
- **Integration tests** (`tests/integration/`) — require the local PostGIS container (`docker compose up -d`).
- Coverage floor is 60% (enforced via pytest-cov, raise as the project matures).
- Changes to PostGIS models (`point_of_interest.py`, `route.py`) require an integration test that round-trips geometry through the database.

## Security

Day-1 baseline — not optional:

- Pre-commit hooks: ruff, bandit, detect-secrets
- `pip-audit` for CVE scanning, GitHub Dependabot for known-vulnerable dependencies
- HMAC-verified webhook endpoint (`/internal/webhook/github`), shared-secret-gated resync endpoint
- Security-headers middleware (CSP, X-Frame-Options, X-Content-Type-Options)
- SSH key-only access, fail2ban, ufw on the server
- No secret ever has a working default — missing config fails loudly at startup, not silently

Run the full security check:

```bash
make security
```

## Monitoring & ops

- **UptimeRobot** checks `/health` every 5 minutes — has already caught two real production incidents during development.
- **Sentry** captures unhandled exceptions when `SENTRY_DSN` is set; expected 404s are filtered out so they don't count as errors.
- **GitHub Actions** runs the full `make ci` suite on every push to `develop`.
- Backup automation is intentionally not yet built — see `docs/dev/monitoring_ops.md` for why, and what triggers it becoming urgent.

## Documentation

Deeper design docs, decision history, and phased implementation plans live
in `docs/dev/`:

| Doc | Covers |
|---|---|
| `bulliexplorer_stack_concept.md` | Original architecture decisions and Hetzner setup |
| `boilerplate.md` | Local dev tooling and conventions (this README's companion) |
| `post_and_backend.md` | The blog-post vertical slice: DB, sync service, routes, templates |
| `editor_cms.md` | Sveltia CMS integration, PAT auth, webhook auto-publish |
| `maps_gis.md` | Points of interest, GPX routes, geocoding, ride stats |
| `monitoring_ops.md` | Monitoring, Dependabot, backups, CI/CD — priority and reasoning |
| `deployment.md` | Server setup, hardening, deploy process |
| `buckets.md` | Current outstanding work, sized and prioritized |

`AGENTS.md` (repo root) has the rules a coding agent — or future you — should follow before touching this codebase.

## License

Private — all rights reserved.