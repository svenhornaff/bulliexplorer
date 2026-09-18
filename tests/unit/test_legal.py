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


@pytest.mark.unit
async def test_sentry_notice_matches_configuration(client, monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    get_settings.cache_clear()
    response = await client.get("/datenschutz")
    assert "Fehlerüberwachung mit Sentry" not in response.text
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.org/1")
    get_settings.cache_clear()
    get_settings.cache_clear()
    response = await client.get("/datenschutz")
    assert "Fehlerüberwachung mit Sentry" in response.text


@pytest.mark.unit
async def test_legal_config_is_plain_text(client, monkeypatch):
    monkeypatch.setenv("LEGAL_ADDRESS", "<script>alert(1)</script>\n[click](https://evil.example)")
    get_settings.cache_clear()
    response = await client.get("/impressum")
    assert "&lt;script&gt;" in response.text
    assert 'href="https://evil.example"' not in response.text
    assert "<br>" in response.text


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/impressum", "/datenschutz"])
async def test_production_refuses_missing_disclosures(client, monkeypatch, path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_ADDRESS", "")
    get_settings.cache_clear()
    assert (await client.get(path)).status_code == 503
    assert (await client.get("/health")).status_code == 200


@pytest.mark.unit
async def test_production_legal_pages_with_verified_values(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_CLASSIFICATION", "commercial")
    for field in ["ADDRESS", "EMAIL", "HOSTING", "LOG_RETENTION", "CLOUDFLARE_DETAILS", "SENTRY_DETAILS"]:
        monkeypatch.setenv("LEGAL_" + field, "Verified test value")
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.org/1")
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
async def test_classification_personal_still_requires_datenschutz_fields(client, monkeypatch):
    """The personal/family exemption is about provider ID, not GDPR — /datenschutz
    still needs the controller address and other fields regardless of classification."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGAL_CLASSIFICATION", "personal")
    monkeypatch.setenv("LEGAL_EMAIL", "hallo@example.org")
    monkeypatch.setenv("LEGAL_ADDRESS", "")
    get_settings.cache_clear()
    assert (await client.get("/datenschutz")).status_code == 503


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
