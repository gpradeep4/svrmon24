"""Static markup checks for enterprise login gate (no browser)."""

from __future__ import annotations

from pathlib import Path

from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC


def _static_paths() -> tuple:
    return FRONTEND_INDEX, FRONTEND_STATIC / "js" / "cmdb.js"


def test_enterprise_login_structure() -> None:
    html_path, js_path = _static_paths()
    html = html_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")

    assert 'content="login-enterprise-v8"' in html
    assert "brand-s-logo" in html
    assert 'id="svrmon-brand-s"' in html
    assert "brand-wordmark" in html
    assert "brand-wordmark-core" in html
    assert "brand-wordmark-suffix" in html
    assert "login-hero-stage" in html
    assert (FRONTEND_STATIC / "img" / "svrmon-brand-mark.svg").is_file()
    assert (FRONTEND_STATIC / "img" / "svrmon-favicon.svg").is_file()
    assert "svrmon-favicon.svg" in html
    assert "brand.js" in html
    assert "config.js" in html
    brand_js = (FRONTEND_STATIC / "js" / "brand.js").read_text(encoding="utf-8")
    assert "SVRMON24_BRAND" in brand_js
    assert "markSvg" in brand_js
    mark_svg = (FRONTEND_STATIC / "img" / "svrmon-brand-mark.svg").read_text(encoding="utf-8")
    assert "35.2 11.4" in mark_svg
    assert "35.2 11.4" in html
    assert "svrmon-brand-swoosh" in html
    assert "brand-mark-divider" in html
    assert "brand-wordmark-swoosh" in html
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
    css_path = FRONTEND_STATIC / "css" / "cmdb.css"
    css = css_path.read_text(encoding="utf-8")
    assert "@media (min-width: 1200px)" in css
    assert "grid-template-areas: \"portal form\"" in css
    assert "@media (max-width: 1199px)" in css


def test_enterprise_login_scale_layout_css() -> None:
    """Left showcase must not be capped at ~840px; hero stage places tilted dashboard without narrow column cap."""
    css_path = FRONTEND_STATIC / "css" / "cmdb.css"
    css = css_path.read_text(encoding="utf-8")
    assert "65fr) minmax(0, 35fr)" in css
    assert "min(840px, 92%)" not in css
    assert ".login-portal-inner" in css
    assert "width: 90%;" in css
    assert ".login-hero-stage" in css
    assert "rotateY(-11deg)" in css


def test_env_example_local_dual_auth_defaults() -> None:
  """Local template exposes both auth methods; production still documents Basic off."""
  root = Path(__file__).resolve().parents[1]
  env_example = (root / ".env.example").read_text(encoding="utf-8")
  assert "BASIC_AUTH_ENABLED=true" in env_example
  assert "OIDC_ENABLED=true" in env_example
  assert "BASIC_AUTH_ENABLED=false" in env_example  # production guidance in comments


def test_enterprise_login_version_bump() -> None:
    from app import __version__

    html_path, _ = _static_paths()
    html = html_path.read_text(encoding="utf-8")
    assert __version__ == "0.32.8"
    assert f'content="{__version__}"' in html
    assert f"cmdb.css?v={__version__}" in html
    assert f"cmdb.js?v={__version__}" in html
    assert f"brand.js?v={__version__}" in html
    assert f"config.js?v={__version__}" in html
