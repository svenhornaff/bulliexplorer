"""Static validation of the shared R2 bucket's CORS policy (docs/dev/r2-cors.json).

One bucket serves two consumers with different CORS needs:

- Rule 1 — PMTiles basemap reads: public GET/HEAD from any origin, with
  ``Range``/``Accept-Encoding`` request headers and ``Content-Range``/
  ``Content-Length`` exposure (MapLibre/PMTiles range requests read those).
- Rule 2 — Sveltia CMS uploads (media_storage_r2.md Phase 1): browser→R2
  PUT with AWS SigV4 headers from the editor's own origins only.

Rule order matters to R2: it applies the *first* rule whose AllowedOrigins
matches the request's Origin header, without falling through to check
headers on later rules. The specific-origin upload rule must come before
the wildcard tiles rule — otherwise an authenticated SigV4 request from
the editor's own origin matches the wildcard rule first, whose
AllowedHeaders (Range/Accept-Encoding only) rejects the SigV4 headers,
and the browser reports a blanket CORS failure. Tests below select rules
by content (AllowedOrigins), not list position, so a reorder can't
silently break either guard.

Rule 1 predates rule 2 and must never regress as a side effect of upload
changes — these tests exist so an edit to the media rule can't quietly
break the live map.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CORS_PATH = Path(__file__).resolve().parents[2] / "docs" / "dev" / "r2-cors.json"


@pytest.fixture
def rules() -> list[dict]:
    return json.loads(CORS_PATH.read_text())


@pytest.mark.unit
def test_cors_policy_is_two_rules(rules: list[dict]) -> None:
    assert len(rules) == 2


def _find_rule(rules: list[dict], *, wildcard_origin: bool) -> dict:
    """Select a rule by its AllowedOrigins shape, not list position — the
    two rules' relative order matters to R2 (see module docstring) but
    must not matter to these tests."""
    matches = [r for r in rules if (r["AllowedOrigins"] == ["*"]) == wildcard_origin]
    assert len(matches) == 1, f"expected exactly one rule with wildcard_origin={wildcard_origin}"
    return matches[0]


@pytest.mark.unit
def test_upload_rule_precedes_tiles_rule(rules: list[dict]) -> None:
    """The specific-origin upload rule must be listed before the wildcard
    tiles rule — R2 applies the first rule matching Origin only, so the
    reverse order breaks SigV4 uploads from the editor's own origin."""
    assert rules[0]["AllowedOrigins"] != ["*"]
    assert rules[1]["AllowedOrigins"] == ["*"]


@pytest.mark.unit
def test_tiles_rule_unchanged(rules: list[dict]) -> None:
    """The wildcard tiles rule keeps the exact shape the PMTiles setup
    shipped with."""
    tiles = _find_rule(rules, wildcard_origin=True)
    # pi-lens-ignore: cors-wildcard
    assert tiles["AllowedOrigins"] == ["*"]
    assert set(tiles["AllowedMethods"]) == {"GET", "HEAD"}
    assert "Range" in tiles["AllowedHeaders"]
    assert "Accept-Encoding" in tiles["AllowedHeaders"]
    assert "Content-Range" in tiles["ExposeHeaders"]
    assert "Content-Length" in tiles["ExposeHeaders"]
    assert "ETag" in tiles["ExposeHeaders"]
    assert tiles["MaxAgeSeconds"] == 3600


@pytest.mark.unit
def test_upload_rule_matches_sveltia_requirements(rules: list[dict]) -> None:
    """The specific-origin rule covers Sveltia's documented upload needs,
    from the editor's origins only (production site + local dev server)."""
    uploads = _find_rule(rules, wildcard_origin=False)
    assert set(uploads["AllowedMethods"]) == {"GET", "PUT", "HEAD"}
    assert uploads["AllowedHeaders"] == ["*"], "SigV4 sends varied headers; docs prescribe *"
    assert "ETag" in uploads["ExposeHeaders"]
    assert "https://bulliexplorer.com" in uploads["AllowedOrigins"]
    assert "http://localhost:8000" in uploads["AllowedOrigins"], "local dev editor needs access"
    assert "*" not in uploads["AllowedOrigins"], "uploads must not accept any origin"
    assert isinstance(uploads["MaxAgeSeconds"], int)
