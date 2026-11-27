"""Login gate — hub modules graphic + Option B overview (0.99.11)."""

from __future__ import annotations

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC


def test_login_module_showcase_assets() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")

    assert 'id="loginShowcaseStage"' in html
    assert "login-hero-stage--modules" in html
    assert "login-hero-stage--best" in html
    assert 'id="loginModulesVisual"' in html
    assert 'id="loginHubHotspots"' in html
    assert 'id="loginModuleDetail"' in html
    assert 'id="loginOverviewModal"' in html
    assert 'id="btnLoginWatchOverview"' in html
    assert "login-hub" in html
    assert "login-hub-spokes" in html
    assert "login-hub-core" in html
    assert 'id="loginCapabilityGrid"' not in html
    assert "login-cap-card" not in html
    assert "login-panels/panel-" not in html
    assert "login-preview-tilt" not in html
    assert "login-modules-composite.jpg" not in html
    assert 'id="loginModulesComposite"' not in html
    assert "setActiveModule" in js
    assert "openOverviewModal" in js
    assert "login-cap-play" not in js
    assert "buildCards" not in js
    assert "prefers-reduced-motion" in js or "prefersReducedMotion" in js
    for mod in ("cmdb", "monitoring", "itsm", "portal", "secureops", "config"):
        assert f'data-module="{mod}"' in html
        assert f'id: "{mod}"' in js
    assert ".login-hub" in css
    assert ".login-hub-node" in css
    assert ".login-hub-core" in css
    assert ".login-module-detail" in css
    assert ".login-modules-visual" in css
    assert ".login-watch-overview" in css
    assert ".login-overview-modal" in css
    assert "prefers-reduced-motion" in css
    assert f"login-showcase.js?v={__version__}" in html
    assert (FRONTEND_STATIC / "assets" / "brand" / "modules-overview-loop.mp4").is_file()
    assert (FRONTEND_STATIC / "assets" / "brand" / "modules-overview-poster.png").is_file()
    assert not (FRONTEND_STATIC / "assets" / "login-panels").exists()


def test_login_showcase_intro_stack() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert 'class="login-showcase-intro"' in html
    intro_idx = html.index("login-showcase-intro")
    hero_idx = html.index("loginShowcaseStage")
    assert intro_idx < hero_idx
    assert "Watch overview" in html
    assert ".login-showcase-intro" in css
    assert "login-showcase-copy" not in html
    assert "login-module-chip" not in html.split('id="loginGate"', 1)[1].split('id="appShell"', 1)[0]
    assert 'id="loginCapabilityGrid"' not in html


def test_login_showcase_hub_no_card_chrome() -> None:
    """Hub sits on page wash — no image plate, no capability cards, no nested panel."""
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert "login-modules-visual" in html
    assert "login-hub-node" in html
    assert "login-hub-core" in html
    assert "login-preview-tilt" not in html
    assert "login-dashboard-tilt" not in html
    assert 'id="loginCapabilityGrid"' not in html
    assert "login-modules-composite.jpg" not in html
    assert "background: transparent" in css.split("Hub graphic", 1)[-1].split(".login-capability-grid", 1)[0]
    hub_css = css.split("Hub graphic", 1)[-1].split(".login-capability-grid", 1)[0]
    assert "box-shadow: none" in hub_css
    assert ".login-module-detail" in hub_css
    assert "backdrop-filter: blur(10px)" not in hub_css
    gate = html.split('id="loginGate"', 1)[1].split('id="appShell"', 1)[0]
    assert "rotateY" not in gate
    assert "login-preview-viewport--shots" not in gate
    for label in ("CMDB", "Monitoring", "ITSM", "Service Portal", "SecureOps", "Configuration"):
        assert label in html


def test_login_hub_nodes_accessible_details() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert 'aria-describedby="loginModuleDetail"' in html
    assert 'id="loginModuleDetailTitle"' in html
    assert 'id="loginModuleDetailBody"' in html
    assert "mouseenter" in js
    assert 'addEventListener("focus"' in js
    assert "ArrowRight" in js
    assert ".login-hub-node:focus-visible" in css or "login-hub-node:focus-visible" in css


def test_login_card_play_opens_overview_without_autoplay() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    assert 'id="loginOverviewVideo"' in html
    video_snip = html.split('id="loginOverviewVideo"', 1)[1].split("</video>", 1)[0].lower()
    assert "autoplay" not in video_snip
    assert 'preload="metadata"' in html
    assert "btnLoginWatchOverview" in js
    assert "video.play" in js
    init = js.split("function initLoginShowcase", 1)[1].split("window.svrmonLoginShowcase", 1)[0]
    assert ".play(" not in init
    assert "openOverviewModal" not in init


def test_version_bump_for_login_generic_modules() -> None:
    assert __version__ == "0.99.11"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.11"' in html
    assert 'content="login-enterprise-v20"' in html


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
