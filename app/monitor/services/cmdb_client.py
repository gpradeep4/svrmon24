"""CMDB inventory access for Monitoring — service boundary only (no cross-DB joins)."""

from __future__ import annotations

from typing import Any

from ...cmdb.models.components import COMPONENT_TYPES, ComponentType
from ...cmdb.services import components as components_service

# Monitoring domains map 1:1 to CMDB component types (middleware stays CMDB-only in v1).
DOMAIN_COMPONENT_TYPES: dict[str, str] = {
    "server": ComponentType.SERVER.value,
    "network": ComponentType.NETWORK.value,
    "application": ComponentType.APPLICATION.value,
    "database": ComponentType.DATABASE.value,
}

MONITORABLE_COMPONENT_TYPES: tuple[str, ...] = tuple(DOMAIN_COMPONENT_TYPES.values())


class MonitorCmdbError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def domain_for_component_type(component_type: str | None) -> str | None:
    """Map CMDB component_type → Monitoring domain (None for Middleware / unknown)."""
    ctype = (component_type or "").strip()
    for domain, mapped in DOMAIN_COMPONENT_TYPES.items():
        if ctype == mapped:
            return domain
    return None


def list_monitorable_components(
    *,
    tenant_id: str,
    component_type: str | None = None,
    page_size: int = 200,
) -> list[dict[str, Any]]:
    """List same-tenant CMDB CIs eligible for Monitoring targets.

    Pages through the CMDB components service — never queries CMDB Mongo from
    Monitoring aggregations.
    """
    types: list[str]
    if component_type:
        ctype = component_type.strip()
        if ctype not in MONITORABLE_COMPONENT_TYPES:
            if ctype not in COMPONENT_TYPES:
                raise MonitorCmdbError(
                    f"Unknown component_type '{component_type}'",
                    status_code=422,
                )
            # Middleware (and any non-monitorable type) → empty.
            return []
        types = [ctype]
    else:
        types = list(MONITORABLE_COMPONENT_TYPES)

    items: list[dict[str, Any]] = []
    for ctype in types:
        page = 1
        while True:
            listed = components_service.list_components(
                tenant_id=tenant_id,
                component_type=ctype,
                page=page,
                page_size=page_size,
                sort_by="component_id",
                sort_dir="asc",
            )
            batch = listed.get("items") or []
            items.extend(batch)
            total_pages = int(listed.get("total_pages") or 1)
            if page >= total_pages or not batch:
                break
            page += 1
    return items


def get_component(*, tenant_id: str, component_id: str) -> dict[str, Any] | None:
    """Fetch one same-tenant CMDB component (404-equivalent None when missing)."""
    cid = (component_id or "").strip()
    if not cid:
        return None
    return components_service.get_component(cid, tenant_id=tenant_id)
