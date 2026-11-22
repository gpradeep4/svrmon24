"""Monitoring module metadata — SIMULATED default; live gates fail-closed."""

from __future__ import annotations

from typing import Any

from ...config import Settings, get_settings
from ..models.literals import DOMAINS, EXECUTION_MODES, WATCH_MODES
from . import live_gates as live_gates_service
from . import mtls as mtls_service

EXECUTION_MODE = "SIMULATED"
DATA_SOURCE = "SYNTHETIC_DEMO"
# Product lock: both collect modes in model/meta from day one; live still gated.
COLLECT_MODES: tuple[str, ...] = ("agentless", "agent")
OS_FAMILIES: tuple[str, ...] = ("linux", "windows", "macos", "unix")
NETWORK_TARGET_KINDS: tuple[str, ...] = (
    "switch",
    "router",
    "firewall",
    "load_balancer",
    "access_point",
    "other_network",
)
BANNER_SIMULATED = (
    "SIMULATED / SYNTHETIC_DEMO — Monitoring does not run live probes or agents. "
    "Target health, metric samples, and log streams are synthetic; live probes stay off."
)
BANNER_LIVE_GATED = (
    "Live monitoring gates are ON for this tenant — series may be SIMULATED or LIVE. "
    "SIMULATED seed / simulate-tick remain available; agentless HTTP/TCP/ICMP/SNMP "
    "polls require poller/allowlist (L1/L2); HTTP log ingest (+ optional syslog) "
    "writes LIVE log_events when ingest gates are on (L3); agent enroll/register "
    "requires agent opt-in (L4); agents push metrics/logs/file-events (L5); "
    "file watches support watch_mode AGENT / AGENTLESS_POLL (L6)."
)
# Back-compat alias for SIMULATED services (dashboard / targets / logs / alerts).
BANNER = BANNER_SIMULATED


def module_meta(
    *,
    settings: Settings | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Stable meta payload for ``GET /api/monitor/meta``."""
    # Lazy import avoids logs → meta → agent_ingest → ingest → logs cycles.
    from . import agent_ingest as agent_ingest_service

    cfg = settings or get_settings()
    tid = (tenant_id or "").strip()
    gates: dict[str, Any]
    retention_tier = "hot"
    if tid:
        gates = live_gates_service.live_gates(tenant_id=tid, settings=cfg)
        retention_tier = live_gates_service.tenant_live_settings(tid)[
            "monitor_retention_tier"
        ]
    else:
        gates = {
            "platform_enabled": bool(cfg.monitor_live_probes_enabled),
            "tenant_opt_in": False,
            "agentless": False,
            "agent": False,
            "auto_incident": False,
            "syslog_bound": False,
            "poller_enabled": False,
            "http_ingest": False,
        }
    live_probes = bool(gates.get("platform_enabled") and gates.get("tenant_opt_in"))
    banner = BANNER_LIVE_GATED if live_probes else BANNER_SIMULATED
    return {
        "module": "monitoring",
        "execution_mode": EXECUTION_MODE,
        "execution_modes": list(EXECUTION_MODES),
        "data_source": DATA_SOURCE,
        "demo_only": not live_probes,
        "live_probes": live_probes,
        "live_gates": gates,
        "retention_tier": retention_tier,
        "collect_modes": list(COLLECT_MODES),
        "domains": list(DOMAINS),
        "os_families": list(OS_FAMILIES),
        "network_target_kinds": list(NETWORK_TARGET_KINDS),
        "banner": banner,
        "notice": (
            "Monitoring defaults to SIMULATED. Sync targets from CMDB (API client "
            "only); domain health views stamp AGENTLESS/AGENT collect modes for "
            "all OS families and networking kinds. Log streams are searchable "
            "SIMULATED events by default; LIVE HTTP ingest "
            "(`/api/monitor/ingest/logs`) and optional syslog bind write "
            "LIVE rows when gates are on. simulate-tick is admin-only. Alert "
            "rules evaluate thresholds / log matches / file changes on "
            "synthetic data by default. Optional alert→ITSM auto-create (L8) "
            "requires platform live + tenant monitor_live_opt_in + "
            "monitor_auto_incident_opt_in (default OFF) and rule.auto_incident; "
            "creates via ITSM service (actor=monitor-auto-incident), audited, "
            "daily-capped — never writes ITSM Mongo from Monitoring. "
            "Suggest-incident draft→Apply remains for tenants with flag off. "
            "No AI auto-approve of unrelated flows. Dashboard aggregates come "
            "from monitor collections. Live probes require platform "
            "MONITOR_LIVE_PROBES_ENABLED plus tenant monitor_live_opt_in "
            "(fail-closed). Agents register via enrollment codes (token "
            "hash-at-rest; optional mTLS sketch) and push LIVE "
            "metrics/logs/file-events with ingest cursors (L5). File watches "
            "expose watch_mode SIMULATED|AGENT|AGENTLESS_POLL (L6); agentless "
            "poll uses HTTP ETag/checksum where feasible. Middleware is a "
            "first-class Monitoring domain (L7) synced from CMDB Middleware "
            "CIs. File Monitoring and Diagnostics are under Monitoring "
            "(CMDB redirect stubs removed in M8)."
        ),
        "watch_modes": list(WATCH_MODES),
        "agent_ingest_contract": agent_ingest_service.os_contract_meta(),
        "log_sources": ["agentless", "agent", "simulated"],
        "log_severities": [
            "debug",
            "info",
            "warning",
            "error",
            "critical",
        ],
        "alert_condition_types": ["threshold", "log_match", "file_change"],
        "alert_statuses": ["firing", "acked", "resolved"],
        "alert_severities": ["info", "warning", "error", "critical"],
        "agent_statuses": ["pending", "active", "revoked", "stale"],
        "agent_mtls": mtls_service.mtls_sketch_meta(cfg),
        "database": cfg.monitor_database_name,
        "monitor_database": cfg.monitor_database_name,
        "deprecations": {
            "cmdb_file_monitoring_nav": (
                "Removed — use Monitoring → File Monitoring "
                "(#tab=file-monitoring)."
            ),
            "cmdb_diagnostics_nav": (
                "Removed — use Monitoring → Diagnostics (#tab=diagnostics)."
            ),
            "api_file_monitoring": (
                "Compat path /api/file-monitoring/* remains; prefer "
                "/api/monitor/files when available. Data lives in "
                f"{cfg.monitor_database_name}."
            ),
            "api_diagnostics": (
                "Compat path /api/diagnostics/* remains; history is stored in "
                f"{cfg.monitor_database_name} (dual-read migrate from CMDB)."
            ),
        },
        "entry_path": "/monitor",
        "retention_sweep": "/api/monitor/admin/retention-sweep",
        "live_settings": "/api/monitor/admin/live-settings",
        "live_probe_stub": "/api/monitor/live/probe-stub",
        "checks": "/api/monitor/checks",
        "poller_tick": "/api/monitor/admin/poller/tick",
        "ingest_logs": "/api/monitor/ingest/logs",
        "syslog_sources": "/api/monitor/logs/syslog-sources",
        "ingest_keys": "/api/monitor/logs/ingest-keys",
        "agents": "/api/monitor/agents",
        "agent_enrollments": "/api/monitor/agents/enrollments",
        "agent_register": "/api/monitor/agents/register",
        "ingest_metrics": "/api/monitor/ingest/metrics",
        "ingest_file_events": "/api/monitor/ingest/file-events",
        "agent_desired_state": "/api/monitor/agents/{agent_id}/desired-state",
        "files_watches": "/api/monitor/files/watches",
    }
