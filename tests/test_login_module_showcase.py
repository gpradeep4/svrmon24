"""Login gate — interactive module showcase (0.97.0)."""

from __future__ import annotations

from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC


def test_login_module_showcase_assets() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")

    assert 'id="loginShowcaseStage"' in html
    assert "login-hero-stage--modules" in html
    for mod in ("dashboard", "cmdb", "monitoring", "itsm", "portal", "admin"):
        assert f'data-module="{mod}"' in html
    assert "setActiveModule" in js
    assert "prefers-reduced-motion" in js or "prefersReducedMotion" in js
    assert ".login-module-rail" in css
    assert "prefers-reduced-motion" in css
    assert "login-showcase.js?v=0.97.0" in html