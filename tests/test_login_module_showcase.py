"""Login gate — capability-card showcase + Option B overview (0.99.11)."""

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
    assert 'id="loginModuleCaption"' in html
    assert 'id="loginCapabilityGrid"' in html
    assert 'id="loginOverviewModal"' in html
    assert 'id="btnLoginWatchOverview"' in html
    assert 'id="loginModulesVisual"' in html
    assert 'id="loginModulesComposite"' in html
    assert "login-modules-composite.jpg" in html
    assert "Explore SVRMON24 modules" not in html
    assert "login-module-detail" not in html
    assert 'id="loginModuleRail"' not in html
    assert 'id="loginPreviewViewport"' not in html
    assert "login-panels/panel-" not in html
    assert "login-preview-tilt" not in html
    assert "setActiveCard" in js
    assert "openOverviewModal" in js
    assert "login-cap-play" in js
    assert "loginModulesVisual" in js
    assert "loginModuleUses" not in js
    assert "setActiveModule" not in js
    assert "prefers-reduced-motion" in js or "prefersReducedMotion" in js
    for mod in ("cmdb", "dashboard", "monitoring", "itsm", "admin"):
        assert f'module: "{mod}"' in js
    assert ".login-capability-grid" in css
    assert ".login-cap-play" in css
    assert ".login-watch-overview" in css
    assert ".login-overview-modal" in css
    assert ".login-modules-visual" in css
    assert ".login-modules-composite" in css
    assert ".login-preview-caption" in css
    assert "login-module-detail" not in css
    assert "prefers-reduced-motion" in css
    assert f"login-showcase.js?v={__version__}" in html
    assert (FRONTEND_STATIC / "assets" / "brand" / "modules-overview-loop.mp4").is_file()
    assert (FRONTEND_STATIC / "assets" / "brand" / "modules-overview-poster.png").is_file()
    assert (FRONTEND_STATIC / "assets" / "brand" / "login-modules-composite.jpg").is_file()
    assert not (FRONTEND_STATIC / "assets" / "login-panels").exists()


def test_login_showcase_intro_stack() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    assert 'class="login-showcase-intro"' in html
    intro_idx = html.index("login-showcase-intro")
    hero_idx = html.index("loginShowcaseStage")
    grid_idx = html.index("loginCapabilityGrid")
    assert intro_idx < hero_idx < grid_idx
    assert "Watch overview" in html
    assert ".login-showcase-intro" in css
    assert "login-showcase-copy" not in html
    assert "login-module-chip" not in html.split('id="loginGate"', 1)[1].split('id="appShell"', 1)[0]


def test_login_showcase_flat_modules_visual() -> None:
    """Hero uses a flat composed illustration — no tilted product screenshot."""
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert "login-modules-visual" in html
    assert "login-modules-composite" in html
    assert "login-preview-tilt" not in html
    assert "login-dashboard-tilt" not in html
    assert "object-fit: contain" in css
    assert ".login-modules-composite" in css
    assert "login-modules-composite.jpg" in html
    # Active hero markup must not use the old tilted shot chrome.
    gate = html.split('id="loginGate"', 1)[1].split('id="appShell"', 1)[0]
    assert "rotateY" not in gate
    assert "login-preview-viewport--shots" not in gate
    reduced = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".login-modules-visual" in reduced
    for label in ("CMDB", "Monitoring", "ITSM", "Service Portal", "SecureOps", "Configuration"):
        assert label in html


def test_login_card_play_opens_overview_without_autoplay() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "login-showcase.js").read_text(encoding="utf-8")
    assert 'id="loginOverviewVideo"' in html
    video_snip = html.split('id="loginOverviewVideo"', 1)[1].split("</video>", 1)[0].lower()
    assert "autoplay" not in video_snip
    assert 'preload="metadata"' in html
    assert "openOverviewModal(card.seek)" in js
    assert "btnLoginWatchOverview" in js
    assert "video.play" in js
    # No page-load autoplay: play only inside openOverviewModal
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
