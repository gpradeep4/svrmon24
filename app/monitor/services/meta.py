"""Monitoring module metadata — SIMULATED default; live gates fail-closed."""

from __future__ import annotations

from typing import Any

from ...config import Settings, get_settings
from ..models.literals import DOMAINS, EXECUTION_MODES, WATCH_MODES
from . import egress as egress_service
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
    "SIMULATED / SYNTHETIC_DEMO — platform MONITOR_LIVE_PROBES_ENABLED and/or "
    "tenant monitor_live_opt_in are off (fail-closed). Target health, metric "
    "samples, and log streams stay synthetic until both gates are on."
)
BANNER_LIVE_GATED = (
    "Live monitoring gates are ON for this tenant — series may be SIMULATED or LIVE. "
    "Per-row execution_mode badges distinguish sources. SIMULATED seed / "
    "simulate-tick remain available; agentless polls need egress allowlist; "
    "HTTP/syslog ingest, agents, file watches, and optional auto-incident "
    "each require their capability gates."
)
# Back-compat alias for SIMULATED services (dashboard / targets / logs / alerts).
BANNER = BANNER_SIMULATED

# Fail-closed capability matrix documented in meta (L10).
FAIL_CLOSED_MATRIX: dict[str, dict[str, Any]] = {
    "agentless_poll": {
        "requires": [
            "MONITOR_LIVE_PROBES_ENABLED",
            "tenant.monitor_live_opt_in",
            "MONITOR_LIVE_AGENTLESS_ENABLED",
            "tenant.monitor_live_agentless_opt_in",
            "MONITOR_EGRESS_ALLOWLIST (non-empty)",
        ],
        "when_off": "403 / denied — no LIVE check results or samples written",
    },
    "log_ingest_http": {
        "requires": [
            "MONITOR_LIVE_PROBES_ENABLED",
            "tenant.monitor_live_opt_in",
            "MONITOR_LIVE_HTTP_INGEST_ENABLED",
        ],
        "when_off": "403 on POST /api/monitor/ingest/logs",
    },
    "log_ingest_syslog": {
        "requires": [
            "MONITOR_LIVE_PROBES_ENABLED",
            "tenant.monitor_live_opt_in",
            "MONITOR_LIVE_AGENTLESS_ENABLED",
            "tenant.monitor_live_agentless_opt_in",
            "MONITOR_LIVE_SYSLOG_BIND (set)",
        ],
        "when_off": "socket unbound / drop — no LIVE syslog ingest",
    },
    "agent_register": {
        "requires": [
            "MONITOR_LIVE_PROBES_ENABLED",
            "tenant.monitor_live_opt_in",
            "MONITOR_LIVE_AGENT_ENABLED",
            "tenant.monitor_live_agent_opt_in",
        ],
        "when_off": "403 on enroll/register/heartbeat",
    },
    "agent_ingest": {
        "requires": [
            "MONITOR_LIVE_PROBES_ENABLED",
            "tenant.monitor_live_opt_in",
            "MONITOR_LIVE_AGENT_ENABLED",
            "tenant.monitor_live_agent_opt_in",
        ],
        "when_off": "403 on POST /api/monitor/ingest/metrics|logs|file-events (agent token)",
    },
    "file_watch_live": {
        "requires": [
            "MONITOR_LIVE_PROBES_ENABLED",
            "tenant.monitor_live_opt_in",
            "agent or agentless capability (mode-dependent)",
        ],
        "when_off": "LIVE watch_mode rejected; SIMULATED watches unchanged",
    },
    "auto_incident": {
        "requires": [
            "MONITOR_LIVE_PROBES_ENABLED",
            "tenant.monitor_live_opt_in",
            "tenant.monitor_auto_incident_opt_in",
            "rule.auto_incident",
        ],
        "when_off": "never creates ITSM incidents; suggest-incident draft remains",
    },
    "live_stub": {
        "requires": [
            "MONITOR_LIVE_PROBES_ENABLED",
            "tenant.monitor_live_opt_in",
        ],
        "when_off": "403 on POST /api/monitor/live/probe-stub",
    },
}


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
    retention_days: int | None = None
    retention_days_by_tier: dict[str, int | None] = {
        "hot": None,
        "extended": None,
        "siem": None,
    }
    if tid:
        from ...services import entitlements as entitlements_service
        from . import cold_storage as cold_storage_service

        gates = live_gates_service.live_gates(tenant_id=tid, settings=cfg)
        retention_tier = live_gates_service.tenant_live_settings(tid)[
            "monitor_retention_tier"
        ]
        retention_days = entitlements_service.effective_monitor_retention_days(tid)
        retention_days_by_tier = {
            "hot": entitlements_service.monitor_retention_days_hot_limit(tid),
            "extended": entitlements_service.monitor_retention_days_extended_limit(tid),
            "siem": entitlements_service.monitor_retention_days_siem_limit(tid),
        }
        cold = cold_storage_service.cold_storage_status(settings=cfg)
    else:
        from . import cold_storage as cold_storage_service

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
        cold = cold_storage_service.cold_storage_status(settings=cfg)
    live_probes = bool(gates.get("platform_enabled") and gates.get("tenant_opt_in"))
    banner = BANNER_LIVE_GATED if live_probes else BANNER_SIMULATED
    egress = egress_service.egress_status(settings=cfg)
    # Meta is readable by dashboard:read — omit host list; admin live-settings has full entries.
    egress_public = {
        "env_var": egress["env_var"],
        "configured": egress["configured"],
        "entry_count": egress["entry_count"],
        "deny_all_when_empty": egress["deny_all_when_empty"],
        "docs": egress["docs"],
    }
    return {
        "module": "monitoring",
        "execution_mode": EXECUTION_MODE,
        "execution_modes": list(EXECUTION_MODES),
        "data_source": DATA_SOURCE,
        "demo_only": not live_probes,
        "live_probes": live_probes,
        "live_gates": gates,
        "fail_closed_matrix": FAIL_CLOSED_MATRIX,
        "egress": egress_public,
        "retention_tier": retention_tier,
        "retention_days": retention_days,
        "retention_days_by_tier": retention_days_by_tier,
        "cold_storage": {
            "configured": bool(cold.get("configured")),
            "scheme": cold.get("scheme"),
        },
        "collect_modes": list(COLLECT_MODES),
        "domains": list(DOMAINS),
        "os_families": list(OS_FAMILIES),
        "network_target_kinds": list(NETWORK_TARGET_KINDS),
        "banner": banner,
        "notice": (
            "Monitoring defaults to SIMULATED (fail-closed). Enable platform "
            "MONITOR_LIVE_PROBES_ENABLED plus tenant monitor_live_opt_in to "
            "unlock LIVE series; capability sub-gates and MONITOR_EGRESS_ALLOWLIST "
            "(deny-all when empty) still apply — see fail_closed_matrix. "
            "Sync targets from CMDB (API client only); domains include "
            "server/network/application/middleware/database. LIVE paths: "
            "agentless HTTP/TCP/ICMP/SNMP checks + poller; HTTP/syslog log "
            "ingest; agent enroll/token (+ optional mTLS sketch) + "
            "metrics/logs/file-events ingest; file watch_mode "
            "SIMULATED|AGENT|AGENTLESS_POLL; optional alert→ITSM auto-create "
            "(tenant monitor_auto_incident_opt_in default OFF + rule.auto_incident; "
            "ITSM service only, audited, daily-capped — never writes ITSM Mongo). "
            "Suggest-incident draft→Apply remains when auto-incident is off. "
            "No AI auto-approve of unrelated flows. Retention tiers "
            "(hot/extended/siem) + SIEM search + optional cold-archive "
            "(MONITOR_COLD_STORAGE_URI file://). File Monitoring and Diagnostics "
            "live under Monitoring (CMDB redirect stubs removed in M8). "
            "Live path L0–L10 complete; SIMULATED seed / simulate-tick unchanged "
            "when live is off."
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
            "live_never_copy": (
                "Do not claim live probes are permanently unavailable. "
                "Default is SIMULATED/fail-closed; LIVE unlocks when platform "
                "+ tenant gates (and capability/egress) are on. See "
                "fail_closed_matrix and live_gates."
            ),
        },
        "entry_path": "/monitor",
        "retention_sweep": "/api/monitor/admin/retention-sweep",
        "cold_archive": "/api/monitor/admin/cold-archive",
        "retention_jobs": "/api/monitor/admin/retention-jobs",
        "live_settings": "/api/monitor/admin/live-settings",
        "egress_admin": "/api/monitor/admin/egress",
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
        "live_path_complete": True,
        "live_slices": ["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10"],
    }
