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

    # --- Monitoring -----------------------------------------------------------
    # Empty default is deliberate: a missing SENTRY_DSN should not crash the
    # app — that would mean a monitoring misconfiguration takes down the very
    # app it's supposed to monitor.  Sentry is initialised only when non-empty.
    sentry_dsn: str = ""

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
