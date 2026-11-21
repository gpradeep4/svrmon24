"""Compat re-export — Diagnostics data lives in ``app.monitor`` (M8).

Canonical implementation: ``app.monitor.services.diagnostics``.
``/api/diagnostics`` routes keep working via this shim.
"""

from __future__ import annotations

from ...monitor.services.diagnostics import (  # noqa: F401
    COLLECTION,
    DiagnosticError,
    attach_ai_analysis,
    count_diagnostics,
    count_ollama_analyses,
    enforce_diagnostics_retention,
    generate_diagnostic_id,
    get_diagnostic,
    list_diagnostic_profiles,
    list_diagnostics,
    migrate_tenant_from_cmdb,
    start_diagnostic,
)

__all__ = [
    "COLLECTION",
    "DiagnosticError",
    "attach_ai_analysis",
    "count_diagnostics",
    "count_ollama_analyses",
    "enforce_diagnostics_retention",
    "generate_diagnostic_id",
    "get_diagnostic",
    "list_diagnostic_profiles",
    "list_diagnostics",
    "migrate_tenant_from_cmdb",
    "start_diagnostic",
]
