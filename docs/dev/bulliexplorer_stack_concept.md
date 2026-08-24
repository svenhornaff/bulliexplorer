# BulliExplorer — Tech Concept v1

Solo-authored gravel/adventure blog with campsites, routes, and GPX tracks.
Domain: `bulliexplorer.com` (registered at AWS Route 53).

## Stack decision

Single-language Python stack. No separate frontend toolchain (no npm/TS
build step) — server-rendered HTML with HTMX for interactivity.

| Layer | Choice |
|---|---|
| Language/runtime | Python 3.13, managed with `uv` |
| Web framework | FastAPI |
| Templates | Jinja2 |
| Interactivity | HTMX + Alpine.js (script tags, no build step) |
| Geo/data | SQLAlchemy + GeoAlchemy2 + PostgreSQL/PostGIS |
| Interactive map | MapLibre GL JS |
| Blog content | Markdown files, rendered via `markdown-it-py`, frontmatter validated with Pydantic |
| Structured data admin | SQLAdmin (campsites, routes) + `fastapi-users` for auth/2FA |
| Search | Postgres full-text search |
| Media storage | Cloudflare R2 (S3-compatible, zero egress) via `boto3` |
| App server | Uvicorn/Gunicorn behind Caddy (automatic TLS) |
| Compute | Hetzner CX23, Docker Compose |
| CI/CD | GitHub Actions → build image → deploy |
| DNS | Route 53 (domain stays at AWS; A record points to Hetzner) |

**Security baseline (day 1):** 2FA + rate-limiting on admin, SSH key-only +
fail2ban, ufw firewall, automated Postgres backups to R2 (tested restore),
security headers/HSTS, Dependabot, Sentry (errors), UptimeRobot, Cloudflare
in front (WAF/CDN, free tier).

**Explicitly deferred:** Prometheus/Grafana/Loki, secrets manager, log
aggregation — revisit only if traffic or team size grows.

---

## Getting started: project setup with `uv`

```bash
# install uv (one-time, macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# scaffold the project
uv init bulliexplorer --python 3.13
cd bulliexplorer

# core dependencies
uv add fastapi uvicorn[standard] jinja2 python-multipart
uv add sqlalchemy geoalchemy2 psycopg[binary] alembic
uv add sqladmin fastapi-users[sqlalchemy]
uv add markdown-it-py pydantic boto3 python-dotenv

# dev-only dependencies
uv add --dev pytest httpx ruff
```

`uv run uvicorn app.main:app --reload` starts local dev. `uv.lock` gets
committed — reproducible installs on the server, no separate venv
management.

### Local Postgres/PostGIS (docker-compose, dev only)

```yaml
services:
  db:
    image: postgis/postgis:17-3.5
    environment:
      POSTGRES_DB: bulliexplorer
      POSTGRES_USER: dev
      POSTGRES_PASSWORD: dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

---

## Getting started: Hetzner

### Provisioned so far

| Item | Value | Status |
|---|---|---|
| Server type | CX23 — 2 vCPU / 4GB RAM / 40GB SSD (Cost-Optimized tier) | ✅ done |
| Location | Selected Nuremberg at creation | ⚠️ verify — hostname shows `hel1` (Helsinki); check console, may have provisioned in the wrong region |
| OS image | Ubuntu 26.04 LTS | ✅ done |
| Price | ~€7.13/mo (€6.53 server + €0.60 IPv4) | ✅ |
| Public IP | `62.238.122.200` (IPv4), `2a01:4f9:c014:2dd5::1` (IPv6) | ✅ |
| SSH key | `~/.ssh/bulliexplorer_hetzner` (ed25519), attached at creation | ✅ done |
| Hetzner Cloud Firewall | Inbound TCP 22/80/443 (Any IPv4/IPv6) + ICMP, outbound unrestricted, applied to server | ✅ done |
| Backups (Hetzner add-on) | Not enabled | Intentionally skipped — using `pg_dump` → R2 instead |

### Server hardening — in progress

```bash
# as root, first login
adduser sven                                   # ✅ done — password set for local sudo only
usermod -aG sudo sven                          # ✅ done
rsync --archive --chown=sven:sven ~/.ssh /home/sven   # ✅ done — key copied to sven
```

Still to do, in order:

```bash
# 1. confirm sven can log in via key BEFORE touching sshd_config
ssh -i ~/.ssh/bulliexplorer_hetzner sven@62.238.122.200

# 2. only once that works — edit /etc/ssh/sshd_config:
#      PermitRootLogin no
#      PasswordAuthentication no
sudo systemctl restart sshd

# 3. ufw — network-level rules already exist via the Hetzner Cloud
#    Firewall (22/80/443); this is the host-level second layer
sudo apt install -y ufw fail2ban
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

### Shell setup on the box — done

- `apt update` run, `apt upgrade -y` pending/recommended on first login
- `git` installed
- Colored bash prompt (green user@host, blue path, yellow git branch when
  inside a repo) + `gacp` helper appended to `~/.bash_aliases` — no zsh,
  kept the existing Debian `.bashrc` as-is (its `ls`/`grep` coloring
  already worked; only `PS1` needed a manual override since the stock
  `case "$TERM"` check doesn't match modern terminals)

### Still ahead

1. **Install Docker**
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker sven
   ```

2. **Point DNS** — Route 53 → hosted zone for `bulliexplorer.com` → A
   record → `62.238.122.200` (AAAA → the IPv6 above, optional).

3. **Deploy stack** — `docker-compose.yml` on the server: FastAPI app
   container + Postgres/PostGIS container + Caddy (reverse proxy,
   automatic Let's Encrypt TLS from a two-line `Caddyfile`):
   ```
   bulliexplorer.com {
       reverse_proxy app:8000
   }
   ```
   ```bash
   docker compose up -d
   ```

4. **Backups** — cron job (or small container) running `pg_dump` nightly,
   pushed to Cloudflare R2 via `boto3`/`aws s3 cp`. Test a restore once
   before relying on it.

5. **Cloudflare in front** — free tier, proxy `bulliexplorer.com` through
   Cloudflare (orange-cloud DNS) for WAF/DDoS protection and edge caching,
   Caddy still handles origin TLS.

---

## Open items for v2 of this concept

- RSS feed + sitemap generation (manual — no Astro integration to lean on)
- Image pipeline (Pillow-based resize/WebP conversion on upload)
- GPX import/parsing workflow into PostGIS `LineStringField`