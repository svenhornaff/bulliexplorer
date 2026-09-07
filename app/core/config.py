"""Centralised settings — pydantic-settings, single source of truth."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App-wide configuration, populated from env / .env file."""

    # --- General -------------------------------------------------------------
    app_env: str = "development"
    debug: bool = False
    log_json: bool = False

    # --- Database ------------------------------------------------------------
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/bulliexplorer"

    # --- S3 / R2 (media storage) --------------------------------------------
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "bulliexplorer"

    # --- Map tiles ----------------------------------------------------------
    # Full pmtiles:// URL for the regional basemap.  Empty → map widget is
    # hidden; the stats row still renders when route data is present.
    # Local dev:  pmtiles://http://localhost:8000/static/pmtiles/black-forest-20260826.pmtiles
    # Production: pmtiles://https://pub-<hash>.r2.dev/tiles/black-forest.pmtiles
    tiles_url: str = ""

    # --- Monitoring -----------------------------------------------------------
    # Empty default is deliberate: a missing SENTRY_DSN should not crash the
    # app — that would mean a monitoring misconfiguration takes down the very
    # app it's supposed to monitor.  Sentry is initialised only when non-empty.
    sentry_dsn: str = ""

    # R2 media library for Sveltia CMS (media_storage_r2.md Phase 1).
    # Empty by default — same non-required pattern as sentry_dsn, not the
    # "no default for secrets" rule: an unconfigured media library must
    # degrade gracefully (git-based uploads keep working), not crash the
    # app. Sourced from .env on the server only — never written to any
    # git-tracked file, since static/editor/config.yml is served as a
    # public static asset. See app/routes/internal.py's dynamic
    # /editor/config.yml route for where these actually get used.
    r2_access_key_id: str = ""
    r2_account_id: str = ""
    r2_public_url: str = ""

    # --- Auth ----------------------------------------------------------------
    secret_key: str  # no default — missing config crashes on startup

    # --- Internal endpoints --------------------------------------------------
    resync_token: str  # no default — missing config crashes on startup

    # --- GitHub Contents API (webhook auto-publish) -------------------------
    # Fine-grained PAT with Contents: Read on the bulliexplorer repo.
    # Used by POST /internal/webhook/github to fetch committed files.
    github_token: str  # no default — missing config crashes on startup
    webhook_secret: str  # no default — generated when registering the webhook

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # --- Convenience properties ----------------------------------------------
    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — import this, not the class."""
    return Settings()  # type: ignore[call-arg] — values come from env / .env file at runtime
