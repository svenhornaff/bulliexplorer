"""Unit tests for scripts/backup_db.py (docs/dev/review_17SEP2026.md
housekeeping — "No DB backups").

No live R2/Postgres involved — `boto3` and `subprocess.run` are both
mocked (AGENTS.md: tests must pass with no external API keys/R2
credentials, mock boto3/S3 calls, don't hit real R2 in tests). The one
genuinely pure piece of logic here (retention selection) gets its own
dedicated tests with no mocking at all.
"""

from __future__ import annotations

import datetime
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.backup_db import (
    backup_key,
    dump_database,
    prune_old_backups,
    run_backup,
    select_keys_to_delete,
)


@pytest.mark.unit
def test_backup_key_formats_utc_date():
    """Key is deterministic and lexicographically date-sortable."""
    now = datetime.datetime(2026, 3, 7, 23, 59, tzinfo=datetime.UTC)
    assert backup_key(now) == "backups/backup-2026-03-07.sql.gz"


@pytest.mark.unit
def test_select_keys_to_delete_keeps_newest_n():
    """Only the oldest keys beyond the retention window are selected —
    keys sort lexicographically in date order, so a plain sort suffices.
    """
    keys = [f"backups/backup-2026-01-{day:02d}.sql.gz" for day in range(1, 21)]  # 20 days
    to_delete = select_keys_to_delete(keys, keep=14)
    assert len(to_delete) == 6
    assert to_delete == [f"backups/backup-2026-01-{day:02d}.sql.gz" for day in range(1, 7)]


@pytest.mark.unit
def test_select_keys_to_delete_under_retention_deletes_nothing():
    keys = [f"backups/backup-2026-01-{day:02d}.sql.gz" for day in range(1, 5)]
    assert select_keys_to_delete(keys, keep=14) == []


@pytest.mark.unit
def test_select_keys_to_delete_exactly_at_retention_deletes_nothing():
    keys = [f"backups/backup-2026-01-{day:02d}.sql.gz" for day in range(1, 15)]  # exactly 14
    assert select_keys_to_delete(keys, keep=14) == []


@pytest.mark.unit
def test_dump_database_runs_pg_dump_via_docker_compose_and_gzips_stdout():
    fake_sql = b"-- fake pg_dump output --"
    fake_result = MagicMock(stdout=fake_sql)
    with patch("scripts.backup_db.subprocess.run", return_value=fake_result) as mock_run:
        payload = dump_database()

    args = mock_run.call_args[0][0]
    assert args[:2] == ["docker", "compose"]
    assert "pg_dump" in args
    assert mock_run.call_args.kwargs["check"] is True
    # gzip round-trips back to the original stdout bytes.
    import gzip

    assert gzip.decompress(payload) == fake_sql


@pytest.mark.unit
def test_dump_database_propagates_pg_dump_failure():
    """A failed pg_dump (non-zero exit) must not be silently swallowed —
    check=True lets CalledProcessError surface to the caller.
    """
    with patch(
        "scripts.backup_db.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["pg_dump"]),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            dump_database()


@pytest.mark.unit
def test_prune_old_backups_deletes_only_stale_keys():
    keys = [f"backups/backup-2026-01-{day:02d}.sql.gz" for day in range(1, 21)]
    mock_client = MagicMock()
    mock_client.list_objects_v2.return_value = {"Contents": [{"Key": k} for k in keys]}

    deleted = prune_old_backups(mock_client, bucket="test-bucket")

    assert len(deleted) == 6
    assert mock_client.delete_object.call_count == 6
    mock_client.list_objects_v2.assert_called_once_with(Bucket="test-bucket", Prefix="backups/")


@pytest.mark.unit
def test_prune_old_backups_empty_bucket_deletes_nothing():
    mock_client = MagicMock()
    mock_client.list_objects_v2.return_value = {}  # no "Contents" key at all

    deleted = prune_old_backups(mock_client, bucket="test-bucket")

    assert deleted == []
    mock_client.delete_object.assert_not_called()


@pytest.mark.unit
def test_run_backup_aborts_when_r2_not_configured():
    """Missing credentials must fail loudly (sys.exit(1)), not silently
    skip the backup — a cron job that quietly does nothing looks
    identical to success in a mailbox nobody reads closely.
    """
    mock_settings = MagicMock(s3_endpoint_url="", s3_access_key="")
    with (
        patch("scripts.backup_db.get_settings", return_value=mock_settings),
        patch("scripts.backup_db.dump_database") as mock_dump,
        pytest.raises(SystemExit) as exc_info,
    ):
        run_backup()

    assert exc_info.value.code == 1
    mock_dump.assert_not_called()


@pytest.mark.unit
def test_run_backup_uploads_and_prunes_when_configured():
    mock_settings = MagicMock(
        s3_endpoint_url="https://example.r2.cloudflarestorage.com",
        s3_access_key="fake-key",
        s3_secret_key="fake-secret",  # noqa: S106 — test double, not a real secret  # nosec B106
        s3_bucket="test-bucket",
    )
    fake_payload = b"gzipped-sql-bytes"
    mock_s3_client = MagicMock()
    mock_s3_client.list_objects_v2.return_value = {"Contents": []}

    with (
        patch("scripts.backup_db.get_settings", return_value=mock_settings),
        patch("scripts.backup_db.dump_database", return_value=fake_payload),
        patch("scripts.backup_db.boto3.client", return_value=mock_s3_client) as mock_boto_client,
    ):
        run_backup()

    mock_boto_client.assert_called_once_with(
        "s3",
        endpoint_url="https://example.r2.cloudflarestorage.com",
        aws_access_key_id="fake-key",
        aws_secret_access_key="fake-secret",  # noqa: S106 — test double, not a real secret  # nosec B106
    )
    put_call = mock_s3_client.put_object.call_args
    assert put_call.kwargs["Bucket"] == "test-bucket"
    assert put_call.kwargs["Body"] == fake_payload
    assert put_call.kwargs["Key"].startswith("backups/backup-")
