"""Login gate — premium interactive central hub + Option B overview (0.99.14)."""

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
    assert 'id="loginHubSpokes"' in html
    assert 'id="loginHubNodes"' in html
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
    assert "computePositions" in js
    assert "enabledModules" in js
    assert "renderHub" in js
    assert "DEFAULT_MODULE" in js
    assert 'DEFAULT_MODULE = "cmdb"' in js
    assert "capabilities:" in js
    assert "short_description:" in js
    assert "display_order:" in js
    assert "enabled: true" in js
    assert "enabled: false" in js
    assert "Centralised infrastructure inventory" in js
    assert "Role-based access control" in js
    assert "buildCards" not in js
    for mod in ("cmdb", "monitoring", "itsm", "portal", "secureops"):
        assert f'id: "{mod}"' in js
    assert 'id: "config"' in js
    assert "enabled: false" in js
    # Configuration must not be hard-coded into the login hub shell
    assert 'data-module="config"' not in html
    assert ".login-hub-node" in css
    assert "login-hub-pulse" in css
    assert "login-curve-glow" in css
    assert (
        "scale(1.06)" in css
        or "scale(1.05)" in css
        or "scale(1.07)" in css
        or "scale(1.04)" in css
    )
    assert ".login-module-detail-bullets" in css
    assert ".login-module-intro" in css
    assert 'preserveAspectRatio="xMidYMid meet"' in html
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
    assert "loginHubHex" in html
    assert 'id="loginCapabilityGrid"' not in html
    assert "login-modules-composite.jpg" not in html
    hub_css = css.split("Hub graphic", 1)[-1].split(".login-capability-grid", 1)[0]
    assert "background: transparent" in hub_css
    assert ".login-module-detail" in hub_css
    # Permanent spoke dash chrome is forbidden; draw-in uses inline JS dash metrics
    assert "stroke-dasharray" not in hub_css
    assert ".login-hub-temp-connection" in hub_css
    assert "Configuration" not in html.split('id="loginHubHotspots"', 1)[1].split("login-module-detail", 1)[0]


def test_login_hub_hex_architecture() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    assert 'polygon id="loginHubHex"' in html
    assert "login-hub-nodes" in html
    assert "<line data-module=" not in html
    assert "loginHubSpokeGrad" in html
    assert "has-selection" in js
    assert "computePositions" in js
    assert "count <= 6" in js or "count <= 10" in js
    assert "min(100%, 980px)" in css or "min(100%, 1120px)" in css or "min(100%, 1040px)" in css
    assert "login-curve-glow" in css
    # Spokes stretch with hub box so % coords match node --hx/--hy
    assert 'id="loginHubSpokes"' in html
    assert 'preserveAspectRatio="none"' in html.split('id="loginHubSpokes"', 1)[1].split(">", 1)[0]
    # Layering: spokes behind core + nodes
    hub_block = html.split('id="loginHubHotspots"', 1)[1].split("login-module-detail", 1)[0]
    assert hub_block.index("loginHubSpokes") < hub_block.index("login-hub-core")
    assert hub_block.index("login-hub-core") < hub_block.index("loginHubNodes")
    assert "z-index: 0" in css.split(".login-hub-spokes", 1)[1].split("}", 1)[0]
    assert "z-index: 1" in css.split(".login-hub-core", 1)[1].split("}", 1)[0]
    assert "z-index: 2" in css.split(".login-hub-nodes", 1)[1].split("}", 1)[0]


def test_login_hub_connection_geometry() -> None:
    """Temporary selected-module edge-clipped SVG: direction → hex boundary → cubic."""
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert "hexBoundaryIntersection" in js
    assert "connectionPath" in js
    assert "edgeCurvePath" in js
    assert "updateConnections" in js
    assert "measureHexInView" in js
    assert "observeHubResize" in js
    assert "ResizeObserver" in js
    assert "hexVertices" in js
    assert "raySegmentIntersection" in js
    # Single temporary connection — never five permanent module paths
    assert 'id="loginHubTempConnection"' in js or 'loginHubTempConnection' in js
    assert "One temporary connection" in js or "login-hub-temp-connection" in js
    assert "permanent" in js.lower()
    # Must clip to boundaries — module edge → hub edge
    assert "hexBoundaryIntersection(hub.cx, hub.cy, hub.hw, hub.hh, dx, dy)" in js
    assert "hexBoundaryIntersection(node.cx, node.cy, node.hw, node.hh, -dx, -dy)" in js
    assert "edgeCurvePath(nodeEdge.x, nodeEdge.y, hubEdge.x, hubEdge.y)" in js
    # No CSS translate/margin offset hacks on spokes
    spokes_css = css.split(".login-hub-spokes", 1)[1].split(".login-hub-core", 1)[0]
    assert "translate(" not in spokes_css
    assert "margin-left" not in spokes_css
    assert "top:" not in spokes_css or "inset: 0" in spokes_css
    # Temporary connection visible only when selected
    assert ".login-hub-temp-connection" in css
    assert ".login-hub-temp-connection.is-visible" in css
    # Exported for future modules / diagnostics
    assert "updateConnections," in js
    assert "hexBoundaryIntersection," in js
    assert "connectionPath," in js


