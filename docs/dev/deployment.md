# BulliExplorer — Deployment Guide

> Deploy the app from the local dev machine to the Hetzner CX23 box.
> Single-server Docker Compose stack: **FastAPI app + PostGIS + Caddy**.
> Domain: `bulliexplorer.com` (Route 53 on AWS).

---

## Two separate publish paths — don't conflate them

**Content** (blog posts, images, routes/POIs) publishes via Sveltia CMS
(`/editor/`) → GitHub webhook → automatic sync. No SSH, no rsync, no
`make deploy`. See `docs/dev/editor_cms.md` for the full design.

**Code** (anything in `app/`, templates, config) deploys via `make deploy`
(rsync-based) as described below. This never touches content, and
publishing content never triggers a code deploy — the two are intentionally
decoupled.

Everything from here on in this document is the *code* deploy path.

## 0. Architecture overview

```
                 ┌─────────────────┐
                 │   Cloudflare    │  ← optional later (WAF/CDN, free tier)
                 │   (DNS proxy)   │
                 └────────┬────────┘
                          │
         ┌────────────────▼──────────────────┐
         │       Hetzner CX23                │
         │       62.238.122.200              │
         │                                   │
         │  ┌────────────┐  ┌─────────────┐  │
         │  │  Caddy     │  │  PostGIS    │  │
         │  │  :80/:443  │  │  :5432      │  │
         │  │  (TLS)     │  │  (internal) │  │
         │  └─────┬──────┘  └──────▲──────┘  │
         │        │                │         │
         │        ▼                │         │
         │    ┌──────────────────────┐       │
         │    │  FastAPI (uvicorn)   |       │
         │    │  :8000 (internal)    |       │
         │    └──────────────────────┘       │
         └───────────────────────────────────┘
```

