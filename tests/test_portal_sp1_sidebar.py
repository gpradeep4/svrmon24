"""Service Portal SP1 — expandable sidebar + stub panels (0.99.11)."""

from __future__ import annotations

from pathlib import Path

from app import __version__

from tests.frontend_paths import FRONTEND_INDEX

CMDB_JS = Path("frontend/static/js/cmdb.js")
PORTAL_INDEX_JS = Path("frontend/static/js/portal/index.js")
PORTAL_CSS = Path("frontend/static/css/portal.css")


def test_version_bump_for_portal_sp1() -> None:
    assert __version__ == "0.99.11"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.11"' in html
    assert "portal.css?v=0.99.11" in html
    assert "portal/index.js?v=0.99.11" in html


def test_portal_sidebar_section_and_order() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="navPortalSection"' in html
    assert 'data-nav-collapse="portal"' in html
    assert 'id="navPortalGroup"' in html
    assert 'data-nav-group="portal"' in html
    assert 'data-portal-nav-group="1"' in html
    assert "Service Portal" in html
    assert "Catalog" in html

    itsm_i = html.index('id="navItsmSection"')
    portal_i = html.index('id="navPortalSection"')
    portal_group_i = html.index('id="navPortalGroup"')
    config_i = html.index('id="navConfigurationSection"')
    assert itsm_i < portal_i < portal_group_i < config_i

    ordered = [
        "sp-catalog",
        "sp-request-new",
        "sp-my-requests",
        "sp-approvals",
        "sp-executions",
        "sp-vuln-reports",
        "sp-catalog-admin",
    ]
    positions = [html.index(f'data-tab="{tab}"') for tab in ordered]
    assert positions == sorted(positions)
    for tab, pos in zip(ordered, positions, strict=True):
        assert portal_group_i < pos < config_i, tab
        assert 'data-portal-nav="1"' in html[pos - 120 : pos + 160]

    assert 'data-portal-perm="sp:catalog:read"' in html
    assert 'data-portal-perm="sp:request:create"' in html
    assert 'data-portal-perm="sp:request:read"' in html
    assert 'data-tab="sp-approvals"' in html
    assert "Change status" in html
    assert 'data-portal-perm="sp:request:read"' in html
    assert 'data-portal-perm="sp:execution:read"' in html
    assert 'data-portal-perm="sp:catalog:admin"' in html
    assert "Approvals inbox" not in html


def test_portal_stub_panels_and_simulated_banner() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    for tab in (
        "sp-catalog",
        "sp-request-new",
        "sp-my-requests",
        "sp-approvals",
        "sp-executions",
        "sp-vuln-reports",
        "sp-catalog-admin",
    ):
        assert f'id="tab-{tab}"' in html
        assert 'data-portal-module="1"' in html
    assert 'data-portal-simulated="1"' in html
    assert "SIMULATED" in html[html.index('id="tab-sp-catalog"') :]
    assert "portal/vuln.js" in html


def test_portal_nav_js_and_css_markers() -> None:
    cmdb = CMDB_JS.read_text(encoding="utf-8")
    assert "portal: true" in cmdb
    assert '"sp-catalog": "portal"' in cmdb
    assert "SVRMON24Portal" in cmdb
    assert "applyPortalNavGates" in cmdb
    assert "registerPortalHooks" in cmdb

    portal = PORTAL_INDEX_JS.read_text(encoding="utf-8")
    assert 'getElementById("navPortalGroup")' in portal
    assert "applyPortalNavGates" in portal
    assert "sp:catalog:read" in portal

    assert PORTAL_CSS.is_file()
    css = PORTAL_CSS.read_text(encoding="utf-8")
    assert "portal-panel" in css
