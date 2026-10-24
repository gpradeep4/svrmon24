"""Dependency traversal and impact analysis.

Relationship records in ``cmdb_relationships`` are the source of truth.
Direction convention (source → target):
- Upstream of X = follow outgoing edges (X is source → targets)
- Downstream of X = follow incoming edges (X is target ← sources)

Manual relationships only — no network scanning. Impact language is always
"potentially affected"; never claims a component is actually down.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Literal

from . import components as components_service
from . import relationships as relationships_service

Direction = Literal["upstream", "downstream"]

IMPACT_DISCLAIMER = (
    "Impact analysis identifies potentially affected components based on "
    "relationship data only. Appearance in this graph does not mean a "
    "component is actually down or degraded."
)


class DependencyError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _all_relationships() -> list[dict[str, Any]]:
    result = relationships_service.list_relationships(page=1, page_size=200)
    items = list(result.get("items") or [])
    total_pages = int(result.get("total_pages") or 1)
    for page in range(2, total_pages + 1):
        more = relationships_service.list_relationships(page=page, page_size=200)
        items.extend(more.get("items") or [])
    return items


def _index_edges(
    relationships: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rel in relationships:
        src = rel.get("source_component_id")
        tgt = rel.get("target_component_id")
        if not src or not tgt:
            continue
        outgoing[str(src)].append(rel)
        incoming[str(tgt)].append(rel)
    return outgoing, incoming


def _component_summary(
    component_id: str, cache: dict[str, dict[str, Any] | None]
) -> dict[str, Any] | None:
    if component_id not in cache:
        cache[component_id] = components_service.get_component(component_id)
    doc = cache[component_id]
    if doc is None:
        return None
    return {
        "component_id": doc.get("component_id"),
        "name": doc.get("name"),
        "component_type": doc.get("component_type"),
        "environment": doc.get("environment"),
        "status": doc.get("status"),
    }


def _passes_filters(
    summary: dict[str, Any] | None,
    *,
    environment: str | None,
    status: str | None,
) -> bool:
    if summary is None:
        return False
    if environment and (summary.get("environment") or "").lower() != environment.lower():
        return False
    if status and (summary.get("status") or "").lower() != status.lower():
        return False
    return True


def _edge_view(rel: dict[str, Any], *, depth: int, direct: bool) -> dict[str, Any]:
    return {
        "relationship_id": rel.get("relationship_id"),
        "source_component_id": rel.get("source_component_id"),
        "target_component_id": rel.get("target_component_id"),
        "relationship_type": rel.get("relationship_type"),
        "protocol": rel.get("protocol"),
        "source_port": rel.get("source_port"),
        "target_port": rel.get("target_port"),
        "verification_status": rel.get("verification_status"),
        "evidence_or_notes": rel.get("evidence_or_notes"),
        "discovery_method": rel.get("discovery_method"),
        "confidence": rel.get("confidence"),
        "environment": rel.get("environment"),
        "depth": depth,
        "direct": direct,
    }


def _row_from_node_edge(
    node: dict[str, Any],
    edge: dict[str, Any] | None,
    *,
    direction: Direction,
) -> dict[str, Any]:
    protocol = edge.get("protocol") if edge else None
    source_port = edge.get("source_port") if edge else None
    target_port = edge.get("target_port") if edge else None
    return {
        "component_id": node.get("component_id"),
        "name": node.get("name") or "—",
        "component_type": node.get("component_type") or "—",
        "environment": node.get("environment") or "—",
        "status": node.get("status") or "—",
        "depth": node.get("depth"),
        "direct_or_indirect": "direct" if node.get("direct") else "indirect",
        "relationship_type": (edge or {}).get("relationship_type") or "—",
        "protocol": protocol if protocol not in (None, "") else "—",
        "source_port": "—" if source_port is None else str(source_port),
        "target_port": "—" if target_port is None else str(target_port),
        "verification_status": (edge or {}).get("verification_status") or "—",
        "evidence_or_notes": (edge or {}).get("evidence_or_notes") or "—",
        "relationship_id": (edge or {}).get("relationship_id"),
        "direction": direction,
    }


def traverse(
    component_id: str,
    *,
    direction: Direction,
    depth: int = 5,
    environment: str | None = None,
    status: str | None = None,
    include_selected: bool = True,
) -> dict[str, Any]:
    """Traverse upstream or downstream dependencies from ``component_id``."""
    if depth < 0:
        raise DependencyError("depth must be >= 0", status_code=422)
    if depth > 50:
        raise DependencyError("depth must be <= 50", status_code=422)

    selected = components_service.get_component(component_id)
    if selected is None:
        raise DependencyError(f"Component '{component_id}' not found", status_code=404)

    relationships = _all_relationships()
    outgoing, incoming = _index_edges(relationships)
    adjacency = outgoing if direction == "upstream" else incoming

    cache: dict[str, dict[str, Any] | None] = {component_id: selected}
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges_by_id: dict[str, dict[str, Any]] = {}
    paths: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    missing: set[str] = set()
    seen_path_keys: set[str] = set()
    expanded: set[str] = set()

    if include_selected:
        summary = _component_summary(component_id, cache)
        assert summary is not None
        nodes_by_id[component_id] = {
            **summary,
            "depth": 0,
            "direct": False,
            "is_selected": True,
        }

    # (current_id, depth_so_far, path_component_ids, path_relationship_ids)
    queue: deque[tuple[str, int, list[str], list[str]]] = deque()
    queue.append((component_id, 0, [component_id], []))

    while queue:
        current, current_depth, path_ids, path_rels = queue.popleft()

        if current in expanded:
            continue
        expanded.add(current)

        if current_depth >= depth:
            continue

        for rel in adjacency.get(current, []):
            neighbor = (
                str(rel.get("target_component_id"))
                if direction == "upstream"
                else str(rel.get("source_component_id"))
            )
            rel_id = str(rel.get("relationship_id") or "")
            next_depth = current_depth + 1
            direct = next_depth == 1

            # Cycle detection — neighbor already on this path
            if neighbor in path_ids:
                cycles.append(
                    {
                        "component_ids": list(path_ids) + [neighbor],
                        "relationship_ids": list(path_rels) + [rel_id],
                        "closed_at": neighbor,
                    }
                )
                if rel_id and rel_id not in edges_by_id:
                    edges_by_id[rel_id] = _edge_view(rel, depth=next_depth, direct=direct)
                continue

            summary = _component_summary(neighbor, cache)
            if summary is None:
                missing.add(neighbor)
                if rel_id and rel_id not in edges_by_id:
                    edges_by_id[rel_id] = _edge_view(rel, depth=next_depth, direct=direct)
                continue

            if not _passes_filters(summary, environment=environment, status=status):
                continue

            existing = nodes_by_id.get(neighbor)
            if existing is None:
                nodes_by_id[neighbor] = {
                    **summary,
                    "depth": next_depth,
                    "direct": direct,
                    "is_selected": False,
                }
            else:
                existing["depth"] = min(int(existing["depth"]), next_depth)
                existing["direct"] = bool(existing["direct"]) or direct

            if rel_id not in edges_by_id:
                edges_by_id[rel_id] = _edge_view(rel, depth=next_depth, direct=direct)
            else:
                edge = edges_by_id[rel_id]
                edge["depth"] = min(int(edge["depth"]), next_depth)
                edge["direct"] = bool(edge["direct"]) or direct

            next_path_ids = list(path_ids) + [neighbor]
            next_path_rels = list(path_rels) + [rel_id]
            path_key = ">".join(next_path_ids)
            if path_key not in seen_path_keys:
                seen_path_keys.add(path_key)
                paths.append(
                    {
                        "component_ids": next_path_ids,
                        "relationship_ids": next_path_rels,
                        "depth": next_depth,
                    }
                )

            # Multi-path: if neighbor already expanded via another route, still
            # record this path/edge above; only queue if not yet expanded.
            if neighbor not in expanded:
                queue.append((neighbor, next_depth, next_path_ids, next_path_rels))

    # Second pass for alternate paths through already-expanded nodes:
    # walk all edges again from discovered nodes within depth to capture path variants
    _capture_additional_paths(
        start=component_id,
        direction=direction,
        depth=depth,
        adjacency=adjacency,
        nodes_by_id=nodes_by_id,
        edges_by_id=edges_by_id,
        paths=paths,
        seen_path_keys=seen_path_keys,
        cycles=cycles,
        cache=cache,
        environment=environment,
        status=status,
        missing=missing,
    )

    cycle_keys: set[str] = set()
    unique_cycles: list[dict[str, Any]] = []
    for cycle in cycles:
        key = ">".join(cycle["component_ids"])
        if key not in cycle_keys:
            cycle_keys.add(key)
            unique_cycles.append(cycle)

    nodes = sorted(
        nodes_by_id.values(),
        key=lambda n: (int(n.get("depth") or 0), str(n.get("component_id"))),
    )
    edges = sorted(
        edges_by_id.values(),
        key=lambda e: (int(e.get("depth") or 0), str(e.get("relationship_id"))),
    )

    rows: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("is_selected"):
            continue
        cid = str(node["component_id"])
        edge = None
        for candidate in edges:
            if direction == "upstream" and candidate.get("target_component_id") == cid:
                edge = candidate
                break
            if direction == "downstream" and candidate.get("source_component_id") == cid:
                edge = candidate
                break
        rows.append(_row_from_node_edge(node, edge, direction=direction))

    return {
        "selected": _component_summary(component_id, cache),
        "direction": direction,
        "depth": depth,
        "filters": {"environment": environment, "status": status},
        "nodes": nodes,
        "edges": edges,
        "rows": rows,
        "paths": sorted(paths, key=lambda p: (int(p["depth"]), len(p["component_ids"]))),
        "cycles_detected": unique_cycles,
        "missing_components": sorted(missing),
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "paths": len(paths),
            "cycles": len(unique_cycles),
            "missing": len(missing),
        },
    }


def _capture_additional_paths(
    *,
    start: str,
    direction: Direction,
    depth: int,
    adjacency: dict[str, list[dict[str, Any]]],
    nodes_by_id: dict[str, dict[str, Any]],
    edges_by_id: dict[str, dict[str, Any]],
    paths: list[dict[str, Any]],
    seen_path_keys: set[str],
    cycles: list[dict[str, Any]],
    cache: dict[str, dict[str, Any] | None],
    environment: str | None,
    status: str | None,
    missing: set[str],
) -> None:
    """DFS limited path enumeration to record multiple routes / shared deps."""

    def dfs(current: str, path_ids: list[str], path_rels: list[str]) -> None:
        if len(path_ids) - 1 >= depth:
            return
        for rel in adjacency.get(current, []):
            neighbor = (
                str(rel.get("target_component_id"))
                if direction == "upstream"
                else str(rel.get("source_component_id"))
            )
            rel_id = str(rel.get("relationship_id") or "")
            next_depth = len(path_ids)
            direct = next_depth == 1

            if neighbor in path_ids:
                cycles.append(
                    {
                        "component_ids": list(path_ids) + [neighbor],
                        "relationship_ids": list(path_rels) + [rel_id],
                        "closed_at": neighbor,
                    }
                )
                if rel_id and rel_id not in edges_by_id:
                    edges_by_id[rel_id] = _edge_view(rel, depth=next_depth, direct=direct)
                continue

            summary = _component_summary(neighbor, cache)
            if summary is None:
                missing.add(neighbor)
                if rel_id and rel_id not in edges_by_id:
                    edges_by_id[rel_id] = _edge_view(rel, depth=next_depth, direct=direct)
                continue
            if not _passes_filters(summary, environment=environment, status=status):
                continue

            # Only follow nodes already discovered in primary BFS (or start)
            if neighbor not in nodes_by_id and neighbor != start:
                # Allow discovery of alternate-route nodes within depth
                nodes_by_id[neighbor] = {
                    **summary,
                    "depth": next_depth,
                    "direct": direct,
                    "is_selected": False,
                }
            else:
                node = nodes_by_id[neighbor]
                node["depth"] = min(int(node["depth"]), next_depth)
                node["direct"] = bool(node["direct"]) or direct

            if rel_id not in edges_by_id:
                edges_by_id[rel_id] = _edge_view(rel, depth=next_depth, direct=direct)

            next_ids = list(path_ids) + [neighbor]
            next_rels = list(path_rels) + [rel_id]
            key = ">".join(next_ids)
            if key not in seen_path_keys:
                seen_path_keys.add(key)
                paths.append(
                    {
                        "component_ids": next_ids,
                        "relationship_ids": next_rels,
                        "depth": next_depth,
                    }
                )
            dfs(neighbor, next_ids, next_rels)

    dfs(start, [start], [])


def get_upstream(
    component_id: str,
    *,
    depth: int = 5,
    environment: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return traverse(
        component_id,
        direction="upstream",
        depth=depth,
        environment=environment,
        status=status,
    )


def get_downstream(
    component_id: str,
    *,
    depth: int = 5,
    environment: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return traverse(
        component_id,
        direction="downstream",
        depth=depth,
        environment=environment,
        status=status,
    )


def get_direct_upstream(component_id: str, **filters: Any) -> dict[str, Any]:
    return get_upstream(component_id, depth=1, **filters)


def get_direct_downstream(component_id: str, **filters: Any) -> dict[str, Any]:
    return get_downstream(component_id, depth=1, **filters)


def analyze_impact(
    component_id: str,
    *,
    depth: int = 10,
    environment: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Identify potentially affected applications via downstream traversal."""
    downstream = get_downstream(
        component_id,
        depth=depth,
        environment=environment,
        status=status,
    )
    apps: list[dict[str, Any]] = []
    for node in downstream["nodes"]:
        if node.get("is_selected"):
            continue
        if node.get("component_type") != "Application":
            continue
        app_id = str(node["component_id"])
        connecting = [
            path
            for path in downstream["paths"]
            if app_id in path["component_ids"][1:]
        ]
        apps.append(
            {
                "component": {
                    "component_id": node.get("component_id"),
                    "name": node.get("name"),
                    "component_type": node.get("component_type"),
                    "environment": node.get("environment"),
                    "status": node.get("status"),
                },
                "depth": node.get("depth"),
                "direct_or_indirect": "direct" if node.get("direct") else "indirect",
                "connecting_paths": connecting,
                "note": (
                    "Potentially affected if the selected component becomes unavailable. "
                    "This does not mean the application is currently down."
                ),
            }
        )

    apps.sort(key=lambda a: (int(a.get("depth") or 0), str(a["component"]["component_id"])))

    return {
        "selected": downstream["selected"],
        "disclaimer": IMPACT_DISCLAIMER,
        "depth": depth,
        "filters": {"environment": environment, "status": status},
        "potentially_affected_applications": apps,
        "downstream": downstream,
        "cycles_detected": downstream.get("cycles_detected") or [],
        "missing_components": downstream.get("missing_components") or [],
        "counts": {
            "potentially_affected_applications": len(apps),
            **(downstream.get("counts") or {}),
        },
    }


