"""FastAPI host for mgi-link (thin: health + service info + data bootstrap)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mgi_link import __version__
from mgi_link.buildinfo import build_info
from mgi_link.config import settings
from mgi_link.logging_config import configure_logging
from mgi_link.services.refresh import (
    bootstrap_data,
    start_refresh_scheduler,
    stop_refresh_scheduler,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Bootstrap the MGI index and (optionally) start the refresh scheduler."""
    logger = configure_logging()
    logger.info("mgi-link starting", host=settings.host, port=settings.port)
    await bootstrap_data(settings.data, logger)
    refresh_task = start_refresh_scheduler(settings.data, logger)
    try:
        yield
    finally:
        await stop_refresh_scheduler(refresh_task)
        logger.info("mgi-link shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="mgi-link",
        description="MCP/API server grounding mouse genetics in the MGI dataset.",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness probe (reports build provenance for deploy checks)."""
        return {
            "status": "ok",
            "version": __version__,
            "transport": "streamable-http-stateless",
            "service": "mgi-link",
            **build_info(),
        }

    @app.get("/")
    async def root() -> dict[str, Any]:
        """Service information."""
        return {
            "name": "mgi-link",
            "version": __version__,
            "data_source": "MGI bulk reports (informatics.jax.org) -> local SQLite index",
            "mcp_endpoint": settings.mcp_path,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
