"""CMDB / operations domain.

Inventory, relationships, dependencies, diagnostics, file monitoring, and the
related models and services live in this package. Shared platform code (auth,
tenancy, RBAC, config, database handles) stays at the ``app`` root. ITSM stays
in ``app.itsm``.

Historical import paths under ``app.routers``, ``app.services``, ``app.models``,
and ``app.diagnostics`` re-export these modules so existing callers keep working.
"""
