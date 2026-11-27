"""Login gate — large hex architecture showcase + Option B overview (0.99.11)."""

from __future__ import annotations

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC


def test_login_module_showcase_assets() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")

    assert 'id="loginShowcaseStage"' in html
    assert "login-hero-stage--modules" in html
    assert 'id="loginModulesVisual"' in html
    assert 'id="loginHubHotspots"' in html
    assert 'id="loginModuleDetail"' in html
    assert 'id="loginModuleDetailBullets"' in html
    assert 'id="loginModuleDetailIcon"' in html
    assert 'id="loginModuleIntro"' in html
    assert 'id="loginOverviewModal"' in html
    assert 'id="btnLoginWatchOverview"' in html
    assert "login-hub-core" in html
    assert "login-hub-core-mark" in html
    assert "svrmon-logo-mark.png" in html
    assert 'id="loginCapabilityGrid"' not in html
    assert "login-panels/panel-" not in html
    assert "setActiveModule" in js
    assert "openModuleIntro" in js
    assert "openOverviewModal" in js
    assert "DEFAULT_MODULE" in js
    assert 'DEFAULT_MODULE = "cmdb"' in js
    assert "bullets:" in js
    assert "Centralised infrastructure inventory" in js
    assert "Role-based access control" in js
    assert "buildCards" not in js
    for mod in ("cmdb", "monitoring", "itsm", "portal", "secureops", "config"):
        assert f'data-module="{mod}"' in html
        assert f'id: "{mod}"' in js
    assert ".login-hub-node" in css
    assert "login-hub-pulse" in css
    assert "login-curve-glow" in css
    assert "scale(1.06)" in css or "scale(1.04)" in css
    assert ".login-module-detail-bullets" in css
    assert ".login-module-intro" in css
    assert f"login-showcase.js?v={__version__}" in html
    assert (FRONTEND_STATIC / "assets" / "brand" / "modules-overview-loop.mp4").is_file()


def test_login_showcase_intro_stack() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'class="login-showcase-intro"' in html
    intro_idx = html.index("login-showcase-intro")
    hero_idx = html.index("loginShowcaseStage")
    assert intro_idx < hero_idx
    assert "Watch overview" in html
    assert 'id="loginCapabilityGrid"' not in html


def test_login_showcase_hub_no_card_chrome() -> None:
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert "login-hub-node" in html
    assert "loginHubHex" in html
    assert 'id="loginCapabilityGrid"' not in html
    assert "login-modules-composite.jpg" not in html
    hub_css = css.split("Hub graphic", 1)[-1].split(".login-capability-grid", 1)[0]
    assert "background: transparent" in hub_css
    assert ".login-module-detail" in hub_css
    assert "stroke-dasharray" not in hub_css
    assert "login-hub-spokes path" in hub_css
    for label in ("CMDB", "Monitoring", "ITSM", "Service", "Portal", "SecureOps", "Configuration"):
        assert label in html


def test_login_hub_hex_architecture() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    assert 'polygon id="loginHubHex"' in html
    assert "login-hub-node-content" in html
    assert "<path data-module=" in html
    assert "<line data-module=" not in html
    assert "loginHubSpokeGrad" in html
    assert "has-selection" in js
    assert ".login-hub-spokes path" in js or "login-hub-spokes path" in js
    assert "min(100%, 980px)" in css or "min(100%, 1120px)" in css
    assert "login-curve-glow" in css


def test_login_hub_interactive_behaviour() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert 'aria-describedby="loginModuleDetail"' in html
    assert 'aria-label="CMDB — Configuration Management Database"' in html
    assert "Unified view of servers, networks and applications" in html
    assert "mouseenter" in js
    assert "openModuleIntro" in js
    assert "resetToDefault" in js or 'DEFAULT_MODULE = "cmdb"' in js
    assert "Enter" in js and " " in js  # Space/Space
    assert "login-curve-glow" in css
    assert "login-hub-pulse" in css
    assert "240ms" in css or "260ms" in css
    assert "prefers-reduced-motion" in css
    assert "has-selection" in css


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


def test_login_module_config_covers_spec() -> None:
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    for phrase in (
        "Centralised infrastructure inventory",
        "Manage servers, operating systems, middleware, databases and applications",
        "Visualise infrastructure relationships and dependencies",
        "Incident Management",
        "Change Management",
        "Problem Management",
        "Service requests and ticket lifecycle management",
        "CPU, memory, disk and network utilisation",
        "Centralised service request portal",
        "Access service catalogue and knowledge resources",
        "Role-based access control",
        "Configure integrations and platform settings",
        "Manage tenant-level settings",
    ):
        assert phrase in js


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
    assert "body.is-login" in css
