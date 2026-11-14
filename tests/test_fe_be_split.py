"""Smoke tests for API-only (split) deploy mode."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_DIR, FRONTEND_INDEX, FRONTEND_STATIC


def test_frontend_tree_layout() -> None:
    assert FRONTEND_INDEX.is_file()
    assert (FRONTEND_STATIC / "js" / "cmdb.js").is_file()
    assert (FRONTEND_STATIC / "js" / "config.js").is_file()
    assert FRONTEND_DIR.joinpath("nginx.conf").is_file()


def test_api_only_mode_exposes_auth_config_not_static() -> None:
    os.environ["SERVE_STATIC"] = "false"
    from app.config import get_settings
    from app.db import reset_client_for_tests
    from app.main import create_app
    from app.oidc import clear_discovery_cache

    get_settings.cache_clear()
    clear_discovery_cache()
    reset_client_for_tests()
    try:
        app = create_app()
        with TestClient(app) as client:
            assert client.get("/").status_code == 404
            assert client.get("/static/css/cmdb.css").status_code == 404
            cfg = client.get("/api/auth/config")
            assert cfg.status_code == 200
            body = cfg.json()
            assert "basic_auth_enabled" in body
            assert "oidc_enabled" in body
    finally:
        os.environ.pop("SERVE_STATIC", None)
        reset_client_for_tests()
        get_settings.cache_clear()
        clear_discovery_cache()