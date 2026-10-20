"""FastAPI application factory for slothd web dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from slothd.config import SlothdConfig
from slothd.integrations.sentry_tracing import init_sentry
from slothd.web.routes import router as api_router

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create and configure the slothd FastAPI application."""
    cfg = SlothdConfig.from_env()

    # Optional Sentry initialization
    if cfg.sentry_dsn:
        init_sentry(cfg.sentry_dsn)

    app = FastAPI(
        title="slothd — The Sloth Daemon",
        description="Air-gapped, local-first AI file organizer that tidies your workspace while you rest.",
        version="0.1.0",
    )

    # CORS configuration for local dashboard access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API router
    app.include_router(api_router)

    # Ensure static directory exists
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    # Mount static assets
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """Serve the single-page application dashboard."""
        index_file = STATIC_DIR / "index.html"
        if not index_file.exists():
            return FileResponse(STATIC_DIR / "index.html")
        return FileResponse(index_file)

    @app.get("/sentry-debug", include_in_schema=False)
    def trigger_sentry_error() -> None:
        """Trigger an intentional test error to verify Sentry connection."""
        _ = 1 / 0

    return app


app = create_app()
