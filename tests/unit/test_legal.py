"""Legal page publication and safe configuration rendering."""

import pytest

from app.core.config import get_settings


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/impressum", "/datenschutz"])
async def test_legal_pages_and_footer(client, path):
    get_settings.cache_clear()
    response = await client.get(path)
    assert response.status_code == 200
    assert '<html lang="de">' in response.text
    assert 'href="/impressum"' in response.text
    assert 'href="/datenschutz"' in response.text
    assert "Sven Hornaff" in response.text
    # Footer label is "Rechtliche Hinweise", not "Impressum" — the personal
    # classification means this project doesn't present a commercial
    # Impressum; see docs/dev/legal_gdpr_classification_refactor.md Phase 5.
    # The URL path stays /impressum, only the visible label changed.
    assert "Rechtliche Hinweise" in response.text
    assert 'href="/impressum">Impressum</a>' not in response.text


@pytest.mark.unit
async def test_datenschutz_uses_abstracted_categories_not_vendor_names(client):
    """GDPR Art. 13(1)(e) permits "recipients or categories of recipients" —
    the public notice must not name specific vendors, products, regions, or
    operational thresholds (that's what turned the old version into an
    infrastructure blueprint). Concrete facts live in
    docs/dev/DATA_PROCESSING.md (internal, never published) instead. See
    docs/dev/legal_gdpr_classification_refactor.md Phase 5."""
    get_settings.cache_clear()
    response = await client.get("/datenschutz")
    assert response.status_code == 200
    # Abstracted categories present.
    assert "europäischen Hosting" in response.text
    assert "Objekt-Speicherung" in response.text
    # Art. 13(1)(f) transfer-safeguards section present — abstraction under
    # (1)(e) must not silently drop the separate (1)(f) transfer disclosure.
    assert "Internationale Datenübermittlung" in response.text
    assert "Data Privacy Framework" in response.text
    # No vendor names, products, endpoints, regions, or operational
    # thresholds — these belong in DATA_PROCESSING.md, not here.
    for leaked_detail in [
        "Hetzner",
        "Helsinki",
        "Caddy",
        "Uvicorn",
        "Sentry",
        "ingest.de.sentry.io",
        "Frankfurt",
        "Cloudflare",
        "WEUR",
        "Developer-Tarif",
        "5 × 10 MB",
    ]:
        assert leaked_detail not in response.text, f"{leaked_detail!r} leaked into public /datenschutz"


@pytest.mark.unit
async def test_legal_config_is_plain_text(client, monkeypatch):
    monkeypatch.setenv("LEGAL_ADDRESS", "<script>alert(1)</script>\n[click](https://evil.example)")
    get_settings.cache_clear()
    response = await client.get("/impressum")
    assert "&lt;script&gt;" in response.text
    assert 'href="https://evil.example"' not in response.text
    assert "<br>" in response.text


@pytest.mark.unit
async def test_production_refuses_missing_disclosures(client, monkeypatch):
    """Missing LEGAL_EMAIL (required by both pages) still 503s both
    /impressum and /datenschutz in production. LEGAL_ADDRESS is
    deliberately excluded here — see
    test_datenschutz_renders_without_address_in_production, address is not
    a /datenschutz blocker by design."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_EMAIL", "")
    get_settings.cache_clear()
    assert (await client.get("/impressum")).status_code == 503
    assert (await client.get("/datenschutz")).status_code == 503
    assert (await client.get("/health")).status_code == 200


@pytest.mark.unit
async def test_production_legal_pages_with_verified_values(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_CLASSIFICATION", "commercial")
    for field in ["ADDRESS", "EMAIL"]:
        monkeypatch.setenv("LEGAL_" + field, "Verified test value")
    get_settings.cache_clear()
    assert (await client.get("/impressum")).status_code == 200
    assert (await client.get("/datenschutz")).status_code == 200


@pytest.mark.unit
async def test_classification_unset_refuses_in_production(client, monkeypatch):
    """Unset LEGAL_CLASSIFICATION 503s both legal pages in production — no
    silent default to either "personal" or "commercial"."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_ADDRESS", "Verified test value")
    monkeypatch.setenv("LEGAL_EMAIL", "Verified test value")
    get_settings.cache_clear()
    assert (await client.get("/impressum")).status_code == 503
    assert (await client.get("/datenschutz")).status_code == 503
    assert (await client.get("/health")).status_code == 200


