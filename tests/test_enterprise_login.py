"""Static markup checks for enterprise login gate (no browser)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC


def _static_paths() -> tuple:
    return FRONTEND_INDEX, FRONTEND_STATIC / "js" / "cmdb.js"


def test_enterprise_login_structure() -> None:
    html_path, js_path = _static_paths()
    html = html_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")

    assert 'content="login-enterprise-v18"' in html
    assert "svrmon-brand-lockup" in html
    assert 'src="/static/img/svrmon-logo.png"' in html
    assert "svrmon-logo-compact.png" in html
    assert 'class="svrmon-brand-lockup svrmon-brand-lockup--showcase"' in html
    assert "login-brand-markrow" not in html
    assert "login-brand-wordmark" not in html
    assert "login-hero-stage" in html
    for name in (
        "svrmon-logo.png",
        "svrmon-logo-compact.png",
        "svrmon-logo-sidebar.png",
        "svrmon-logo-mark.png",
        "svrmon-favicon.png",
        "svrmon-apple-touch.png",
    ):
        assert (FRONTEND_STATIC / "img" / name).is_file()
    for name in (
        "brand/svrmon24-logo.svg",
        "brand/svrmon24-symbol.svg",
        "brand/login-waves.png",
        "brand/login-waves.svg",
        "icons/cmdb.svg",
        "icons/ai-investigation.svg",
        "icons/diagnostics.svg",
        "icons/log-intelligence.svg",
        "icons/workflows.svg",
        "icons/security.svg",
    ):
        assert (FRONTEND_STATIC / "assets" / name).is_file()
    assert "svrmon-favicon.png" in html
    assert "brand.js" in html
    assert "config.js" in html
    brand_js = (FRONTEND_STATIC / "js" / "brand.js").read_text(encoding="utf-8")
    assert "SVRMON24_BRAND" in brand_js
    assert "user-png-exact" in brand_js
    assert "logoPng" in brand_js
    assert "logoSidebarPng" in brand_js
    assert "markPng" in brand_js
    assert "logoSvg" in brand_js
    assert "symbolSvg" in brand_js
    assert "loginWavesPng" in brand_js
    assert "loginWavesSvg" in brand_js
    assert 'id="svrmon-brand-s"' not in html
    assert "brand-s-logo" not in html
    assert "login-gate-enterprise" in html
    assert 'id="loginGate"' in html
    assert "login-gradient-text" in html
    assert "Turn Incidents into" in html
    assert "AI Infrastructure Diagnostic" in html
    assert "Open Investigations" in html
    assert "login-dash-nav-item" in html
    assert "login-portal-bg" in html
    assert "login-waves.png" in (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert 'id="loginModuleRail"' in html
    assert 'id="loginPreviewViewport"' in html
    assert 'id="loginModuleCaption"' in html
    assert "Explore SVRMON24 modules" not in html
    assert "login-module-detail" not in html
    assert 'data-module="cmdb"' in html
    assert 'data-module="monitoring"' in html
    assert 'data-module="portal"' in html
    assert "login-showcase.js" in html
    assert "Sign in to your SVRMON24 workspace" in html
    assert 'id="authMethodNote"' in html
    assert "login-dashboard-tilt" in html
    assert "login-dashboard-preview" in html
    assert "login-module-chip" in (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert ".login-preview-caption" in (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
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
    assert "logged_out" in js
    assert "clearStoredBasicAuth" in js
    assert "logoutHomeWithLoggedOutFlag" in js
    assert "basicCredentials" in js
    assert "activeBasicCredentials" in js
    assert "brand-mark--sidebar" in html
    assert 'class="svrmon-brand-lockup svrmon-brand-lockup--sidebar"' in html
    assert 'src="/static/img/svrmon-logo-sidebar.png"' in html
    assert "brand-sidebar-wordmark" not in html
    assert "brand-wordmark-swoosh" not in html
    # Remember me is opt-in (unchecked by default) so Basic does not silently resume on refresh.
    assert 'id="authRemember" checked' not in html


def test_enterprise_login_png_derivatives_match_source() -> None:
    """Lockup PNGs are pinned exports of the user-provided master (not hand-drawn SVG)."""
    expected = {
        "svrmon-logo.png": "babf589ea4f241a951abc2db1054ae2b943c92d7866ca3b03483855bf31a9ae5",
        "svrmon-logo-compact.png": "2f89cd55fa745977ba2bae21e4588b28c107319b1fc5e966d27d198283c4d740",
        "svrmon-logo-sidebar.png": "f10cde67d141f5d41a1e9fe9d7d830bd70481b23af0559c2090aea14a46c45c1",
        "svrmon-logo-mark.png": "c3b89a03ee43a0786c00bb10970f4961814bcefa8ed1e236f128c42d7078aa7d",
        "svrmon-favicon.png": "9697fcd5f81030bf25b78938d72179f3518e44d3f48020ad24ce07e682e5b54a",
    }
    for name, digest in expected.items():
        path = FRONTEND_STATIC / "img" / name
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_enterprise_login_responsive_layout_css() -> None:
    css_path = FRONTEND_STATIC / "css" / "cmdb.css"
    css = css_path.read_text(encoding="utf-8")
    assert "@media (min-width: 1200px)" in css
    assert "grid-template-areas: \"portal form\"" in css
    assert "@media (max-width: 1199px)" in css
    assert ".svrmon-brand-lockup--showcase" in css
    assert "svrmon-logo-mark.png" in css
    assert "minmax(0, var(--sidebar-w))" in css
    assert ".sidebar" in css and "min-width: 0" in css
    assert ".brand-mark--png" in css and "overflow: hidden" in css
    assert "--login-panel-bg:" in css
    assert 'url("/static/assets/brand/login-waves.png")' in css
    assert "background-position: left bottom" in css
    assert "justify-content: flex-start" in css
    assert ".login-gate-enterprise .login-form-pane::before" in css


def test_enterprise_login_scale_layout_css() -> None:
    """Full-bleed hero pane (flush left); sign-in rail pinned on the right."""
    css_path = FRONTEND_STATIC / "css" / "cmdb.css"
    css = css_path.read_text(encoding="utf-8")
    assert "minmax(0, 1fr) minmax(380px, 440px)" in css
    assert "minmax(0, 1200px) minmax(400px, 440px)" not in css
    assert "min(840px, 92%)" not in css
    assert "max-width: min(1080px, 92%)" not in css
    gate_desktop = css.split("@media (min-width: 1200px)", 1)[1].split(".login-gate-split", 1)[1].split("}", 1)[0]
    assert "justify-content: stretch" in gate_desktop
    portal_inner_desktop = css.split(".login-portal-inner {", 2)[2]
    assert "max-width: none" in portal_inner_desktop
    assert "margin-inline: 0" in portal_inner_desktop
    assert "justify-content: flex-start" in portal_inner_desktop
    assert "max-width: min(1200px, 100%)" not in css
    assert "container-type: size" in css
    assert "container-name: login-showcase" in css
    assert "3.2cqi" in css or "cqi" in css
    assert ".login-portal-inner" in css
    assert ".login-hero-stage" in css
    assert "rotateY(-13deg)" in css
    assert ".login-hero-stage .login-dashboard-tilt" in css
    assert "width: min(100%, 560px)" not in css
    assert "backdrop-filter: blur(14px)" in css
    assert "radial-gradient(circle at 1px 1px" in css
    # Desktop composition: vertical stack (logo → intro → preview → chips), not headline beside mock.
    assert ".login-showcase-intro" in css
    assert "grid-column: 2" not in css.split(".login-hero-stage--modules", 1)[0]
    assert "margin-inline-start: clamp(20px, 5.5cqi, 96px)" in css
    assert "perspective-origin: 22% 46%" in css
    # Post-login sidebar: transparent PNG lockup (no CSS-split wordmark / white pill).
    assert ".brand-mark--sidebar" in css
    assert ".svrmon-brand-lockup--sidebar" in css
    sidebar_mark = css.split(".brand-mark--sidebar", 1)[1].split("}", 1)[0]
    assert "background: transparent" in sidebar_mark
    assert "border-radius: 0" in sidebar_mark
    assert ".brand-sidebar-wordmark" not in css
    assert "brand-wordmark--sidebar" not in css


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
    assert __version__ == "0.99.7"
    assert f'content="{__version__}"' in html
    assert f"cmdb.css?v={__version__}" in html
    assert f"cmdb.js?v={__version__}" in html
    assert f"brand.js?v={__version__}" in html
    assert f"config.js?v={__version__}" in html