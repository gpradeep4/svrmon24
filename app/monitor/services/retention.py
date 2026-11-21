"""Monitoring retention / TTL sweeper — entitlement-gated count trim (SIMULATED).

Soft retention mirrors plan limits (``metric_samples_retained``,
``log_events_retained``, ``max_diagnostic_runs``). Not Mongo expireAfterSeconds —
ceilings are per-tenant entitlements, not fixed wall-clock TTLs.
"""

from __future__ import annotations

from typing import Any

from ...tenancy import require_tenant_id
from . import diagnostics as diagnostics_service
from . import logs as logs_service
from . import targets as targets_service


def sweep_tenant_retention(*, tenant_id: str) -> dict[str, Any]:
    """Trim over-limit time-series / history rows for one tenant."""
    tid = require_tenant_id(tenant_id)
    metric_trimmed = targets_service.enforce_metric_samples_retention(tenant_id=tid)
    log_trimmed = logs_service.enforce_log_events_retention(tenant_id=tid)
    diag_trimmed = diagnostics_service.enforce_diagnostics_retention(tenant_id=tid)
    return {
        "tenant_id": tid,
        "metric_samples_trimmed": metric_trimmed,
        "log_events_trimmed": log_trimmed,
        "diagnostics_trimmed": diag_trimmed,
        "live_probes": False,
        "execution_mode": "SIMULATED",
    }