def test_login_hub_interactive_behaviour() -> None:
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert "CMDB — Configuration Management Database" in js
    assert "Unified view of servers, networks and applications" in js
    # Sticky selection via click / focus / touch — hover is CSS-only
    assert "pointerdown" in js
    assert "setActiveModule" in js
    assert "illuminateHub" in js
    assert "is-illuminated" in js or "is-illuminated" in css
    assert "openModuleIntro" in js
    assert "resetToDefault" in js or 'DEFAULT_MODULE = "cmdb"' in js
    assert "Enter" in js and " " in js
    assert "login-curve-glow" in css
    assert "login-hub-pulse" in css
    assert "login-hub-illuminate" in css
    assert "240ms" in css or "260ms" in css or "280ms" in css
    assert "prefers-reduced-motion" in css
    assert "has-selection" in css
    # Palette anchors
    assert "#315FEA" in html_or_css_or_js(css, js)
    assert "#7545E8" in css or "#7545E8" in js
    assert "#172554" in css
    assert "#F2F3FF" in css or "#F2F3FF" in (
        FRONTEND_INDEX.read_text(encoding="utf-8")
    )


def html_or_css_or_js(css: str, js: str) -> str:
    return css + js


def test_login_premium_hub_no_permanent_strings() -> None:
    """Acceptance: no five permanent connecting strings; temp connection only."""
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert "loginHubTempConnection" in js
    assert "login-hub-temp-connection" in css
    # renderHub must not append a path per module
    render = js.split("function renderHub", 1)[1].split("function observeHubResize", 1)[0]
    assert "mods.forEach" in render
    assert 'createElementNS("http://www.w3.org/2000/svg", "path")' in render
    assert render.count('createElementNS("http://www.w3.org/2000/svg", "path")') == 1
    assert "#315FEA" in html
    assert "#7545E8" in html
    assert "#F2F3FF" in html


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
    ):
        assert phrase in js
    # Config capabilities remain in MODULES but disabled for showcase
    assert 'id: "config"' in js
    assert "Configure integrations and platform settings" in js


def test_login_five_modules_enabled_only() -> None:
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert "enabledModules" in js
    assert "m.enabled" in js
    assert 'id="loginHubNodes"' in html
    assert "navConfigurationGroup" in html  # real app Config nav kept


def test_version_bump_for_login_premium_enterprise_ui() -> None:
    assert __version__ == "0.99.14"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.14"' in html
    assert 'content="login-enterprise-v23"' in html


def test_login_premium_enterprise_detail_panel_not_clipped() -> None:
    """Description panel is a frosted card and stays visible (flex-shrink: 0)."""
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    detail = css.split(".login-module-detail {", 1)[1].split(".login-module-detail.is-swapping", 1)[0]
    assert "flex-shrink: 0" in detail
    assert "backdrop-filter" in detail
    assert "rgba(255, 255, 255" in detail or "rgba(255,255,255" in detail
    assert "align-self: flex-start" in detail
    # Desktop showcase column must allow hub shrink so the panel is never clipped
    assert "flex: 1 1 auto" in css
    assert "min-height: 0" in css
    assert "count === 5 ? 36" in js
    assert "Unified view of servers, networks and applications." in js


def test_login_fullbleed_layout_css() -> None:
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="loginGate"' in html
    assert "minmax(0, 1fr) minmax(380px, 440px)" in css
    assert "#loginGate.login-gate-split" in css
    assert "body.is-login" in css
