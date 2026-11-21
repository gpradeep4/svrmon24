"""Compat re-export — File Monitoring data lives in ``app.monitor`` (M3).

Canonical implementation: ``app.monitor.services.file_monitoring``.
``/api/file-monitoring`` routes keep working via this shim.
"""

from __future__ import annotations

from ...monitor.services.file_monitoring import (  # noqa: F401
    BANNER,
    DATA_SOURCE,
    EVENTS_COLLECTION,
    EXECUTION_MODE,
    SIMULATED_NOTE,
    TARGETS_COLLECTION,
    FileMonitoringError,
    ensure_simulated_seed,
    get_target,
    get_version_event,
    list_targets,
    list_versions,
    migrate_tenant_from_cmdb,
    module_meta,
    wipe_demo_for_tenant,
)

__all__ = [
    "BANNER",
    "DATA_SOURCE",
    "EVENTS_COLLECTION",
    "EXECUTION_MODE",
    "SIMULATED_NOTE",
    "TARGETS_COLLECTION",
    "FileMonitoringError",
    "ensure_simulated_seed",
    "get_target",
    "get_version_event",
    "list_targets",
    "list_versions",
    "migrate_tenant_from_cmdb",
    "module_meta",
    "wipe_demo_for_tenant",
]
