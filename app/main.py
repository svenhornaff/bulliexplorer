"""BulliExplorer — application factory + lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.db import dispose_engine, init_engine
from app.utils.log_factory import configure_logging, get_logger

BASE_DIR = Path(__file__).resolve().parent.parent
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    logger.info("BulliExplorer starting up")
    init_engine(settings.database_url)
    yield
    logger.info("BulliExplorer shutting down")
    await dispose_engine()


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    configure_logging(json_output=settings.log_json)

    app = FastAPI(
        title="BulliExplorer",
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Static files & templates -------------------------------------------
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    # Store templates on app.state so routes can access them
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")

    # --- Routers -------------------------------------------------------------
    from app.routes.home import router as home_router

    app.include_router(home_router)

    # --- Health endpoint -----------------------------------------------------
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
