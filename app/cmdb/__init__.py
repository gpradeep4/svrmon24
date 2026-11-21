"""CMDB / operations domain.

Inventory, relationships, dependencies, diagnostics, file monitoring, and the
related models and services live in this package. Shared platform code (auth,
tenancy, RBAC, config, database handles) stays at the ``app`` root. ITSM stays
in ``app.itsm``.

Import from ``app.cmdb.*`` directly (compatibility shims under the historical
``app.routers`` / ``app.services`` / ``app.models`` / ``app.diagnostics`` paths
were removed in 0.44.0).
"""
