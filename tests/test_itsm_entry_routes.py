"""ITSM N6 — bookmarkable SPA routes + optional /itsm entry (0.64.0)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from app import __version__
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_DIR, FRONTEND_INDEX


def test_version_bump_for_entry_routes_slice() -> None:
    assert __version__ == "0.93.0"


def test_monolith_serves_itsm_entry_path(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")

    for path in ("/itsm", "/itsm/"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "text/html" in resp.headers.get("content-type", "")
        assert b"svrmon24-version" in resp.content
        assert b'id="tab-itsm-incidents"' in resp.content


def test_api_only_mode_hides_itsm_entry_html() -> None:
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
            assert client.get("/itsm").status_code == 404
            assert client.get("/itsm/").status_code == 404
    finally:
        os.environ.pop("SERVE_STATIC", None)
        reset_client_for_tests()
        get_settings.cache_clear()
        clear_discovery_cache()


def test_nginx_conf_has_itsm_locations() -> None:
    conf = (FRONTEND_DIR / "nginx.conf").read_text(encoding="utf-8")
    assert "location = /itsm" in conf
    assert "location = /itsm/" in conf


def test_frontend_routing_helpers_and_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.93.0"' in html
    assert "itsm/routing.js?v=0.93.0" in html
    assert "itsm/deeplinks.js?v=0.93.0" in html

    routing = Path("frontend/static/js/itsm/routing.js").read_text(encoding="utf-8")
    assert "parseAppRoute" in routing
    assert "buildAppHash" in routing
    assert "isItsmEntryPath" in routing
    assert "resolveInitialTab" in routing

    # Lightweight parse checks mirroring the JS contract (hash aliases).
    def parse(hash_value: str) -> dict:
        raw = hash_value.lstrip("#")
        if re.match(r"^tab-[^=&]+", raw) and not raw.startswith("tab="):
            raw = "tab=" + raw[len("tab-") :]
        from urllib.parse import parse_qs

        qs = parse_qs(raw, keep_blank_values=True)
        return {k: (v[0] if v else "") for k, v in qs.items()}

    assert parse("#tab=itsm-incidents&component_id=srv-1") == {
        "tab": "itsm-incidents",
        "component_id": "srv-1",
    }
    assert parse("#tab-itsm-incidents&component_id=srv-1")["tab"] == "itsm-incidents"

    cmdb = Path("frontend/static/js/cmdb.js").read_text(encoding="utf-8")
    assert "SVRMON24ItsmRouting" in cmdb
    assert "resolveInitialTab" in cmdb
