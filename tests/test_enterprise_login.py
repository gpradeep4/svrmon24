"""Static markup checks for enterprise login gate (no browser)."""

from __future__ import annotations

from pathlib import Path


def _static_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[1]
    return root / "app" / "static" / "index.html", root / "app" / "static" / "js" / "cmdb.js"


def test_enterprise_login_structure() -> None:
    html_path, js_path = _static_paths()
    html = html_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")

    assert 'content="login-enterprise-v5"' in html
    assert "brand-s-logo" in html
    assert 'id="svrmon-brand-s"' in html
    assert "login-gate-enterprise" in html
    assert 'id="loginGate"' in html
    assert "login-gradient-text" in html
    assert "Turn Incidents into" in html
    assert "AI Infrastructure Diagnostic" in html
    assert "CMDB &amp; Infrastructure Inventory" in html or "CMDB & Infrastructure Inventory" in html
    assert "Middleware &amp; Log Intelligence" in html or "Middleware & Log Intelligence" in html
    assert "Open Investigations" in html
    assert "Sign in to your SVRMON24 workspace" in html
    assert 'id="authMethodNote"' in html
    assert "login-feature-grid" in html
    assert "login-dashboard-tilt" in html
    assert "login-dashboard-preview" in html
    assert "Incident-Driven" in html
    assert "login-panel-brand" in html
    assert "login-input-wrap" in html
    assert "login-keycloak-ico" in html
    assert "login-capabilities" in html
    assert 'class="login-panel-title"' in html or "Welcome Back" in html
    assert 'id="btnOidcLogin"' in html
    assert "Sign in with Keycloak (SSO)" in html
    assert 'id="basicAuthRow"' in html
    assert 'id="authUser"' in html
    assert 'id="authPass"' in html
    assert 'id="btnConnect"' in html
    assert "Sign In" in html
    assert 'id="authRemember"' in html
    assert 'id="btnForgotPassword"' in html
    assert "Audit Ready" in html
    assert "toggleAuthPasswordVisibility" in js
    assert "authOrDivider" in js


def test_enterprise_login_responsive_layout_css() -> None:
    css_path = Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "cmdb.css"
    css = css_path.read_text(encoding="utf-8")
    assert "@media (min-width: 1200px)" in css
    assert "grid-template-areas: \"portal form\"" in css
    assert "@media (max-width: 1199px)" in css


def test_enterprise_login_version_bump() -> None:
    from app import __version__

    html_path, _ = _static_paths()
    html = html_path.read_text(encoding="utf-8")
    assert __version__ == "0.32.4"
    assert f'content="{__version__}"' in html
    assert f"cmdb.css?v={__version__}" in html
    assert f"cmdb.js?v={__version__}" in html
