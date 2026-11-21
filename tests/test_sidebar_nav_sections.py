"""Sidebar IA — CMDB / Monitoring / ITSM expandable sections (0.71.0)."""

from __future__ import annotations

from pathlib import Path

from app import __version__

from tests.frontend_paths import FRONTEND_INDEX

CMDB_JS = Path("frontend/static/js/cmdb.js")
ITSM_INDEX_JS = Path("frontend/static/js/itsm/index.js")
MONITOR_INDEX_JS = Path("frontend/static/js/monitor/index.js")
CMDB_CSS = Path("frontend/static/css/cmdb.css")


def test_version_bump_for_sidebar_cmdb_dashboard() -> None:
    assert __version__ == "0.71.0"


def test_frontend_sidebar_section_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.71.0"' in html

    # No thin Operations section (Dashboard moved under CMDB).
    assert 'id="navOperationsSection"' not in html
    assert 'data-nav-collapse="operations"' not in html
    assert 'id="navOperationsGroup"' not in html
    assert 'data-nav-group="operations"' not in html
    assert ">Operations<" not in html

    # CMDB — Dashboard first, then typed inventory + catalog (no File Monitoring / Diagnostics).
    assert 'id="navCmdbSection"' in html
    assert 'data-nav-collapse="cmdb"' in html
    assert 'id="navCmdbGroup"' in html
    assert 'data-nav-group="cmdb"' in html
    cmdb_group_i = html.index('id="navCmdbGroup"')
    custom_i = html.index('id="navCustomTablesSection"')
    dash_i = html.index('data-tab="dashboard"')
    assert cmdb_group_i < dash_i < custom_i
    # Label is CMDB Dashboard; deep-link tab id stays dashboard.
    assert "CMDB Dashboard" in html[dash_i : dash_i + 500]
    servers_i = html.index('data-tab="servers"')
    assert dash_i < servers_i < custom_i

    for tab in (
        "servers",
        "network",
        "applications",
        "middleware",
        "databases",
        "relationships",
        "dependencies",
    ):
        marker = f'data-tab="{tab}"'
        pos = html.index(marker)
        assert cmdb_group_i < pos < custom_i, tab

    # M8: CMDB File Monitoring / Diagnostics redirect stubs removed.
    assert "cmdb-redirect-file-monitoring" not in html
    assert "cmdb-redirect-diagnostics" not in html

    # Real File Monitoring / Diagnostics are under Monitoring, not CMDB.
    mon_group_i = html.index('id="navMonitoringGroup"')
    itsm_i = html.index('id="navItsmSection"')
    for tab in ("file-monitoring", "diagnostics"):
        pos = html.index(f'data-tab="{tab}"')
        assert mon_group_i < pos < itsm_i, tab
        assert not (cmdb_group_i < pos < custom_i), tab

    # Custom tables — expandable; dynamic entity tables only.
    assert 'data-nav-collapse="custom-tables"' in html
    assert 'id="navCustomTables"' in html
    assert 'data-nav-group="custom-tables"' in html

    # Monitoring — expandable; permission-gated; Dashboard first.
    assert 'id="navMonitoringSection"' in html
    assert 'data-nav-collapse="monitoring"' in html
    assert 'data-monitor-nav-group="1"' in html
    assert "Monitoring Dashboard" in html

    # ITSM — expandable; permission-gated; ITSM Dashboard mirrors CMDB Dashboard placement.
    assert 'id="navItsmSection"' in html
    assert 'data-nav-collapse="itsm"' in html
    assert 'id="navItsmGroup"' in html
    assert 'data-nav-group="itsm"' in html
    assert 'data-itsm-nav-group="1"' in html
    assert "ITSM Dashboard" in html

    # Configuration + Administration — click-to-expand section headers.
    assert 'id="navConfigurationSection"' in html
    assert 'data-nav-collapse="configuration"' in html
    assert 'id="navConfigurationGroup"' in html
    assert 'data-nav-group="configuration"' in html
    assert 'id="navAdministrationSection"' in html
    assert 'data-nav-collapse="administration"' in html
    assert 'id="navAdministrationGroup"' in html
    assert 'data-nav-group="administration"' in html

    # Order: CMDB → Custom tables → Monitoring → ITSM → Configuration → Administration
    cmdb_i = html.index('id="navCmdbSection"')
    mon_i = html.index('id="navMonitoringSection"')
    itsm_group_i = html.index('id="navItsmGroup"')
    config_i = html.index('id="navConfigurationSection"')
    admin_i = html.index('id="navAdministrationSection"')
    assert cmdb_i < custom_i < mon_i < itsm_i < itsm_group_i < config_i < admin_i

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

    # Configuration + Administration children stay in their groups.
    config_group_i = html.index('id="navConfigurationGroup"')
    admin_group_i = html.index('id="navAdministrationGroup"')
    for tab in ("custom", "custom-tables", "columns"):
        pos = html.index(f'data-tab="{tab}"')
        assert config_group_i < pos < admin_i, tab
    for tab in ("users", "roles", "organizations", "plans", "settings", "audit"):
        pos = html.index(f'data-tab="{tab}"')
        assert admin_group_i < pos, tab

    # No bare (non-toggle) section headers remain in the primary nav.
    bare = [line for line in html.splitlines() if '<div class="nav-section">' in line]
    assert bare == [], bare

    # Panel copy no longer says Operations-only home.
    assert "Operations dashboard" not in html
    assert "CMDB dashboard" in html


def test_nav_accordion_js_and_css_markers() -> None:
    cmdb = CMDB_JS.read_text(encoding="utf-8")
    assert 'NAV_EXPAND_KEY = "svrmon24.nav.expand"' in cmdb
    assert "NAV_EXPAND_DEFAULTS" in cmdb
    assert "NAV_TAB_GROUP" in cmdb
    assert "operations: true" not in cmdb
    assert 'dashboard: "cmdb"' in cmdb
    assert "cmdb: true" in cmdb
    assert "monitoring: true" in cmdb
    assert '"monitor-dashboard": "monitoring"' in cmdb
    assert "configuration: true" in cmdb
    assert "administration: true" in cmdb
    assert "initNavAccordions" in cmdb
    assert "expandNavGroupForTab" in cmdb
    assert "setNavGroupExpanded" in cmdb
    assert 'title: "CMDB Dashboard"' in cmdb

    itsm = ITSM_INDEX_JS.read_text(encoding="utf-8")
    assert 'getElementById("navItsmGroup")' in itsm
    assert "group.hidden = !showSection" in itsm

    mon = MONITOR_INDEX_JS.read_text(encoding="utf-8")
    assert 'getElementById("navMonitoringGroup")' in mon
    assert "applyMonitorNavGates" in mon

    css = CMDB_CSS.read_text(encoding="utf-8")
    assert ".nav-section-toggle" in css
    assert ".nav-group.is-collapsed" in css
    assert ".nav-chevron" in css
