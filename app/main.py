"""SVRMON24 FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .auth import AuthUser, require_user
from .config import Settings, get_settings
from .db import close_client, ping_database
from .exceptions import register_exception_handlers
from .logging_config import configure_logging
from .routers import auth_routes
from .routers import components as components_router
from .routers import custom_fields as custom_fields_router
from .routers import dashboard as dashboard_router
from .routers import dependencies as dependencies_router
from .routers import diagnostics as diagnostics_router
from .routers import relationships as relationships_router
from .routers import tenants as tenants_router
from .serialization import serialize_document
from .services.bootstrap import ensure_tenancy_ready

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "startup app=%s version=%s env=%s oidc=%s basic=%s",
        settings.app_name,
        __version__,
        settings.app_env,
        settings.oidc_enabled,
        settings.basic_auth_enabled,
    )
    db_status = ping_database(settings)
    if db_status.get("ok"):
        logger.info("mongodb_ready database=%s", settings.mongodb_db)
        tenancy = ensure_tenancy_ready()
        if tenancy.get("ok"):
            logger.info(
                "tenancy_ready migration_tenant=%s isolation=%s",
                tenancy.get("migration_tenant_id"),
                tenancy.get("isolation_enforced"),
            )
        else:
            logger.warning(
                "tenancy_bootstrap_incomplete detail=%s",
                tenancy.get("detail"),
            )
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
            "SVRMON24: FastAPI + MongoDB CMDB, relationships, dependency/impact "
            "analysis, SIMULATED diagnostics, AI analysis, and dashboard with "
            "provider-neutral OIDC auth (HTTP Basic optional via feature flag). "
            "Tenant/membership models (single logical org); hard isolation is later. "
            "Diagnostics are demo-only; no remote execution."
        ),
        lifespan=lifespan,
    )
    register_exception_handlers(app)

    # Session cookie for OIDC login state + authenticated principal.
    same_site = (settings.session_same_site or "lax").lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age_seconds,
        same_site=same_site,
        https_only=settings.session_https_only,
    )

    app.include_router(auth_routes.router)
    app.include_router(tenants_router.router)
    app.include_router(components_router.router)
    app.include_router(custom_fields_router.router)
    app.include_router(relationships_router.router)
    app.include_router(dependencies_router.router)
    app.include_router(diagnostics_router.router)
    app.include_router(dashboard_router.router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def ui_index() -> FileResponse:
        """CMDB inventory UI (browser). Never cache HTML so login-gate updates apply."""
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, Any]:
        """Public liveness probe — no authentication required."""
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": __version__,
            "env": settings.app_env,
        }

    @app.get("/api/status", tags=["status"])
    def api_status(
        settings_dep: Settings = Depends(get_settings),
        _user: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        """Authenticated status including MongoDB connectivity."""
        db = ping_database(settings_dep)
        return {
            "status": "ok" if db.get("ok") else "degraded",
            "service": settings_dep.app_name,
            "version": __version__,
            "mongodb": serialize_document(db),
        }

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