def dependency_bundle(
    component_id: str,
    *,
    depth: int = 5,
    environment: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Combined upstream + downstream + impact for UI."""
    upstream = get_upstream(
        component_id, depth=depth, environment=environment, status=status
    )
    impact = analyze_impact(
        component_id, depth=depth, environment=environment, status=status
    )
    return {
        "selected": upstream["selected"],
        "depth": depth,
        "filters": {"environment": environment, "status": status},
        "upstream": upstream,
        "downstream": impact["downstream"],
        "impact": {
            "disclaimer": impact["disclaimer"],
            "potentially_affected_applications": impact[
                "potentially_affected_applications"
            ],
            "counts": {
                "potentially_affected_applications": impact["counts"][
                    "potentially_affected_applications"
                ]
            },
        },
        "cycles_detected": _merge_cycles(
            upstream.get("cycles_detected") or [],
            impact.get("cycles_detected") or [],
        ),
        "missing_components": sorted(
            set(upstream.get("missing_components") or [])
            | set(impact.get("missing_components") or [])
        ),
        "graph": _build_graph(upstream, impact["downstream"]),
        "disclaimer": IMPACT_DISCLAIMER,
    }


def _merge_cycles(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for cycle in group:
            key = ">".join(cycle.get("component_ids") or [])
            if key and key not in seen:
                seen.add(key)
                out.append(cycle)
    return out


def _build_graph(
    upstream: dict[str, Any],
    downstream: dict[str, Any],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    for block, role in ((upstream, "upstream"), (downstream, "downstream")):
        for node in block.get("nodes") or []:
            cid = str(node["component_id"])
            existing = nodes.get(cid)
            if existing is None:
                roles = ["selected"] if node.get("is_selected") else [role]
                nodes[cid] = {**node, "roles": roles}
            else:
                if node.get("is_selected"):
                    existing["roles"] = ["selected"]
                    existing["is_selected"] = True
                elif role not in existing["roles"]:
                    existing["roles"].append(role)
        for edge in block.get("edges") or []:
            rid = str(edge.get("relationship_id") or "")
            if rid and rid not in edges:
                edges[rid] = edge
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
