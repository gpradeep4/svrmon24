"""Service Portal module — request / approve / execute catalog.

Collections live in the ITSM DB (``svrmon-itsm``) with ``sp_`` prefix.
Cross-access to CMDB / Monitoring is via API/service clients only — no joins.
SIMULATED remains the default; live paths are fail-closed behind platform
``SERVICE_PORTAL_LIVE_EXEC_ENABLED`` + per-tenant ``sp_live_opt_in``.
Dual collect modes: ``AGENT`` | ``AGENTLESS`` (both SIMULATED when live off).
"""

from __future__ import annotations

# SP0: package + meta + RBAC. SP1: sidebar. SP2+: catalog / requests / …
PORTAL_COLLECTIONS: tuple[str, ...] = (
    "sp_catalog_items",
    "sp_approval_policies",
    "sp_requests",
    "sp_approval_steps",
    "sp_execution_runs",
    "sp_audit_events",
)

PORTAL_DOMAINS: tuple[str, ...] = (
    "os",
    "middleware",
    "database",
    "networking",
    "cloud",
    "generic",
    "other",
)

PORTAL_COLLECT_MODES: tuple[str, ...] = ("agentless", "agent")
