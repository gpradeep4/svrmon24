"""Login gate — interactive module showcase (0.99.3)."""

from __future__ import annotations

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC


def test_login_module_showcase_assets() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")

    assert 'id="loginShowcaseStage"' in html
    assert "login-hero-stage--modules" in html
    assert 'id="loginModuleCaption"' in html
    assert "Explore SVRMON24 modules" not in html
    assert "login-module-detail" not in html
    for mod in ("dashboard", "cmdb", "monitoring", "itsm", "portal", "admin"):
        assert f'data-module="{mod}"' in html
    assert "setActiveModule" in js
    assert "caption" in js
    assert "loginModuleUses" not in js
    assert "prefers-reduced-motion" in js or "prefersReducedMotion" in js
    assert ".login-module-rail" in css
    assert ".login-preview-caption" in css
    assert ".login-module-detail" not in css
    assert "prefers-reduced-motion" in css
    assert f"login-showcase.js?v={__version__}" in html


def test_login_showcase_intro_stack() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert 'class="login-showcase-intro"' in html
    intro_idx = html.index("login-showcase-intro")
    hero_idx = html.index("loginShowcaseStage")
    rail_idx = html.index("loginModuleRail")
    assert intro_idx < hero_idx < rail_idx
    assert ".login-showcase-intro" in css
    assert "login-showcase-copy" not in html


def test_login_showcase_tilt_and_reduced_motion() -> None:
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert "login-preview-tilt" in css
    tilt_block = css.split(".login-hero-stage--modules .login-preview-tilt", 1)[1].split("}", 1)[0]
    assert "perspective:" in tilt_block
    assert "rotateY" in css
    reduced = css.split("@media (prefers-reduced-motion: reduce)", 1)[1].split("@media", 1)[0]
    assert "perspective: none" in reduced
    assert "transform: none" in reduced


def test_version_bump_for_login_showcase_cleanup() -> None:
    assert __version__ == "0.99.3"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.3"' in html
    assert 'content="login-enterprise-v18"' in html


def test_login_fullbleed_layout_css() -> None:
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="loginGate"' in html
    assert "minmax(0, 1fr) minmax(380px, 440px)" in css
    assert "#loginGate.login-gate-split" in css
    assert "max-width: none" in css.split("#loginGate.login-gate-split", 1)[1].split("}", 1)[0]
    assert "body.is-login" in css
    assert ".login-gate-enterprise .login-portal-bg::after" in css
    assert "backdrop-filter: blur(14px)" in css