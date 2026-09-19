"""Fixtures for the Playwright e2e smoke-test tier.

docs/dev/playwright_e2e_smoke_tests.md — a third test tier, one level up
from tests/integration/: needs a real PostGIS instance *and* a real
running app process for a real browser to point at, not an ASGI
transport or a mock.

Design, matching the doc:
- A dedicated fixture post per post-type variant, checked into
  tests/e2e/fixtures/, seeded via the *real* sync_posts() machinery
  (not a hand-rolled INSERT) — exercising the real sync path is itself
  worth something.
- One NearbyAmenity row is inserted directly for the "with route" fixture
  post, deliberately bypassing a real Overpass call — auto-discovery
  going out to the live Overpass API on every e2e run would make this
  tier slow and flaky for a reason that has nothing to do with what
  this tier actually checks (MapLibre/canvas rendering, not amenity
  discovery correctness, which is already covered by
  tests/integration/test_geo_sync_integration.py).
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
import pytest
from alembic.config import Config
from geoalchemy2.shape import from_shape
from psycopg import sql
from shapely.geometry import Point
from sqlalchemy import delete

from alembic import command
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory, init_engine
from app.models.nearby_amenity import NearbyAmenity
from app.models.post import Post
from app.models.route import Route
from app.services.post_sync import sync_posts

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parent.parent.parent

FIXTURE_SLUGS = [
    "e2e-fixture-with-route",
    "e2e-fixture-pois-only",
    "e2e-fixture-no-geo",
]

_STARTUP_TIMEOUT_S = 30.0
_STARTUP_POLL_INTERVAL_S = 0.3


def _free_port() -> int:
    """Bind to port 0 to let the OS hand out a free one, then release it.

    A fixed port would collide with a real `make dev` already running on
    8000 (very plausible during manual testing of this exact tier).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(
            f"{name} not set — the e2e tier needs a real DATABASE_URL "
            "(docker compose up -d && export DATABASE_URL=... ), see "
            "docs/dev/playwright_e2e_smoke_tests.md"
        )
    return value  # pragma: no cover — skip path taken in environments without a real DB