@pytest.mark.unit
async def test_classification_personal_renders_no_address_notice(client, monkeypatch):
    monkeypatch.setenv("LEGAL_CLASSIFICATION", "personal")
    monkeypatch.setenv("LEGAL_EMAIL", "hallo@example.org")
    monkeypatch.setenv("LEGAL_ADDRESS", "")
    get_settings.cache_clear()
    response = await client.get("/impressum")
    assert response.status_code == 200
    assert "personal travel and tour diary" in response.text
    assert "persönliches Reise- und Tourentagebuch" in response.text
    assert "hallo@example.org" in response.text
    assert "Noch einzutragen: address" not in response.text


@pytest.mark.unit
async def test_classification_personal_requires_email_in_production(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_CLASSIFICATION", "personal")
    monkeypatch.setenv("LEGAL_EMAIL", "")
    get_settings.cache_clear()
    assert (await client.get("/impressum")).status_code == 503


@pytest.mark.unit
async def test_classification_personal_datenschutz_only_needs_email(client, monkeypatch):
    """The personal/family exemption is about provider ID, not GDPR — but
    /datenschutz's own required-field list is now just ["email"] since the
    LEGAL_HOSTING/LOG_RETENTION/CLOUDFLARE_DETAILS/SENTRY_DETAILS fields
    were removed in favour of static abstracted categories (see
    docs/dev/legal_gdpr_classification_refactor.md Phase 5). Missing email
    alone still 503s; a present email is now sufficient."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_CLASSIFICATION", "personal")
    monkeypatch.setenv("LEGAL_EMAIL", "")
    monkeypatch.setenv("LEGAL_ADDRESS", "")
    get_settings.cache_clear()
    assert (await client.get("/datenschutz")).status_code == 503


@pytest.mark.unit
async def test_datenschutz_renders_without_address_in_production(client, monkeypatch):
    """GDPR Art. 13(1)(a) requires "the identity and the contact details of
    the controller" — the statutory text does not name a postal address
    specifically. BulliExplorer deliberately does not publish the
    operator's residential address; name + a dedicated contact email is
    treated as sufficient controller identification for /datenschutz.
    LEGAL_ADDRESS is optional here and must never block rendering, unlike
    LEGAL_EMAIL."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_CLASSIFICATION", "personal")
    monkeypatch.setenv("LEGAL_ADDRESS", "")
    monkeypatch.setenv("LEGAL_EMAIL", "Verified test value")
    get_settings.cache_clear()
    response = await client.get("/datenschutz")
    assert response.status_code == 200
    assert "Sven Hornaff" in response.text
    # No address line, and no placeholder standing in for it either.
    assert "Noch einzutragen: address" not in response.text


@pytest.mark.unit
async def test_classification_commercial_matches_existing_behaviour(client, monkeypatch):
    monkeypatch.setenv("LEGAL_CLASSIFICATION", "commercial")
    get_settings.cache_clear()
    response = await client.get("/impressum")
    assert response.status_code == 200
    assert "Sven Hornaff" in response.text
    assert "personal travel and tour diary" not in response.text


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/impressum", "/datenschutz"])
async def test_production_unavailable_renders_branded_html_not_json(client, monkeypatch, path):
    """The 503 for missing legal disclosures must render the site's own HTML
    shell (LegalContentUnavailable + its exception_handler), not FastAPI's
    default bare-JSON HTTPException body — a JSON {"detail": ...} response
    reads as a broken API endpoint to a site visitor, not unpublished content.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_ADDRESS", "")
    get_settings.cache_clear()
    response = await client.get(path)
    assert response.status_code == 503
    assert "text/html" in response.headers["content-type"]
    assert '<html lang="de">' in response.text
    assert '{"detail"' not in response.text
    assert "vervollständigt" in response.text
