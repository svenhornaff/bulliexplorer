# BulliExplorer — Deployment Guide

> Deploy the app from the local dev machine to the Hetzner CX23 box.
> Single-server Docker Compose stack: **FastAPI app + PostGIS + Caddy**.
> Domain: `bulliexplorer.com` (Route 53 on AWS).

---

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
|---|---|---|---|
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
sed -i 's/^#PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

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
```

Generate secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

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

### Rollback

```bash
# On the server
cd ~/bulliexplorer
docker compose -f docker-compose.prod.yml exec app alembic downgrade -1
```

---

## 7. Future improvements (not now)

| Improvement | When |
|---|---|
| **GitHub Actions CI/CD** | When manual `make deploy` gets tedious — auto-build image on push to `main`, deploy via SSH or Docker registry pull |
| **Docker registry (GHCR)** | Push built images to GitHub Container Registry instead of building on the server — faster deploys, smaller attack surface |
| **Cloudflare proxy** | Orange-cloud the DNS through Cloudflare for WAF/DDoS/edge caching — flip the switch in Route 53 or move nameservers |
| **Automated backups** | `pg_dump` → R2 cron container (already in the tech concept) |
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