def _ensure_e2e_database(base_url: str) -> str:
    """Return a `<db>_e2e`-suffixed URL, creating that database if needed.

    Connects to the `postgres` maintenance database to run `CREATE
    DATABASE` (which cannot run inside a transaction block — psycopg's
    ``autocommit=True`` is required, not optional, here) only when the
    dedicated e2e database doesn't already exist. Idempotent: safe to
    call on every `make e2e` run.
    """
    sync_url = base_url.replace("+psycopg", "")
    parsed = urlsplit(sync_url)
    original_db_name = parsed.path.lstrip("/")
    e2e_db_name = f"{original_db_name}_e2e"

    maintenance_url = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", parsed.query, parsed.fragment))
    with psycopg.connect(maintenance_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (e2e_db_name,))
        if cur.fetchone() is None:
            # sql.Identifier safely quotes the computed database name —
            # the correct psycopg way to parameterise an identifier
            # (values use %s placeholders; identifiers like table/DB
            # names can't, so this is psycopg's own supported mechanism
            # for that case, not a raw string interpolation).
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(e2e_db_name)))

    # A freshly CREATE DATABASE'd database does *not* inherit the
    # postgis extension — hit exactly this (real, not hypothetical) gap:
    # alembic's first migration failed with `type "geometry" does not
    # exist`. The original bulliexplorer DB only has it because the
    # imresamu/postgis image runs `CREATE EXTENSION postgis` once, at
    # container init, on its one configured POSTGRES_DB — a second
    # database created later at runtime needs the same statement run
    # explicitly. Always attempted (IF NOT EXISTS, so cheap and
    # idempotent) rather than gated on "did this call just create the
    # database" — a database created by an earlier, interrupted run
    # (exactly what happened once while building this) needs it too.
    e2e_db_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{e2e_db_name}", parsed.query, parsed.fragment))
    with psycopg.connect(e2e_db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    e2e_path = f"/{e2e_db_name}"
    e2e_sync_url = urlunsplit((parsed.scheme, parsed.netloc, e2e_path, parsed.query, parsed.fragment))
    return e2e_sync_url.replace("postgresql:", "postgresql+psycopg:", 1)


@pytest.fixture(scope="session")
def _database_url() -> str:
    """A dedicated, isolated database for the e2e tier — never the shared dev DB.

    Real incident, hit while building this fixture, not a hypothetical:
    sync_posts() reconciles by deleting any DB row whose slug isn't in
    the given content_dir's current file set — global, not scoped to
    that directory in any way (see app/services/post_sync.py's own
    _delete_removed()). Pointing that at tests/e2e/fixtures/ (3 files)
    against the same DATABASE_URL used for local dev silently deleted
    every real post (dream-of-north, feldberg-summit-loop,
    sunday-gravel-loop) the first time this fixture ran — restored
    manually, but the *design* was wrong, not just unlucky. Existing
    tests/integration/ tests have the identical exposure (test_post_
    sync_integration.py's own tmp_path-based tests commit the same
    reconciling delete against the same real DATABASE_URL) — they've
    happened to survive intact only because some later-running
    integration test's own lifespan re-syncs the real content/posts/
    directory before the pytest session ends, coincidentally restoring
    state. That's existing, pre-existing fragility this task didn't
    introduce and isn't in scope to fix — but this new e2e tier must
    not rely on the same coincidence, especially since `make e2e` is
    designed to run standalone, with nothing after it to "accidentally"
    restore anything.

    Fix: derive a dedicated `<db>_e2e` database name from the real
    DATABASE_URL and create it (via the `postgres` maintenance DB,
    since CREATE DATABASE can't run inside a transaction) if it
    doesn't exist yet — fully isolating this tier's destructive
    reconciliation from any real content, in both local dev and CI.

    Also overwrites this process's own `DATABASE_URL` env var and clears
    Settings' lru_cache: alembic/env.py reads `get_settings().
    database_url` directly and unconditionally, ignoring whatever URL
    is passed to `alembic.config.Config.set_main_option()` — found
    exactly this way when `_migrated_db`'s in-process `command.upgrade`
    silently migrated the *original* database instead of this isolated
    one, and the seeded_db fixture then hit UndefinedTable against the
    (unmigrated) e2e database. Without this, every other in-process
    Settings() read in this same pytest process would keep resolving
    to the original DB too, not just alembic's.
    """
    base_url = _require_env("DATABASE_URL")
    e2e_url = _ensure_e2e_database(base_url)
    os.environ["DATABASE_URL"] = e2e_url
    get_settings.cache_clear()
    return e2e_url


@pytest.fixture(scope="session")
def _migrated_db(_database_url: str):
    """Apply Alembic migrations once for the whole e2e session.

    Deliberately self-contained rather than assuming a prior CI step
    already did this — `make e2e` needs to work standalone, the same
    way `make test` (unit + integration) doesn't require a separate
    manual migration step either once this fixture exists.
    """
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", _database_url.replace("+psycopg", ""))
    command.upgrade(alembic_cfg, "head")
    yield


async def _seed_fixtures(_database_url: str) -> None:
    """Seed the three fixture posts via the real sync_posts() path.

    Also inserts one NearbyAmenity row directly for the "with route"
    fixture (see module docstring for why that one row bypasses a real
    Overpass call rather than the sync path).

    Called *after* the real app process has finished its own startup —
    not before, and not as an independent fixture the app fixture merely
    depends on. Real incident, hit while building this: the app's own
    lifespan runs its own sync_posts() against the real content/posts/
    directory on every startup (app/main.py, unconditionally, by
    design) — sync_posts() reconciles (deletes anything not in the
    given directory), so seeding fixtures *before* starting the app
    got wiped the moment the app's own startup sync ran afterwards.
    Seeding after the app is already up and past its own startup sync
    means this call's own reconciliation is the *last* one to run,
    leaving the fixtures in place for the rest of the session. The
    isolated e2e database (see _database_url's docstring) has no real
    content worth preserving anyway, so this reconciling away the
    app's own real-content sync is harmless here specifically.

    Idempotent: sync_posts() upserts by slug, so re-running `make e2e`
    against an already-seeded database is safe.
    """
    init_engine(_database_url)
    session_factory = get_session_factory()
    async with session_factory() as session:
        await sync_posts(FIXTURES_DIR, session)
        await session.commit()

        route_result = await session.execute(Post.__table__.select().where(Post.slug == "e2e-fixture-with-route"))
        post_row = route_result.first()
        assert post_row is not None, "e2e-fixture-with-route did not sync — check fixture frontmatter"

        route_result = await session.execute(Route.__table__.select().where(Route.post_id == post_row.id))
        route_row = route_result.first()
        assert route_row is not None, "e2e-fixture-with-route synced but has no Route row"

        # Idempotent: clear any prior fixture amenity row(s) for this
        # route before inserting the one this fixture needs, rather than
        # relying on the model's own unique constraint + an upsert.
        await session.execute(delete(NearbyAmenity).where(NearbyAmenity.route_id == route_row.id))
        session.add(
            NearbyAmenity(
                route_id=route_row.id,
                osm_element_type="node",
                osm_element_id=999_000_001,
                category="shelter",
                name="E2E Fixture Amenity",
                location=from_shape(Point(8.005, 47.879), srid=4326),
                tags={"amenity": "shelter"},
            )
        )
        await session.commit()

    await dispose_engine()


@pytest.fixture(scope="session")
def e2e_base_url(_migrated_db, _database_url: str):
    """Start the real app (`uvicorn app.main:app`) as a background process.

    Real dependency, one level up from tests/integration/'s real PostGIS
    container — a real browser needs a real running HTTP server, not an
    ASGI transport (docs/dev/playwright_e2e_smoke_tests.md's own framing).
    """
    port = _free_port()
    env = {
        **os.environ,
        "DATABASE_URL": _database_url,
        "SECRET_KEY": os.environ.get("SECRET_KEY", "e2e-test-secret-not-for-production"),
        "RESYNC_TOKEN": os.environ.get("RESYNC_TOKEN", "e2e-test-resync-token"),
        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "e2e-test-github-token"),
        "WEBHOOK_SECRET": os.environ.get("WEBHOOK_SECRET", "e2e-test-webhook-secret"),
        # Real, public R2 PMTiles URL already used for local dev — not a
        # secret. Needed so the map canvas actually gets a real style to
        # validate/load, the exact mechanism this whole tier exists to
        # check (see the doc's own framing: a *real* browser against a
        # *real* style, not a mock).
        "TILES_URL": os.environ.get(
            "TILES_URL",
            "pmtiles://https://pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev/tiles/europe.pmtiles",
        ),
    }

    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell=True, no untrusted input  # nosec B603
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    started = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"uvicorn exited early (code {proc.returncode}):\n{output}")
        try:
            resp = httpx.get(f"{base_url}/health", timeout=1.0)
            if resp.status_code == 200:
                started = True
                break
        except httpx.HTTPError:
            pass
        time.sleep(_STARTUP_POLL_INTERVAL_S)

    if not started:
        proc.terminate()
        proc.wait(timeout=5)
        raise RuntimeError(f"uvicorn did not become healthy within {_STARTUP_TIMEOUT_S}s")

    # Seed *after* the app is up and has run its own startup content
    # sync — see _seed_fixtures()'s docstring for why the order matters.
    asyncio.run(_seed_fixtures(_database_url))

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
