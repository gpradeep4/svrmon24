"""Monitoring M2 — expandable Monitoring sidebar + dashboard shell (0.92.0)."""

from __future__ import annotations

from pathlib import Path

from app import __version__

from tests.frontend_paths import FRONTEND_INDEX

CMDB_JS = Path("frontend/static/js/cmdb.js")
MONITOR_INDEX_JS = Path("frontend/static/js/monitor/index.js")
MONITOR_DASH_JS = Path("frontend/static/js/monitor/dashboard.js")
MONITOR_CSS = Path("frontend/static/css/monitor.css")


def test_version_bump_for_monitor_m2() -> None:
    assert __version__ == "0.92.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.92.0"' in html
    assert "monitor.css?v=0.92.0" in html
    assert "monitor/index.js?v=0.92.0" in html
    assert "monitor/dashboard.js?v=0.92.0" in html


def test_monitoring_sidebar_section_and_order() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")

    assert 'id="navMonitoringSection"' in html
    assert 'data-nav-collapse="monitoring"' in html
    assert 'id="navMonitoringGroup"' in html
    assert 'data-nav-group="monitoring"' in html
    assert 'data-monitor-nav-group="1"' in html
    assert "Monitoring Dashboard" in html

    cmdb_i = html.index('id="navCmdbSection"')
    custom_i = html.index('id="navCustomTablesSection"')
    mon_i = html.index('id="navMonitoringSection"')
    mon_group_i = html.index('id="navMonitoringGroup"')
    itsm_i = html.index('id="navItsmSection"')
    assert cmdb_i < custom_i < mon_i < mon_group_i < itsm_i

    # Dashboard first under Monitoring.
    dash_i = html.index('data-tab="monitor-dashboard"')
    assert mon_group_i < dash_i < itsm_i
    assert "Monitoring Dashboard" in html[dash_i : dash_i + 400]

    ordered = [
        "monitor-dashboard",
        "monitor-servers",
        "monitor-network",
        "monitor-applications",
        "monitor-middleware",
        "monitor-databases",
        "monitor-logs",
        "file-monitoring",
        "diagnostics",
        "monitor-alerts",
        "monitor-agents",
    ]
    positions = [html.index(f'data-tab="{tab}"') for tab in ordered]
    assert positions == sorted(positions)
    for tab, pos in zip(ordered, positions, strict=True):
        assert mon_group_i < pos < itsm_i, tab
        assert 'data-monitor-nav="1"' in html[pos - 120 : pos + 160]

    assert 'data-monitor-perm="monitor:dashboard:read"' in html
    assert 'data-monitor-perm="monitor:targets:read"' in html
    assert 'data-monitor-perm="monitor:logs:read"' in html
    assert 'data-monitor-perm="monitor:alerts:read"' in html
    assert 'data-monitor-perm="monitor:admin"' in html[html.index('data-tab="monitor-agents"') : html.index('data-tab="monitor-agents"') + 200]


def test_file_monitoring_and_diagnostics_moved_from_cmdb() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    cmdb_group_i = html.index('id="navCmdbGroup"')
    custom_i = html.index('id="navCustomTablesSection"')
    mon_group_i = html.index('id="navMonitoringGroup"')
    itsm_i = html.index('id="navItsmSection"')

    # Real tabs live under Monitoring (stable ids).
    fm_i = html.index('data-tab="file-monitoring"')
    diag_i = html.index('data-tab="diagnostics"')
    assert mon_group_i < fm_i < itsm_i
    assert mon_group_i < diag_i < itsm_i

    # M8: CMDB redirect stubs removed.
    assert "cmdb-redirect-file-monitoring" not in html
    assert "cmdb-redirect-diagnostics" not in html
    assert "data-cmdb-monitor-redirect" not in html
    # Real File Monitoring / Diagnostics are not under CMDB.
    assert not (cmdb_group_i < fm_i < custom_i)
    assert not (cmdb_group_i < diag_i < custom_i)


def test_monitor_dashboard_shell_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="tab-monitor-dashboard"' in html
    assert 'data-monitor-simulated="1"' in html
    assert 'id="monitorDashBanner"' in html
    assert 'id="btnRefreshMonitorDash"' in html
    assert 'id="monitorDashLiveProbes"' in html
    for tab in (
        "monitor-servers",
        "monitor-network",
        "monitor-applications",
        "monitor-middleware",
        "monitor-databases",
        "monitor-logs",
        "monitor-alerts",
        "monitor-agents",
    ):
        assert f'id="tab-{tab}"' in html


def test_monitor_nav_js_css_markers() -> None:
    cmdb = CMDB_JS.read_text(encoding="utf-8")
    assert 'monitoring: true' in cmdb
    assert '"monitor-dashboard": "monitoring"' in cmdb
    assert 'diagnostics: "monitoring"' in cmdb
    assert '"file-monitoring": "monitoring"' in cmdb
    assert "cmdb-redirect-file-monitoring" not in cmdb
    assert "expandNavGroupForTab" in cmdb
    assert 'tabName.startsWith("monitor-")' in cmdb
    assert "SVRMON24Monitor?.applyMonitorNavGates" in cmdb
    assert "SVRMON24Monitor?.registerMonitorHooks" in cmdb
    assert "loadMonitorDashboard" in cmdb

    mon = MONITOR_INDEX_JS.read_text(encoding="utf-8")
    assert "applyMonitorNavGates" in mon
    assert "anyMonitorPermission" in mon
    assert "file_monitoring:read" in mon
    assert "monitor:files:read" in mon
    assert "diagnostics:read" in mon

    dash = MONITOR_DASH_JS.read_text(encoding="utf-8")
    assert "/api/monitor/meta" in dash
    assert "live_probes" in dash

    css = MONITOR_CSS.read_text(encoding="utf-8")
    assert ".monitor-kpi-row" in css
    assert ".monitor-panel" in css
