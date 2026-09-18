# ── Builder ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock README.md ./
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

# --proxy-headers --forwarded-allow-ips="*": this container is never
# reachable directly from the internet (docker-compose.prod.yml doesn't
# publish this port to the host — only Caddy, on the same Docker
# network, can reach app:8000), so trusting X-Forwarded-For from any
# direct connection is safe here specifically. Without this, uvicorn
# reports the reverse proxy's own internal Docker IP as
# request.client.host for every single request, which is what
# docs/dev/security_review_owasp.md Phase 2's auth-failure logging
# (app/routes/internal.py) discovered live in production — the source_ip
# in "Resync auth failed"/"Webhook auth failed" warnings was always the
# same Caddy-hop IP, never the real caller, making that field useless
# for its actual purpose (telling a brute-force attempt's real source
# apart from normal traffic).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips=*"]
