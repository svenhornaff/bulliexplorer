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
    for field in ["ADDRESS", "EMAIL", "HOSTING", "LOG_RETENTION", "CLOUDFLARE_DETAILS", "SENTRY_DETAILS"]:
        monkeypatch.setenv("LEGAL_" + field, "Verified test value")
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.org/1")
    get_settings.cache_clear()
    assert (await client.get("/impressum")).status_code == 200
    assert (await client.get("/datenschutz")).status_code == 200
