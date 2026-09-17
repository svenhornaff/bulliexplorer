"""Nightly Postgres backup to Cloudflare R2, with retention pruning.

Housekeeping item from ``docs/dev/review_17SEP2026.md`` (tech debt
register, "No DB backups") and ``docs/dev/monitoring_ops.md`` Phase 4 —
``nearby_amenities`` is now 15k+ rows that are expensive to re-derive
against a flaky public API (Overpass), so "everything is re-derivable
from git + OSM" no longer fully holds. Reuses the ``boto3`` dependency
and ``s3_*`` settings already declared for media storage
(``docs/dev/media_storage_r2.md``) but left unused there — media ended
up going browser-to-R2 directly via Sveltia instead, so this script is
the first actual caller of that config/dependency pair.

Deliberately a host-cron script, not a new docker-compose service ("no
new services" per the review) — see ``docs/dev/deployment.md`` for the
crontab entry and ``docs/dev/monitoring_ops.md`` Phase 4 for the full
scope/verification write-up.

Usage (see ``make backup``)::

    uv run python scripts/backup_db.py

Requires ``docker compose -f docker-compose.prod.yml`` to be runnable
from the current directory (the ``db`` service must be up) and the
``s3_*``/R2 settings to be configured in the environment — both true on
the production host, neither true by default in local dev, which is
why this isn't wired into any app-startup path.
"""

from __future__ import annotations

import gzip
import subprocess  # noqa: S404 — fixed argv below, no shell, no user input  # nosec B404
import sys
from datetime import UTC, datetime
from typing import Any

import boto3

from app.core.config import get_settings
from app.utils.log_factory import configure_logging, get_logger

logger = get_logger(__name__)

BACKUP_PREFIX = "backups/"
RETENTION_COUNT = 14
COMPOSE_FILE = "docker-compose.prod.yml"
DB_SERVICE = "db"
DB_NAME = "bulliexplorer"
DB_USER = "postgres"


def dump_database() -> bytes:
    """Run ``pg_dump`` inside the running ``db`` container and gzip it.

    Runs via ``docker compose exec`` rather than a direct ``psql``
    connection from the host so the ``pg_dump`` binary version always
    matches the server exactly (both come from the same ``postgis``
    image) — no separate postgres-client install needed on the host.

    Returns
    -------
    bytes
        The gzip-compressed SQL dump.
    """
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell=True, no untrusted input  # nosec B603 B607
        [  # noqa: S607 — relies on `docker` via PATH by design, same as every docker call in Makefile
            "docker",
            "compose",
            "-f",
            COMPOSE_FILE,
            "exec",
            "-T",
            DB_SERVICE,
            "pg_dump",
            "-U",
            DB_USER,
            DB_NAME,
        ],
        capture_output=True,
        check=True,
    )
    return gzip.compress(result.stdout)


def backup_key(now: datetime | None = None) -> str:
    """Build the R2 object key for a backup taken at ``now`` (UTC).

    Parameters
    ----------
    now
        The backup timestamp. Defaults to the current UTC time.

    Returns
    -------
    str
        An object key of the form ``backups/backup-YYYY-MM-DD.sql.gz``.
    """
    now = now or datetime.now(UTC)
    return f"{BACKUP_PREFIX}backup-{now:%Y-%m-%d}.sql.gz"


def select_keys_to_delete(keys: list[str], keep: int = RETENTION_COUNT) -> list[str]:
    """Choose which backup keys to delete to enforce the retention window.

    Backup keys sort lexicographically in date order
    (``backup-YYYY-MM-DD...``), so the newest ``keep`` keys are simply
    the last ``keep`` entries after a plain sort — no need to parse
    dates back out of the key name.

    Parameters
    ----------
    keys
        All existing backup object keys (any order).
    keep
        How many of the newest backups to retain.

    Returns
    -------
    list[str]
        The keys to delete — empty if ``len(keys) <= keep``.
    """
    if len(keys) <= keep:
        return []
    return sorted(keys)[: len(keys) - keep]


def prune_old_backups(s3_client: Any, bucket: str) -> list[str]:
    """Delete backups beyond the retention window.

    Parameters
    ----------
    s3_client
        A boto3 S3 client already configured for the R2 endpoint.
    bucket
        The bucket containing the ``backups/`` prefix.

    Returns
    -------
    list[str]
        The keys that were deleted.
    """
    response = s3_client.list_objects_v2(Bucket=bucket, Prefix=BACKUP_PREFIX)
    keys = [obj["Key"] for obj in response.get("Contents", [])]
    to_delete = select_keys_to_delete(keys)
    for key in to_delete:
        s3_client.delete_object(Bucket=bucket, Key=key)
    return to_delete


def run_backup() -> None:
    """Dump the database, upload it to R2, and prune old backups.

    Aborts (exit code 1) rather than silently no-op-ing when R2
    credentials aren't configured — a backup job that quietly does
    nothing is worse than one that fails loudly, since the former looks
    identical to success in a cron mailbox nobody reads closely.
    """
    settings = get_settings()
    if not settings.s3_endpoint_url or not settings.s3_access_key:
        logger.error("S3/R2 credentials not configured (s3_endpoint_url/s3_access_key) — aborting backup")
        sys.exit(1)

    logger.info("Starting nightly database backup")
    payload = dump_database()
    key = backup_key()

    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
    s3_client.put_object(Bucket=settings.s3_bucket, Key=key, Body=payload)
    logger.info("Uploaded backup %s (%d bytes)", key, len(payload))

    deleted = prune_old_backups(s3_client, settings.s3_bucket)
    if deleted:
        logger.info("Pruned %d old backup(s): %s", len(deleted), ", ".join(deleted))


if __name__ == "__main__":
    configure_logging(json_output=get_settings().log_json)
    run_backup()
