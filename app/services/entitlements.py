"""Tenant entitlements (plan limits only — Master Phase 9 / 13).

v1 is entitlements-only: no payment provider, no billing webhooks, no Stripe.
Plans are an in-memory catalog keyed by ``plan_code``; each tenant document may
store ``plan_code`` (default ``legacy_unlimited``). Services enforce ceilings.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..tenancy import require_tenant_id

# Resource keys services may check. None in limits → unlimited.
RESOURCE_RELATIONSHIPS = "relationships"
RESOURCE_COMPONENTS = "components"
RESOURCE_CUSTOM_TABLES = "custom_tables"
RESOURCE_CUSTOM_RECORDS = "custom_records"
# Max depth for dependency / impact traversal (API hard-caps at 50).
RESOURCE_MAX_DEPENDENCY_DEPTH = "max_dependency_depth"
# Max SIMULATED diagnostic history rows a tenant may retain / create.
RESOURCE_MAX_DIAGNOSTIC_RUNS = "max_diagnostic_runs"
# Max Ollama-sourced AI analyses a tenant may store (rule fallback unlimited).
RESOURCE_MAX_OLLAMA_ANALYSES = "max_ollama_analyses"

PLAN_LEGACY_UNLIMITED = "legacy_unlimited"
PLAN_STARTER = "starter"
PLAN_STANDARD = "standard"

DEFAULT_PLAN_CODE = PLAN_LEGACY_UNLIMITED

# In-memory plan catalog (no payment system). Operators assign plan_code on
# tenants via CLI/API; there is no checkout or billing webhook.
_PLAN_CATALOG: dict[str, dict[str, Any]] = {
    PLAN_LEGACY_UNLIMITED: {
        "plan_code": PLAN_LEGACY_UNLIMITED,
        "plan_label": "Legacy (unlimited)",
        "limits": {
            RESOURCE_RELATIONSHIPS: None,
            RESOURCE_COMPONENTS: None,
            RESOURCE_CUSTOM_TABLES: None,
            RESOURCE_CUSTOM_RECORDS: None,
            RESOURCE_MAX_DEPENDENCY_DEPTH: None,
            RESOURCE_MAX_DIAGNOSTIC_RUNS: None,
            RESOURCE_MAX_OLLAMA_ANALYSES: None,
        },
        "notes": (
            "Default entitlements for migration / unlimited tenants. "
            "No payment provider is wired. "
            "Ollama AI also requires OLLAMA_ENABLED=true; shared-local contention "
            "applies when multiple tenants hit one Ollama host."
        ),
    },
    PLAN_STARTER: {
        "plan_code": PLAN_STARTER,
        "plan_label": "Starter",
        "limits": {
            RESOURCE_RELATIONSHIPS: 50,
            RESOURCE_COMPONENTS: 100,
            RESOURCE_CUSTOM_TABLES: 5,
            RESOURCE_CUSTOM_RECORDS: 500,
            RESOURCE_MAX_DEPENDENCY_DEPTH: 5,
            RESOURCE_MAX_DIAGNOSTIC_RUNS: 20,
            RESOURCE_MAX_OLLAMA_ANALYSES: 5,
        },
        "notes": (
            "Entitlements-only starter ceiling for small orgs. "
            "No payment provider — assign via platform-admin CLI/API."
        ),
    },
    PLAN_STANDARD: {
        "plan_code": PLAN_STANDARD,
        "plan_label": "Standard",
        "limits": {
            RESOURCE_RELATIONSHIPS: 500,
            RESOURCE_COMPONENTS: 1000,
            RESOURCE_CUSTOM_TABLES: 25,
            RESOURCE_CUSTOM_RECORDS: 5000,
            RESOURCE_MAX_DEPENDENCY_DEPTH: 15,
            RESOURCE_MAX_DIAGNOSTIC_RUNS: 200,
            RESOURCE_MAX_OLLAMA_ANALYSES: 50,
        },
        "notes": (
            "Entitlements-only standard ceiling. "
            "No payment provider — assign via platform-admin CLI/API."
        ),
    },
}


class EntitlementError(Exception):
    def __init__(self, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def list_plans() -> list[dict[str, Any]]:
    """Return the entitlements plan catalog (no billing fields)."""
    return [deepcopy(plan) for plan in _PLAN_CATALOG.values()]


def get_plan(plan_code: str) -> dict[str, Any] | None:
    code = (plan_code or "").strip()
    plan = _PLAN_CATALOG.get(code)
    return deepcopy(plan) if plan else None


def normalize_plan_code(plan_code: str | None) -> str:
    code = (plan_code or DEFAULT_PLAN_CODE).strip() or DEFAULT_PLAN_CODE
    if code not in _PLAN_CATALOG:
        raise EntitlementError(
            f"Unknown plan_code '{plan_code}' "
            f"(expected one of: {', '.join(sorted(_PLAN_CATALOG))})",
            status_code=422,
        )
    return code


def _plan_for_tenant(tenant_id: str) -> dict[str, Any]:
    """Resolve plan for a tenant from its ``plan_code`` (default unlimited)."""
    from . import tenants as tenants_service

    tid = require_tenant_id(tenant_id)
    tenant = tenants_service.get_tenant(tid)
    code = DEFAULT_PLAN_CODE
    if tenant and tenant.get("plan_code"):
        candidate = str(tenant["plan_code"]).strip()
        if candidate in _PLAN_CATALOG:
            code = candidate
    return deepcopy(_PLAN_CATALOG[code])


def get_tenant_entitlements(tenant_id: str) -> dict[str, Any]:
    """Return entitlements snapshot for the current tenant (no billing fields)."""
    tid = require_tenant_id(tenant_id)
    plan = _plan_for_tenant(tid)
    return {
        "tenant_id": tid,
        "plan_code": plan["plan_code"],
        "plan_label": plan["plan_label"],
        "payment_provider": None,
        "billing_enabled": False,
        "limits": dict(plan["limits"]),
        "notes": plan["notes"],
        "catalog_size": len(_PLAN_CATALOG),
    }


def relationship_limit(tenant_id: str) -> int | None:
    """Max relationships allowed for tenant, or None when unlimited."""
    entitlements = get_tenant_entitlements(tenant_id)
    limit = entitlements["limits"].get(RESOURCE_RELATIONSHIPS)
    if limit is None:
        return None
    return int(limit)


def assert_can_create_relationship(tenant_id: str) -> None:
    """Enforce relationship create against tenant entitlements.

    Unlimited (None) always passes. When a numeric limit is set, count current
    tenant relationships and raise EntitlementError (403) at/over the ceiling.
    """
    tid = require_tenant_id(tenant_id)
    limit = relationship_limit(tid)
    if limit is None:
        return

    from . import relationships as relationships_service

    listed = relationships_service.list_relationships(
        tenant_id=tid, page=1, page_size=1
    )
    total = int(listed.get("total") or 0)
    if total >= limit:
        raise EntitlementError(
            f"Relationship limit reached for this tenant "
            f"({total}/{limit}). Upgrade entitlements to create more.",
            status_code=403,
        )


def max_dependency_depth(tenant_id: str) -> int | None:
    """Max dependency/impact depth for tenant, or None when unlimited (API ≤50)."""
    entitlements = get_tenant_entitlements(tenant_id)
    limit = entitlements["limits"].get(RESOURCE_MAX_DEPENDENCY_DEPTH)
    if limit is None:
        return None
    return int(limit)


def assert_dependency_depth_allowed(tenant_id: str, depth: int) -> None:
    """Enforce requested traversal depth against tenant entitlements.

    Unlimited (None) always passes (API still caps at 50). When a numeric
    ceiling is set, requests deeper than that raise EntitlementError (403).
    """
    tid = require_tenant_id(tenant_id)
    limit = max_dependency_depth(tid)
    if limit is None:
        return
    if int(depth) > int(limit):
        raise EntitlementError(
            f"Dependency depth {depth} exceeds tenant entitlement "
            f"(max_dependency_depth={limit}). Upgrade entitlements for deeper "
            "traversal.",
            status_code=403,
        )


def diagnostic_run_limit(tenant_id: str) -> int | None:
    """Max SIMULATED diagnostic runs allowed for tenant, or None when unlimited."""
    entitlements = get_tenant_entitlements(tenant_id)
    limit = entitlements["limits"].get(RESOURCE_MAX_DIAGNOSTIC_RUNS)
    if limit is None:
        return None
    return int(limit)


def assert_can_run_diagnostic(tenant_id: str) -> None:
    """Enforce diagnostic start against tenant entitlements.

    Unlimited (None) always passes. When a numeric limit is set, count current
    tenant diagnostic_history rows and raise EntitlementError (403) at/over the
    ceiling. Live/remote probes remain disabled regardless of plan.
    """
    tid = require_tenant_id(tenant_id)
    limit = diagnostic_run_limit(tid)
    if limit is None:
        return

    from . import diagnostics as diagnostics_service

    listed = diagnostics_service.list_diagnostics(
        tenant_id=tid, page=1, page_size=1
    )
    total = int(listed.get("total") or 0)
    if total >= limit:
        raise EntitlementError(
            f"Diagnostic run limit reached for this tenant "
            f"({total}/{limit}). Upgrade entitlements to run more "
            "SIMULATED diagnostics.",
            status_code=403,
        )


def ollama_analysis_limit(tenant_id: str) -> int | None:
    """Max Ollama-sourced analyses allowed for tenant, or None when unlimited."""
    entitlements = get_tenant_entitlements(tenant_id)
    limit = entitlements["limits"].get(RESOURCE_MAX_OLLAMA_ANALYSES)
    if limit is None:
        return None
    return int(limit)


def count_ollama_analyses(tenant_id: str) -> int:
    """Count stored Ollama-sourced analyses for the tenant (history entries)."""
    from . import diagnostics as diagnostics_service

    return diagnostics_service.count_ollama_analyses(tenant_id=tenant_id)


def ollama_analysis_allowed(tenant_id: str) -> dict[str, Any]:
    """Snapshot of whether this tenant may call Ollama (entitlements only).

    Does not check OLLAMA_ENABLED — callers combine with settings. Rule-based
    fallback is never blocked by this limit.
    """
    tid = require_tenant_id(tenant_id)
    limit = ollama_analysis_limit(tid)
    used = count_ollama_analyses(tid)
    if limit is None:
        return {
            "allowed": True,
            "limit": None,
            "used": used,
            "remaining": None,
            "limited": False,
        }
    remaining = max(0, int(limit) - int(used))
    return {
        "allowed": used < limit,
        "limit": int(limit),
        "used": int(used),
        "remaining": remaining,
        "limited": used >= limit,
    }


def assert_can_run_ollama_analysis(tenant_id: str) -> None:
    """Enforce Ollama analyze against tenant entitlements.

    Unlimited (None) always passes. When a numeric limit is set, count stored
    Ollama-sourced analysis history entries and raise EntitlementError (403)
    at/over the ceiling. Rule-based fallback remains available regardless.
    """
    tid = require_tenant_id(tenant_id)
    status = ollama_analysis_allowed(tid)
    if status["allowed"]:
        return
    raise EntitlementError(
        f"Ollama analysis limit reached for this tenant "
        f"({status['used']}/{status['limit']}). Upgrade entitlements for more "
        "local Ollama analyses, or use rule-based fallback.",
        status_code=403,
    )
