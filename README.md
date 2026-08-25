# BulliExplorer

<!-- Replace MONITOR_API_KEY with your UptimeRobot monitor-specific API key -->
<!-- (My Monitors → gear icon → Monitor-Specific API Key) -->
[![Uptime Robot status](https://img.shields.io/uptimerobot/status/MONITOR_API_KEY)](https://bulliexplorer.com)

A gravel & adventure blog with interactive maps, campsites, routes, and GPX tracks.

Server-rendered with **FastAPI + Jinja2 + HTMX** — no client-side build step, no npm.
Geo data backed by **PostgreSQL/PostGIS** via SQLAlchemy + GeoAlchemy2.
Blog posts authored as **Markdown** with Pydantic-validated frontmatter.

## Stack

| Layer | Tech |
|---|---|
| Runtime | Python 3.13, managed with [uv](https://docs.astral.sh/uv/) |
| Web | FastAPI, Jinja2, HTMX, Alpine.js |
| Maps | MapLibre GL JS |
| Database | PostgreSQL + PostGIS (SQLAlchemy, GeoAlchemy2, Alembic) |
| Blog content | Markdown files (`content/posts/`), rendered via markdown-it-py |
| Admin | SQLAdmin + fastapi-users (2FA) |
| Media | Cloudflare R2 (S3-compatible) via boto3 |
| Hosting | Hetzner CX23, Docker Compose, Caddy (auto TLS) |

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

The app will be running at `http://localhost:8000`. Health check at `/health`.

### Install pre-commit hooks

```bash
uv run pre-commit install
```

## Project structure

```
bulliexplorer/
├── app/
│   ├── main.py              # create_app() factory + lifespan
│   ├── core/
│   │   └── config.py        # pydantic-settings
│   ├── models/              # SQLAlchemy + GeoAlchemy2 models
│   │   ├── base.py          # shared DeclarativeBase
│   │   ├── campsite.py      # PostGIS Point
│   │   ├── route.py         # PostGIS LineString (GPX tracks)
│   │   ├── post.py          # blog posts
│   │   └── post_schema.py   # Pydantic frontmatter validation
│   ├── services/            # business logic (no framework imports)
│   ├── routes/              # FastAPI routers
│   ├── admin.py             # SQLAdmin views
│   └── utils/
│       └── log_factory.py   # centralised logging
├── templates/               # Jinja2 server-rendered HTML
│   ├── base.html
│   └── partials/            # HTMX fragment responses
├── static/                  # vendored JS/CSS (htmx, alpine, maplibre)
├── content/
│   └── posts/               # Markdown blog posts with YAML frontmatter
├── tests/
│   ├── unit/                # no DB required
│   └── integration/         # needs PostGIS container
├── alembic/                 # database migrations
├── pyproject.toml
├── uv.lock                  # committed — reproducible installs
├── Makefile
├── docker-compose.yml       # local dev: PostGIS
└── .pre-commit-config.yaml
```

**Key conventions:**

- `app/services/` is framework-free — no FastAPI, Jinja2, or SQLAdmin imports. Business logic stays testable without spinning up the web layer.
- `Path(__file__)`-anchored paths everywhere — no relative-path fragility.
- No JS build step. HTMX, Alpine.js, and MapLibre GL JS are vendored `<script>` tags in `static/`.

## Make targets

```bash
make dev          # uvicorn with --reload
make lint         # ruff format --check + ruff check + pyright
make format       # ruff format + ruff check --fix (mutating)
make test         # pytest (coverage floor: 60%)
make security     # bandit + detect-secrets + pip-audit
make db-upgrade   # alembic upgrade head
make db-revision m="description"  # autogenerate a migration
make ci           # lint + test + security (run before pushing)
make clean        # remove __pycache__, .pytest_cache, htmlcov
```

## Configuration

All config flows through `app/core/config.py` (pydantic-settings). Copy `.env.example` to `.env` for local overrides:

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development` / `production` |
| `DEBUG` | `false` | Debug mode |
| `LOG_JSON` | `false` | JSON log output (enable on server) |
| `DATABASE_URL` | `postgresql+psycopg://…` | PostGIS connection string |
| `SECRET_KEY` | — | Auth secret (change in production) |
| `S3_ENDPOINT_URL` | — | Cloudflare R2 endpoint |
| `S3_ACCESS_KEY` | — | R2 access key |
| `S3_SECRET_KEY` | — | R2 secret key |
| `S3_BUCKET` | `bulliexplorer` | R2 bucket name |
| `SENTRY_DSN` | `""` (disabled) | Sentry error tracking DSN |

## Blog posts

Posts live as Markdown files in `content/posts/` with YAML frontmatter:

```markdown
---
title: First Gravel Ride
slug: first-gravel-ride
date: 2025-06-01
summary: Opening day on the new bike.
tags:
  - gravel
  - alps
cover_image: /static/uploads/first-ride.jpg
draft: false
---

Post body in Markdown here…
```

Frontmatter is validated against `app/models/post_schema.py`. If the schema changes, **all existing posts must be updated to match** — see `AGENTS.md` for the full contract.

## Testing

```bash
make test
```

- **Unit tests** (`tests/unit/`) — no database, no external services.
- **Integration tests** (`tests/integration/`) — require the local PostGIS container (`docker compose up -d`).
- Coverage floor is 60% (enforced via pytest-cov, raise as the project matures).
- Changes to PostGIS models (`campsite.py`, `route.py`) require an integration test that round-trips geometry through the database.

## Security

Day-1 baseline — not optional:

- Pre-commit hooks: ruff, bandit, detect-secrets
- `pip-audit` for CVE scanning
- 2FA on `/admin` (fastapi-users)
- Security-headers middleware (CSP, X-Frame-Options, X-Content-Type-Options)
- SSH key-only access, fail2ban, ufw on the server
- GitHub Dependabot enabled

Run the full security check:

```bash
make security
```

## License

Private — all rights reserved.
