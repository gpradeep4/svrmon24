"""SVRMON24 FastAPI application entrypoint (Phase 2 foundation)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI

from . import __version__
from .auth import verify_basic_credentials
from .config import Settings, get_settings
from .db import close_client, ping_database
from .exceptions import register_exception_handlers
from .logging_config import configure_logging
from .serialization import serialize_document

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "startup app=%s version=%s env=%s",
        settings.app_name,
        __version__,
        settings.app_env,
    )
    # Soft check only — app still starts if MongoDB is down
    db_status = ping_database(settings)
    if db_status.get("ok"):
        logger.info("mongodb_ready database=%s", settings.mongodb_db)
    else:
        logger.warning(
            "mongodb_not_ready database=%s detail=%s",
            settings.mongodb_db,
            db_status.get("detail"),
        )
    yield
    close_client()
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "SVRMON24 Phase 2 foundation: FastAPI + Uvicorn + MongoDB (PyMongo) "
            "with HTTP Basic auth. Diagnostics remain simulated; no remote execution."
        ),
        lifespan=lifespan,
    )
    register_exception_handlers(app)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, Any]:
        """Public liveness probe — no authentication required."""
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": __version__,
            "env": settings.app_env,
        }

    @app.get("/api/status", tags=["status"], dependencies=[Depends(verify_basic_credentials)])
    def api_status(settings_dep: Settings = Depends(get_settings)) -> dict[str, Any]:
        """Authenticated status including MongoDB connectivity."""
        db = ping_database(settings_dep)
        return {
            "status": "ok" if db.get("ok") else "degraded",
            "service": settings_dep.app_name,
            "version": __version__,
            "mongodb": serialize_document(db),
        }

    @app.get("/api/me", tags=["auth"], dependencies=[Depends(verify_basic_credentials)])
    def whoami(username: str = Depends(verify_basic_credentials)) -> dict[str, str]:
        """Return the authenticated username (auth smoke check)."""
        return {"username": username}

    return app


app = create_app()


def run() -> None:
    """Run with Uvicorn (used by `python -m app.main`)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
