"""Playwright e2e smoke tests — docs/dev/playwright_e2e_smoke_tests.md.

Direct response to a real production bug: a MapLibre style-validation
failure took down the entire map (base tiles included), while every
existing unit test — which only checks that certain strings exist in
post-map.js — stayed green. These tests load a real page in a real
browser and check the actual runtime behaviour those string checks
cannot see at any coverage percentage.

Deliberately a smoke tier, not comprehensive coverage — see the doc's
own "Scope" section for what's explicitly out.

Run with: make e2e (needs `docker compose up -d` first, same as
tests/integration/). Skipped automatically when DATABASE_URL isn't set
(see conftest.py's _require_env) — never runs as a silent, misleading
pass; it's an explicit, visible skip.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, sync_playwright

pytestmark = pytest.mark.e2e

_WITH_ROUTE_SLUG = "e2e-fixture-with-route"
_POIS_ONLY_SLUG = "e2e-fixture-pois-only"
_NO_GEO_SLUG = "e2e-fixture-no-geo"

_ALL_SLUGS = [_WITH_ROUTE_SLUG, _POIS_ONLY_SLUG, _NO_GEO_SLUG]


def _collect_console_errors(page: Page) -> list[str]:
    """Attach console/pageerror listeners, returning the live list they append to.

    Must be called *before* page.goto() — errors during the initial
    script execution (exactly the class of bug this tier exists for)
    happen synchronously on load, not after.
    """
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(f"[console.{msg.type}] {msg.text}") if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(f"[pageerror] {exc}"))
    return errors


def _install_maplibre_error_hook(page: Page) -> None:
    """Hook `maplibregl.Map` so any `error` event fires into a page-global list.

    The precise, minimal check described in the doc: MapLibre emits a
    real `error` event on the map instance when style loading fails —
    this is exactly the mechanism the real incident's bug tripped,
    independent of whatever else may or may not reach the console.
    Installed via an init script (runs before any page script, so it's
    in place before maplibre-gl.js's own UMD assigns `window.maplibregl`).
    """
    page.add_init_script(
        """
        window.__maplibreErrors = [];
        let _realMaplibregl;
        Object.defineProperty(window, 'maplibregl', {
            configurable: true,
            get() { return _realMaplibregl; },
            set(v) {
                const OrigMap = v.Map;
                function PatchedMap(...args) {
                    const inst = new OrigMap(...args);
                    inst.on('error', (e) => {
                        window.__maplibreErrors.push(String((e && e.error) || e));
                    });
                    return inst;
                }
                PatchedMap.prototype = OrigMap.prototype;
                v.Map = PatchedMap;
                _realMaplibregl = v;
            },
        });
        """
    )


# ---------------------------------------------------------------------------
# Check 1 — page loads with HTTP 200 and zero console/page errors.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", _ALL_SLUGS)
def test_page_loads_with_no_console_errors(e2e_base_url, slug):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        errors = _collect_console_errors(page)

        response = page.goto(f"{e2e_base_url}/posts/{slug}", wait_until="networkidle")

        assert response is not None
        assert response.status == 200, f"expected HTTP 200 for /posts/{slug}, got {response.status}"
        assert errors == [], f"console/page errors on /posts/{slug}: {errors}"

        browser.close()


# ---------------------------------------------------------------------------
# Check 2 — for posts with a route: map canvas exists, MapLibre's error
# event never fired. The direct check for the exact bug class this tier
# is named for.
# ---------------------------------------------------------------------------


def test_map_renders_without_maplibre_error_event(e2e_base_url):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        _install_maplibre_error_hook(page)
        errors = _collect_console_errors(page)

        page.goto(f"{e2e_base_url}/posts/{_WITH_ROUTE_SLUG}", wait_until="networkidle")
        page.wait_for_timeout(2000)  # let async tile loads/style validation settle

        canvas = page.query_selector("#post-map canvas")
        assert canvas is not None, "map canvas never appeared — style failed to load entirely"

        maplibre_errors = page.evaluate("window.__maplibreErrors")
        assert maplibre_errors == [], f"MapLibre 'error' event fired: {maplibre_errors}"
        assert errors == [], f"console/page errors alongside map load: {errors}"

        browser.close()


def test_posts_without_route_render_no_map(e2e_base_url):
    """The negative case for check 2 — no route means no map block at all."""
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()

        for slug in (_POIS_ONLY_SLUG, _NO_GEO_SLUG):
            page.goto(f"{e2e_base_url}/posts/{slug}", wait_until="networkidle")
            assert page.query_selector("#map-wrap") is None, f"/posts/{slug} unexpectedly has a map block"

        browser.close()


# ---------------------------------------------------------------------------
# Check 3 — the elevation chart canvas exists and has non-trivial
# rendered content (not a blank canvas). Same reasoning as check 2,
# different renderer (elevation-chart.js, a wholly separate script from
# post-map.js — exactly why the real incident's map crash didn't also
# take the chart down, and why this tier checks both independently).
# ---------------------------------------------------------------------------


def test_elevation_chart_renders_non_blank_canvas(e2e_base_url):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        errors = _collect_console_errors(page)

        page.goto(f"{e2e_base_url}/posts/{_WITH_ROUTE_SLUG}", wait_until="networkidle")
        page.wait_for_timeout(500)

        canvas = page.query_selector("#elevation-chart")
        assert canvas is not None, "elevation chart canvas never appeared"

        # A blank <canvas> encodes to a tiny, near-identical PNG for any
        # size; real chart content (axes, line, fill) produces a
        # meaningfully larger data URL. Cheap, real signal — no pixel
        # inspection needed.
        data_url_length = page.evaluate("document.querySelector('#elevation-chart').toDataURL().length")
        assert data_url_length > 2000, (
            f"elevation chart canvas looks blank (data URL length {data_url_length}) — "
            "expected real rendered content (axes/line/fill)"
        )
        assert errors == [], f"console/page errors alongside elevation chart render: {errors}"

        browser.close()


# ---------------------------------------------------------------------------
# Check 4 — each existing toggle can be clicked without throwing. Not
# verifying every visual outcome, just that the interaction itself
# doesn't error (docs/dev/playwright_e2e_smoke_tests.md's own explicit
# scope limit).
# ---------------------------------------------------------------------------


def test_theme_toggle_does_not_throw(e2e_base_url):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        errors = _collect_console_errors(page)

        page.goto(f"{e2e_base_url}/posts/{_NO_GEO_SLUG}", wait_until="networkidle")
        page.click("#theme-toggle")
        page.wait_for_timeout(200)

        assert errors == [], f"theme toggle click raised: {errors}"
        browser.close()


def test_map_fullscreen_toggle_does_not_throw(e2e_base_url):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        errors = _collect_console_errors(page)

        page.goto(f"{e2e_base_url}/posts/{_WITH_ROUTE_SLUG}", wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.click("#map-fullscreen-toggle")
        page.wait_for_timeout(300)

        assert errors == [], f"fullscreen toggle click raised: {errors}"
        browser.close()


def test_nearby_services_toggle_does_not_throw(e2e_base_url):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        errors = _collect_console_errors(page)

        page.goto(f"{e2e_base_url}/posts/{_WITH_ROUTE_SLUG}", wait_until="networkidle")
        page.wait_for_timeout(1000)

        checkbox = page.query_selector("#amenity-toggle-input")
        assert checkbox is not None, (
            "amenity toggle never appeared — the fixture's NearbyAmenity seed row "
            "(conftest.py's _seeded_db) didn't take effect"
        )
        page.click("#amenity-toggle-input")
        page.wait_for_timeout(500)  # lazy-fetches amenities.geojson on first check

        assert errors == [], f"nearby-services toggle click raised: {errors}"
        browser.close()