- **Caddy** handles TLS (automatic Let's Encrypt), reverse-proxies to the app.
- **PostGIS** is internal only — no exposed port.
- **App** runs as a non-root user inside the container.
- All three services managed by a single `docker-compose.prod.yml`.

---

## 1. DNS — Route 53

Point the domain to the Hetzner server **before** deploying (Caddy needs DNS
to resolve for Let's Encrypt).

### In the AWS Route 53 console

Go to the hosted zone for `bulliexplorer.com` and create/update:

| Record | Type | Value | TTL |
| --- | --- | --- | --- |
| `bulliexplorer.com` | A | `62.238.122.200` | 300 |
| `www.bulliexplorer.com` | CNAME | `bulliexplorer.com` | 300 |

Optionally add the IPv6 AAAA record:

| Record | Type | Value | TTL |
|---|---|---|---|
| `bulliexplorer.com` | AAAA | `2a01:4f9:c014:2dd5::1` | 300 |

### Verify propagation

```bash
dig +short bulliexplorer.com A
# should return: 62.238.122.200
```

---

## 2. Server hardening (one-time)

The server is Ubuntu 26.04, Docker 29.x installed, user `brooklyn` exists.
Some hardening steps from the tech concept doc are still pending:

```bash
# SSH into the server
ssh -i ~/.ssh/bulliexplorer_hetzner root@62.238.122.200

# 1. Lock down SSH — disable root login + password auth
#
# NOTE: the previous version of this used `sed -i 's/^#PermitRootLogin.*/.../'`,
# which only fires if a line starting with exactly "#PermitRootLogin" already
# exists to match against. On a config that doesn't have that exact commented
# line (common — this bit us live during initial setup), the sed silently
# does nothing and exits 0: no error, no change, false sense of security.
# grep -q + conditional append guarantees the setting lands regardless of
# the file's starting state:
grep -q '^PermitRootLogin no' /etc/ssh/sshd_config || echo 'PermitRootLogin no' >> /etc/ssh/sshd_config
grep -q '^PasswordAuthentication no' /etc/ssh/sshd_config || echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config
systemctl restart sshd
# Verify before trusting it — sshd -t validates syntax, sshd -T dumps the
# effective config so you can confirm the setting actually took:
sshd -t && sshd -T | grep -i "permitrootlogin\|passwordauthentication

# ⚠️  BEFORE running the above, verify you can SSH as brooklyn:
#     ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200
#     If that doesn't work, set up the key first:
#     rsync --archive --chown=brooklyn:brooklyn ~/.ssh /home/brooklyn

# 2. Enable firewall
apt update && apt install -y ufw fail2ban
ufw allow OpenSSH
ufw allow 80,443/tcp
ufw --force enable

# 3. Add brooklyn to docker group (if not already)
usermod -aG docker brooklyn
```

After this, **all further commands run as `brooklyn`**, not root.

---

## 3. Project files on the server

### 3.1 Create the deployment directory

```bash
# As brooklyn on the server
ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200

mkdir -p ~/bulliexplorer
```

### 3.2 Files to deploy

Three files need to exist on the server (they are NOT the local dev files):

#### `docker-compose.prod.yml`

```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      - APP_ENV=production
      - LOG_JSON=true
      - DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@db:5432/bulliexplorer
      - SECRET_KEY=${SECRET_KEY}
      - S3_ENDPOINT_URL=${S3_ENDPOINT_URL:-}
      - S3_ACCESS_KEY=${S3_ACCESS_KEY:-}
      - S3_SECRET_KEY=${S3_SECRET_KEY:-}
      - S3_BUCKET=${S3_BUCKET:-bulliexplorer}
      - TILES_URL=${TILES_URL:-}
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    expose:
      - "8000"

  db:
    image: postgis/postgis:16-3.4
    restart: unless-stopped
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: bulliexplorer
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    # No ports exposed — only accessible from app and caddy network

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"   # HTTP/3
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config

volumes:
  pgdata:
  caddy_data:
  caddy_config:
```

#### `Caddyfile`

```
bulliexplorer.com {
    reverse_proxy app:8000

    header {
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "camera=(), microphone=(), geolocation=()"
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
    }
}

www.bulliexplorer.com {
    redir https://bulliexplorer.com{uri} permanent
}
```

#### `Dockerfile`

```dockerfile
# ── Builder ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source
COPY app/ app/
COPY templates/ templates/
COPY static/ static/
COPY content/ content/
COPY alembic/ alembic/
COPY alembic.ini ./

# Install the project itself
RUN uv sync --frozen --no-dev

# ── Runtime ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app app/
COPY --from=builder /app/templates templates/
COPY --from=builder /app/static static/
COPY --from=builder /app/content content/
COPY --from=builder /app/alembic alembic/
COPY --from=builder /app/alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

#### `.env` (on server only — never committed)

```bash
POSTGRES_PASSWORD=<generate-a-strong-password>
SECRET_KEY=<generate-a-strong-secret>
S3_ENDPOINT_URL=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET=bulliexplorer
TILES_URL=

# Public legal disclosure values — see docs/dev/legal_gdpr.md.
# LEGAL_CLASSIFICATION: "personal" or "commercial" — unset 503s /impressum and
# /datenschutz in production; see docs/dev/legal_gdpr_classification_refactor.md.
LEGAL_CLASSIFICATION=
# LEGAL_ADDRESS stays empty until a ladungsfaehige Anschrift is confirmed —
# /impressum and /datenschutz return 503 in production while any are unset.
LEGAL_NAME=
LEGAL_ADDRESS=
LEGAL_EMAIL=
LEGAL_HOSTING=
LEGAL_LOG_RETENTION=
LEGAL_CLOUDFLARE_DETAILS=
LEGAL_SENTRY_DETAILS=
```

Generate secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Credential rotation — a standing practice, not a one-time reaction

docs/dev/security_review_owasp.md Phase 4. Two written rules, so both
are an actual standard rather than tribal knowledge the next relevant
moment has to be reinvented from scratch:

1. **Rotation habit for long-lived static tokens.** `RESYNC_TOKEN`,
   `WEBHOOK_SECRET`, and `GITHUB_TOKEN` (all `.env`, never committed) have
   no expiry or rotation mechanism of their own — reasonable for a
   single-operator project at this scale, but that only holds if they're
   actually rotated on a schedule instead of "set once, forgotten."
   Rotate all three **annually**, or immediately after any suspected
   exposure (rule 2 below). Rotating means: generate a new value with the
   command above, update `.env` on the server, `docker compose -f
   docker-compose.prod.yml up -d` to pick it up, then update the matching
   value wherever it's used as a client (the GitHub repo's webhook
   settings for `WEBHOOK_SECRET`, whatever calls `/internal/resync` for
   `RESYNC_TOKEN`, the GitHub App/PAT settings for `GITHUB_TOKEN`).
2. **Any credential that ever touched a public repo's history is
   compromised — full stop, not "probably fine."** The concrete example:
   a GitHub PAT was briefly visible in a DevTools screenshot earlier in
   this project. The correct response to that class of event is always
   "rotate it," never "it probably wasn't seen." This applies to any
   future exposure of the same shape (a screenshot, a copy-pasted log
   line, a committed `.env`), not just that one incident.

Related, worth checking periodically rather than assuming:

- **HaveIBeenPwned** (haveibeenpwned.com) — check the operator's own
  email addresses directly, or set up its free monitoring for future
  breaches.
- **GitHub secret scanning** — confirm it's actually enabled on the repo
  (Settings → Code security) rather than assuming it is by default.

---

## 4. Deploy from local machine

### 4.1 First-time deploy

```bash
# 1. Copy deployment files to the server
scp -i ~/.ssh/bulliexplorer_hetzner \
    Dockerfile Caddyfile docker-compose.prod.yml \
    brooklyn@62.238.122.200:~/bulliexplorer/

# 2. Copy the full project source
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
    --exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='.coverage' \
    --exclude='htmlcov' --exclude='.env' --exclude='.pi' \
    -e "ssh -i ~/.ssh/bulliexplorer_hetzner" \
    ./ brooklyn@62.238.122.200:~/bulliexplorer/

# 3. SSH in and create the .env
ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200
cd ~/bulliexplorer
cat > .env << 'EOF'
POSTGRES_PASSWORD=<your-generated-password>
SECRET_KEY=<your-generated-secret>
EOF

# 4. Build and start
docker compose -f docker-compose.prod.yml up -d --build

# 5. Run database migrations
docker compose -f docker-compose.prod.yml exec app alembic upgrade head

# 6. Verify
curl -s http://localhost:8000/health   # from the server
curl -s https://bulliexplorer.com/health  # from anywhere (once DNS propagates)
```

### 4.2 Subsequent deploys

```bash
# From local machine — sync changes + rebuild
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
    --exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='.coverage' \
    --exclude='htmlcov' --exclude='.env' --exclude='.pi' \
    -e "ssh -i ~/.ssh/bulliexplorer_hetzner" \
    ./ brooklyn@62.238.122.200:~/bulliexplorer/

ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200 << 'DEPLOY'
cd ~/bulliexplorer
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec app alembic upgrade head
DEPLOY
```

### 4.3 Makefile targets (add to local Makefile)

```makefile
REMOTE := brooklyn@62.238.122.200
SSH_KEY := ~/.ssh/bulliexplorer_hetzner
SSH := ssh -i $(SSH_KEY)
RSYNC_EXCLUDE := --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
    --exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='.coverage' \
    --exclude='htmlcov' --exclude='.env' --exclude='.pi'

.PHONY: deploy
deploy: ci ## Deploy to production (runs ci first)
 rsync -avz $(RSYNC_EXCLUDE) -e "$(SSH)" ./ $(REMOTE):~/bulliexplorer/
 $(SSH) $(REMOTE) 'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml up -d --build && docker compose -f docker-compose.prod.yml exec app alembic upgrade head'

.PHONY: deploy-logs
deploy-logs: ## Tail production logs
 $(SSH) $(REMOTE) 'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml logs -f --tail=50'

.PHONY: deploy-status
deploy-status: ## Check production container status
 $(SSH) $(REMOTE) 'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml ps'

.PHONY: deploy-ssh
deploy-ssh: ## SSH into the server
 $(SSH) $(REMOTE)
```

---

## 5. Verify deployment

Once deployed and DNS has propagated:

```bash
# Health check
curl -s https://bulliexplorer.com/health
# → {"status":"ok"}

# TLS certificate
curl -vI https://bulliexplorer.com 2>&1 | grep -E 'subject:|issuer:|expire'

# Security headers
curl -sI https://bulliexplorer.com | grep -iE 'x-frame|x-content|strict-transport|referrer'

# Home page
curl -s https://bulliexplorer.com/ | head -20
```

---

## 6. Operations

### View logs

```bash
# All services
ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200 \
    'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml logs -f --tail=100'

# App only
ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200 \
    'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml logs -f app'
```

### Restart

```bash
ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200 \
    'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml restart app'
```

### Database shell

```bash
ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200 \
    'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml exec db psql -U postgres bulliexplorer'
```

### Database backups

Nightly `pg_dump` → Cloudflare R2, with 14-day retention — housekeeping
item from `docs/dev/review_17SEP2026.md` ("No DB backups"), full
scope/verification write-up in `docs/dev/monitoring_ops.md` Phase 4.
`scripts/backup_db.py` reuses the `s3_*` env vars/`boto3` dependency
already in place for media storage (`docs/dev/media_storage_r2.md`) —
no new secrets, no new dependency. A host crontab entry, not a new
docker-compose service ("small, no new services" per the review):

```bash
ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200
crontab -e
# Add:
0 3 * * * cd /home/brooklyn/bulliexplorer && /home/brooklyn/.local/bin/uv run python scripts/backup_db.py >> /var/log/bulliexplorer-backup.log 2>&1
```

Manual trigger (also what the cron entry runs) — from the server, in
the project directory:

```bash
make backup
```

Verify a backup landed:

```bash
ssh -i ~/.ssh/bulliexplorer_hetzner brooklyn@62.238.122.200 \
    'cd ~/bulliexplorer && uv run python -c "
from app.core.config import get_settings; import boto3
s = get_settings()
c = boto3.client(\"s3\", endpoint_url=s.s3_endpoint_url, aws_access_key_id=s.s3_access_key, aws_secret_access_key=s.s3_secret_key)
print([o[\"Key\"] for o in c.list_objects_v2(Bucket=s.s3_bucket, Prefix=\"backups/\").get(\"Contents\", [])])
"'
```

**Restore test — do this once before relying on the cron job**, into a
throwaway local Postgres, never against production:

```bash
# Pull one backup down, then locally:
gunzip -c backup-2026-XX-XX.sql.gz | docker compose exec -T db psql -U postgres bulliexplorer_restore_test
```

A backup that's never been restored isn't verified, it's just a file
that might be a backup.

### Rollback

```bash
# On the server
cd ~/bulliexplorer
docker compose -f docker-compose.prod.yml exec app alembic downgrade -1
```

---

## 7. Future improvements (not now)

| Improvement | When |
| --- | --- |
| **GitHub Actions CI/CD** | When manual `make deploy` gets tedious — auto-build image on push to `main`, deploy via SSH or Docker registry pull |
| **Docker registry (GHCR)** | Push built images to GitHub Container Registry instead of building on the server — faster deploys, smaller attack surface |
| **Cloudflare proxy** | Orange-cloud the DNS through Cloudflare for WAF/DDoS/edge caching — flip the switch in Route 53 or move nameservers |
| ~~**Automated backups**~~ | ✅ Done — see "Database backups" above (`scripts/backup_db.py` + host crontab, not a container). **Still outstanding**: the one-time restore test against a throwaway local Postgres, and confirming the cron entry is actually installed on the production host — neither could be done from this sandbox (no production SSH/R2 access here). |
| **UptimeRobot** | Monitor `https://bulliexplorer.com/health` — free tier, already planned |
| **Sentry** | Error tracking — add `sentry-sdk[fastapi]` once there's real traffic |
| **Zero-downtime deploys** | Blue-green or rolling update via Docker Compose profiles |

---

## 8. Quick-reference commands

```bash
# Deploy (from local)
make deploy

# SSH into server
make deploy-ssh

# Tail logs
make deploy-logs

# Check status
make deploy-status

# Manual deploy steps
rsync ... && ssh ... docker compose up -d --build

# Generate a secret
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Check DNS
dig +short bulliexplorer.com A
```
