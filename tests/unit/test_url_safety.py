"""Unit tests for app.utils.url_safety (extracted from geo_sync.py's
_is_allowed_gpx_host — see that module's own thin-wrapper docstring —
docs/dev/fix_lcp_image_and_static_cache.md Finding 1).
"""

from __future__ import annotations

import pytest

from app.utils.url_safety import is_allowed_r2_host


@pytest.mark.unit
def test_is_allowed_r2_host_matches_case_insensitively():
    assert is_allowed_r2_host(
        "https://Pub-Example.r2.dev/media/cover.jpg",
        "https://pub-example.r2.dev",
    )


@pytest.mark.unit
def test_is_allowed_r2_host_rejects_different_host():
    assert not is_allowed_r2_host(
        "https://evil.example.com/media/cover.jpg",
        "https://pub-example.r2.dev",
    )


@pytest.mark.unit
def test_is_allowed_r2_host_fails_closed_when_r2_public_url_unset():
    assert not is_allowed_r2_host("https://pub-example.r2.dev/media/cover.jpg", "")


@pytest.mark.unit
def test_is_allowed_r2_host_rejects_unparsable_urls():
    assert not is_allowed_r2_host("not-a-url", "https://pub-example.r2.dev")
    assert not is_allowed_r2_host("https://pub-example.r2.dev/media/cover.jpg", "not-a-url")
