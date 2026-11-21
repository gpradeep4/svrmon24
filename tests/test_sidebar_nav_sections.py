"""Sidebar IA — separate CMDB / Custom tables / expandable ITSM (0.60.0)."""

from __future__ import annotations

from pathlib import Path

from app import __version__

from tests.frontend_paths import FRONTEND_INDEX

CMDB_JS = Path("frontend/static/js/cmdb.js")
ITSM_INDEX_JS = Path("frontend/static/js/itsm/index.js")
CMDB_CSS = Path("frontend/static/css/cmdb.css")


def test_version_bump_for_sidebar_itsm_section() -> None:
    assert __version__ == "0.60.0"


def test_frontend_sidebar_section_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.60.0"' in html

    # Distinct section headers / groups — ITSM must not sit under Custom tables.
    assert 'id="navCustomTablesSection"' in html
    assert 'data-nav-collapse="custom-tables"' in html
    assert 'id="navCustomTables"' in html
    assert 'data-nav-group="custom-tables"' in html

    assert 'id="navCmdbSection"' in html
    assert ">CMDB<" in html
    assert 'id="navCmdbGroup"' in html
    assert 'data-tab="relationships"' in html
    assert 'data-tab="dependencies"' in html
    assert 'data-tab="diagnostics"' in html
    assert 'data-tab="file-monitoring"' in html

    assert 'id="navItsmSection"' in html
    assert 'data-nav-collapse="itsm"' in html
    assert 'id="navItsmGroup"' in html
    assert 'data-nav-group="itsm"' in html
    assert 'data-itsm-nav-group="1"' in html

    # Order: Custom tables section → CMDB → ITSM → Configuration
    custom_i = html.index('id="navCustomTablesSection"')
    cmdb_i = html.index('id="navCmdbSection"')
    itsm_i = html.index('id="navItsmSection"')
    itsm_group_i = html.index('id="navItsmGroup"')
    config_i = html.index('<div class="nav-section">Configuration</div>')
    assert custom_i < cmdb_i < itsm_i < itsm_group_i < config_i

    # ITSM items live inside the ITSM group, not after Configuration.
    for tab in (
        "itsm-dashboard",
        "itsm-incidents",
        "itsm-changes",
        "itsm-problems",
        "itsm-approvals",
        "itsm-workflows",
        "itsm-sla",
        "itsm-knowledge",
        "itsm-notifications",
        "itsm-groups",
        "itsm-reports",
    ):
        marker = f'data-tab="{tab}"'
        pos = html.index(marker)
        assert itsm_group_i < pos < config_i, tab
        assert 'data-itsm-nav="1"' in html[pos - 80 : pos + 120]


def test_nav_accordion_js_and_css_markers() -> None:
    cmdb = CMDB_JS.read_text(encoding="utf-8")
    assert 'NAV_EXPAND_KEY = "svrmon24.nav.expand"' in cmdb
    assert "initNavAccordions" in cmdb
    assert "expandNavGroupForTab" in cmdb
    assert "setNavGroupExpanded" in cmdb

    itsm = ITSM_INDEX_JS.read_text(encoding="utf-8")
    assert 'getElementById("navItsmGroup")' in itsm
    assert "group.hidden = !showSection" in itsm

    css = CMDB_CSS.read_text(encoding="utf-8")
    assert ".nav-section-toggle" in css
    assert ".nav-group.is-collapsed" in css
    assert ".nav-chevron" in css
