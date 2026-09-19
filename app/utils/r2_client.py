"""Shared boto3 R2 client construction.

Same client-construction pattern as ``scripts/backup_db.py`` (endpoint/
access/secret from ``Settings``'s ``s3_*`` fields — the write-capable
credentials, distinct from ``r2_access_key_id``, which is the
browser-facing, editor-only value used in
``app/routes/internal.py``'s ``/editor/config.yml``). Extracted here
once a second real caller
(``app.services.cover_image_sync``, via ``app/main.py``'s lifespan and
``app/routes/internal.py``'s resync/webhook handlers,
docs/dev/fix_lcp_image_and_static_cache.md Finding 1) needed the exact
same client, rather than duplicating the construction a second time.
"""

from __future__ import annotations

from typing import Any

import boto3

from app.core.config import Settings


def build_r2_client(settings: Settings) -> Any | None:
    """Return a configured boto3 S3 client for R2, or ``None`` if unconfigured.

    ``None`` (rather than raising) is deliberate — callers
    (``sync_posts``'s cover-image processing) must degrade gracefully to
    serving images unprocessed when R2 write credentials aren't set,
    the same posture as every other missing-credential path in this
    codebase, not a crash. Contrast with ``scripts/backup_db.py``'s own
    ``run_backup()``, which *does* abort loudly on missing credentials —
    a backup job silently doing nothing is worse than failing; an
    unoptimized cover image is not.
    """
    if not settings.s3_endpoint_url or not settings.s3_access_key:
        return None
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
