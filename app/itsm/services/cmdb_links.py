"""CMDB CI validation for ITSM — service boundary only (no cross-DB joins)."""

from __future__ import annotations

from typing import Any

from ...services import components as components_service
from ..models.common import CiLink


class CmdbLinkError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def resolve_component_link(
    component_id: str, *, tenant_id: str
) -> dict[str, Any]:
    """Validate a same-tenant CMDB component and return a ci_link payload.

    Missing / other-tenant components surface as 404 (no leak).
    """
    cid = (component_id or "").strip()
    if not cid:
        raise CmdbLinkError("component_id is required", status_code=400)
    doc = components_service.get_component(cid, tenant_id=tenant_id)
    if doc is None:
        raise CmdbLinkError(f"Component '{cid}' not found", status_code=404)
    return {
        "component_id": doc.get("component_id") or cid,
        "component_type": doc.get("component_type"),
        "name_snapshot": doc.get("name") or doc.get("hostname") or cid,
    }


def resolve_ci_links(
    links: list[CiLink] | list[dict[str, Any]] | None, *, tenant_id: str
) -> list[dict[str, Any]]:
    """Resolve and de-dupe CI links by component_id.

    Preserves optional ticket-side SLA snapshots (``ci_tier``, ``criticality``)
    supplied on the incoming link — never written back to CMDB.
    """
    if not links:
        return []
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in links:
        snapshot_tier: str | None = None
        snapshot_crit: str | None = None
        if isinstance(raw, CiLink):
            cid = raw.component_id
            snapshot_tier = (raw.ci_tier or "").strip() or None
            snapshot_crit = (raw.criticality or "").strip() or None
        elif isinstance(raw, dict):
            cid = str(raw.get("component_id") or "")
            snapshot_tier = str(raw.get("ci_tier") or "").strip() or None
            snapshot_crit = str(raw.get("criticality") or "").strip() or None
        else:
            continue
        cid = cid.strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        link = resolve_component_link(cid, tenant_id=tenant_id)
        if snapshot_tier:
            link["ci_tier"] = snapshot_tier
        if snapshot_crit:
            link["criticality"] = snapshot_crit
        resolved.append(link)
    return resolved
