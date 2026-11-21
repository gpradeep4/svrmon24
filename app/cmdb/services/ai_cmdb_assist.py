"""CMDB AI assists — classification, relationships, impact narrative, change risk.

C1–C4 assist / suggestion only. Apply writes go through normal create/update APIs.
Uses the shared AI facade (cloud → Ollama → rule). Rule fallbacks always work.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ...services import ai_facade as ai_facade_service
from ...services.ai_providers import SOURCE_CLOUD, SOURCE_OLLAMA, SOURCE_RULE
from ...tenancy import require_tenant_id
from ..models.components import COMPONENT_TYPES, TYPE_SPECIFIC_KEYS, ComponentType
from ..models.relationships import RELATIONSHIP_TYPE_DOCS, RelationshipType
from . import components as components_service
from . import dependencies as dependencies_service
from .dependencies import IMPACT_DISCLAIMER, DependencyError

logger = logging.getLogger(__name__)

# Type-pair → preferred relationship_type (source_type, target_type).
_TYPE_PAIR_RULES: dict[tuple[str, str], str] = {
    ("Middleware", "Server"): RelationshipType.HOSTED_ON.value,
    ("Database", "Server"): RelationshipType.HOSTED_ON.value,
    ("Application", "Server"): RelationshipType.HOSTED_ON.value,
    ("Application", "Middleware"): RelationshipType.DEPENDS_ON.value,
    ("Application", "Database"): RelationshipType.DEPENDS_ON.value,
    ("Middleware", "Database"): RelationshipType.CONNECTS_TO.value,
    ("Middleware", "Middleware"): RelationshipType.DEPENDS_ON.value,
    ("Network", "Application"): RelationshipType.ROUTES_TO.value,
    ("Network", "Server"): RelationshipType.ROUTES_TO.value,
    ("Network", "Middleware"): RelationshipType.ROUTES_TO.value,
    ("Application", "Application"): RelationshipType.DEPENDS_ON.value,
    ("Application", "Network"): RelationshipType.DEPENDS_ON.value,
}


def _blob(*parts: Any) -> str:
    bits: list[str] = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip().lower()
        if text:
            bits.append(text)
    return " ".join(bits)


def _confidence_from_score(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def build_classification_fallback(draft: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Heuristic CI type + field fills from draft payload only."""
    text = _blob(
        draft.get("name"),
        draft.get("hostname"),
        draft.get("ip_address"),
        draft.get("os_family"),
        draft.get("os_version"),
        draft.get("product_type"),
        draft.get("product_version"),
        draft.get("device_type"),
        draft.get("device_name"),
        draft.get("application_name"),
        draft.get("application_type"),
        draft.get("service_url"),
        draft.get("endpoint"),
        draft.get("notes"),
        draft.get("component_id"),
        *(draft.get("hints") or []) if isinstance(draft.get("hints"), list) else [],
    )
    scores: dict[str, int] = {t: 0 for t in COMPONENT_TYPES}
    field_fills: dict[str, Any] = {}
    rationale: list[str] = []

    def bump(ctype: str, pts: int, why: str) -> None:
        scores[ctype] = scores.get(ctype, 0) + pts
        rationale.append(f"{ctype}+{pts}: {why}")

    # Explicit id prefixes
    cid = str(draft.get("component_id") or "").strip().lower()
    prefix_map = {
        "srv": "Server",
        "net": "Network",
        "mware": "Middleware",
        "mw": "Middleware",
        "db": "Database",
        "app": "Application",
    }
    for prefix, ctype in prefix_map.items():
        if cid.startswith(f"{prefix}-") or cid.startswith(prefix):
            bump(ctype, 6, f"component_id prefix '{prefix}'")
            break

    if draft.get("hostname") or draft.get("ip_address") or draft.get("os_family"):
        bump("Server", 5, "hostname/ip/os fields present")
        if draft.get("hostname") and not field_fills.get("hostname"):
            field_fills["hostname"] = draft.get("hostname")
        if draft.get("ip_address"):
            field_fills["ip_address"] = draft.get("ip_address")
        if draft.get("os_family"):
            field_fills["os_family"] = draft.get("os_family")
        if draft.get("os_version"):
            field_fills["os_version"] = draft.get("os_version")

    server_kw = ("rhel", "linux", "windows", "ubuntu", "centos", "host", "vm-", "baremetal")
    if any(k in text for k in server_kw):
        bump("Server", 3, "server OS/host keywords")

    db_kw = (
        "oracle", "postgres", "postgresql", "mysql", "mariadb", "mongodb", "mongo",
        "sqlserver", "mssql", "database", "db2", "cassandra",
    )
    db_hit = any(k in text for k in db_kw) or bool(draft.get("endpoint"))
    if db_hit:
        bump("Database", 7, "database product/endpoint hints")
        if draft.get("endpoint"):
            field_fills["endpoint"] = draft.get("endpoint")
        if draft.get("product_type"):
            field_fills["product_type"] = draft.get("product_type")

    mw_kw = (
        "tomcat", "weblogic", "websphere", "nginx", "apache", "httpd", "redis",
        "rabbitmq", "kafka", "jboss", "middleware", "iis",
    )
    mw_hit = any(k in text for k in mw_kw)
    if mw_hit or ((draft.get("product_type") or draft.get("listen_port")) and not db_hit):
        bump("Middleware", 5, "middleware product/port hints")
        if draft.get("product_type") and not db_hit:
            field_fills["product_type"] = draft.get("product_type")
        if draft.get("listen_port") is not None:
            field_fills["listen_port"] = draft.get("listen_port")

    net_kw = (
        "router", "switch", "firewall", "load balancer", "loadbalancer", "f5",
        "vip", "gateway", "network", "lb-",
    )
    if any(k in text for k in net_kw) or draft.get("device_type") or draft.get("management_ip"):
        bump("Network", 5, "network device hints")
        if draft.get("device_type"):
            field_fills["device_type"] = draft.get("device_type")
        if draft.get("management_ip"):
            field_fills["management_ip"] = draft.get("management_ip")
        if draft.get("device_name"):
            field_fills["device_name"] = draft.get("device_name")

    app_kw = ("application", "service", "portal", "api", "http://", "https://", "svc")
    if any(k in text for k in app_kw) or draft.get("service_url") or draft.get("application_name"):
        bump("Application", 5, "application/url hints")
        if draft.get("service_url"):
            field_fills["service_url"] = draft.get("service_url")
        if draft.get("application_name"):
            field_fills["application_name"] = draft.get("application_name")
        elif draft.get("name"):
            field_fills["application_name"] = draft.get("name")

    # Prefer an already-stated type when present and valid.
    stated = str(draft.get("component_type") or "").strip()
    if stated in COMPONENT_TYPES:
        bump(stated, 4, "draft already names this component_type")

    best = max(COMPONENT_TYPES, key=lambda t: scores.get(t, 0))
    best_score = scores.get(best, 0)
    if best_score <= 0:
        best = "Server"
        best_score = 1
        rationale.append("Server+1: default when no strong signals")

    # Drop field fills that are illegal for the chosen type.
    allowed = TYPE_SPECIFIC_KEYS[ComponentType(best)]
    field_fills = {k: v for k, v in field_fills.items() if k in allowed and v is not None}

    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "suggested_component_type": best,
        "suggested_fields": field_fills,
        "confidence": _confidence_from_score(best_score),
        "rationale": rationale[:12],
        "scores": scores,
        "safety": {
            "assist_only": True,
            "auto_apply": False,
            "human_must_confirm": True,
        },
    }


def _normalize_classification(
    raw: dict[str, Any],
    *,
    source: str,
    model: str | None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    ctype = str(raw.get("suggested_component_type") or raw.get("component_type") or "").strip()
    if ctype not in COMPONENT_TYPES:
        ctype = "Server"
    fields_raw = raw.get("suggested_fields") or raw.get("fields") or {}
    fields: dict[str, Any] = {}
    if isinstance(fields_raw, dict):
        allowed = TYPE_SPECIFIC_KEYS[ComponentType(ctype)]
        for key, value in fields_raw.items():
            if key in allowed and value is not None and str(value).strip() != "":
                fields[str(key)] = value
    confidence = str(raw.get("confidence") or "low").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    rationale = raw.get("rationale") or raw.get("reasons") or []
    if isinstance(rationale, str):
        rationale = [rationale]
    if not isinstance(rationale, list):
        rationale = []
    out: dict[str, Any] = {
        "source": source,
        "model": model,
        "suggested_component_type": ctype,
        "suggested_fields": fields,
        "confidence": confidence,
        "rationale": [str(r).strip() for r in rationale if str(r).strip()][:12],
        "safety": {
            "assist_only": True,
            "auto_apply": False,
            "human_must_confirm": True,
        },
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def _validate_classification(raw: dict[str, Any]) -> None:
    if "suggested_component_type" not in raw and "component_type" not in raw:
        raise ValueError("classification JSON missing suggested_component_type")


def suggest_classification(
    draft: dict[str, Any],
    *,
    tenant_id: str,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Suggest component_type + type-specific field fills for a draft CI."""
    tid = require_tenant_id(tenant_id)
    draft = dict(draft or {})

    def _fallback(reason: str) -> dict[str, Any]:
        return build_classification_fallback(draft, reason=reason)

    system = (
        "You are a CMDB classification assistant for SVRMON24. "
        "Respond with a single JSON object only. "
        "Suggest component_type from exactly: Server, Network, Middleware, Database, Application. "
        "Also suggest type-specific field fills using only keys valid for that type. "
        "Never invent hostnames, IPs, or products not hinted in the draft. "
        "Never instruct creating/updating inventory — suggestion only. "
        "Required keys: suggested_component_type (string), suggested_fields (object), "
        "confidence (low|medium|high), rationale (array of strings)."
    )
    user = "Classify this CMDB draft and return the required JSON:\n" + json.dumps(
        draft, default=str
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="cmdb.classify",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_classification,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        return _normalize_classification(
            result.payload, source=result.source, model=result.model
        )
    payload = result.payload
    if isinstance(payload, dict) and payload.get("suggested_component_type"):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")


def _default_rel_type(source_type: str | None, target_type: str | None) -> str:
    if source_type and target_type:
        hit = _TYPE_PAIR_RULES.get((source_type, target_type))
        if hit:
            return hit
    return RelationshipType.DEPENDS_ON.value


def build_relationship_fallback(
    *,
    source: dict[str, Any] | None,
    target: dict[str, Any] | None,
    notes: str | None,
    reason: str,
    neighbor_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rule-based edge suggestion for a pair and/or neighbor list."""
    src_type = (source or {}).get("component_type")
    tgt_type = (target or {}).get("component_type")
    rel_type = _default_rel_type(
        str(src_type) if src_type else None,
        str(tgt_type) if tgt_type else None,
    )
    rationale: list[str] = []
    if src_type and tgt_type:
        rationale.append(
            f"Type pair {src_type} → {tgt_type} maps to {rel_type} via catalog heuristics"
        )
    else:
        rationale.append(f"Default relationship_type={rel_type} when types incomplete")

    note_blob = _blob(notes, (source or {}).get("name"), (target or {}).get("name"))
    if "route" in note_blob or "vip" in note_blob or "lb" in note_blob:
        rel_type = RelationshipType.ROUTES_TO.value
        rationale.append("Notes mention routing/LB → ROUTES_TO")
    elif "host" in note_blob or "runs on" in note_blob:
        rel_type = RelationshipType.HOSTED_ON.value
        rationale.append("Notes mention hosting → HOSTED_ON")
    elif "connect" in note_blob or "jdbc" in note_blob or "tcp" in note_blob:
        rel_type = RelationshipType.CONNECTS_TO.value
        rationale.append("Notes mention connect/protocol → CONNECTS_TO")

    suggestion = {
        "relationship_type": rel_type,
        "direction": "source → target",
        "confidence": "medium" if src_type and tgt_type else "low",
        "verification_status": "unverified",
        "discovery_method": "discovered",
        "rationale": rationale,
    }
    if source and source.get("component_id"):
        suggestion["source_component_id"] = source["component_id"]
        suggestion["source_table"] = source.get("component_type")
    if target and target.get("component_id"):
        suggestion["target_component_id"] = target["component_id"]
        suggestion["target_table"] = target.get("component_type")

    docs = RELATIONSHIP_TYPE_DOCS.get(rel_type) or {}
    suggestion["type_meaning"] = docs.get("meaning")

    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "pair_suggestion": suggestion if source and target else None,
        "neighbor_suggestions": neighbor_candidates or [],
        "safety": {
            "assist_only": True,
            "auto_apply": False,
            "human_must_confirm": True,
            "default_verification_status": "unverified",
        },
    }


def _neighbor_candidates(
    *,
    tenant_id: str,
    component: dict[str, Any],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Propose neighbor edges for one CI using type-pair rules (no LLM)."""
    ctype = str(component.get("component_type") or "")
    cid = str(component.get("component_id") or "")
    env = component.get("environment")
    out: list[dict[str, Any]] = []
    # Collect partner types where this CI is source or target in the rule table.
    as_source = [t for (s, t), _rt in _TYPE_PAIR_RULES.items() if s == ctype]
    as_target = [s for (s, t), _rt in _TYPE_PAIR_RULES.items() if t == ctype]
    partner_types = list(dict.fromkeys(as_source + as_target))
    for ptype in partner_types:
        listed = components_service.list_components(
            tenant_id=tenant_id,
            component_type=ptype,
            environment=str(env) if env else None,
            page=1,
            page_size=min(limit, 25),
        )
        for row in listed.get("items") or []:
            other_id = row.get("component_id")
            if not other_id or other_id == cid:
                continue
            if ptype in as_source:
                rel = _TYPE_PAIR_RULES.get((ctype, ptype), RelationshipType.DEPENDS_ON.value)
                out.append(
                    {
                        "source_component_id": cid,
                        "target_component_id": other_id,
                        "source_table": ctype,
                        "target_table": ptype,
                        "relationship_type": rel,
                        "confidence": "low",
                        "verification_status": "unverified",
                        "rationale": [
                            f"Neighbor heuristic: {ctype} → {ptype} typically {rel}"
                        ],
                        "peer_name": row.get("name"),
                        "peer_environment": row.get("environment"),
                    }
                )
            if ptype in as_target:
                rel = _TYPE_PAIR_RULES.get((ptype, ctype), RelationshipType.DEPENDS_ON.value)
                out.append(
                    {
                        "source_component_id": other_id,
                        "target_component_id": cid,
                        "source_table": ptype,
                        "target_table": ctype,
                        "relationship_type": rel,
                        "confidence": "low",
                        "verification_status": "unverified",
                        "rationale": [
                            f"Neighbor heuristic: {ptype} → {ctype} typically {rel}"
                        ],
                        "peer_name": row.get("name"),
                        "peer_environment": row.get("environment"),
                    }
                )
            if len(out) >= limit:
                return out[:limit]
    return out[:limit]


def _normalize_relationship_result(
    raw: dict[str, Any],
    *,
    source: str,
    model: str | None,
    fallback_reason: str | None = None,
    neighbors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pair = raw.get("pair_suggestion") if isinstance(raw.get("pair_suggestion"), dict) else None
    if pair is None and raw.get("relationship_type"):
        pair = {
            "relationship_type": raw.get("relationship_type"),
            "confidence": raw.get("confidence") or "low",
            "rationale": raw.get("rationale") or [],
        }
    if pair:
        rt = str(pair.get("relationship_type") or "").strip().upper()
        if rt not in {t.value for t in RelationshipType}:
            rt = RelationshipType.DEPENDS_ON.value
        pair = {
            **pair,
            "relationship_type": rt,
            "verification_status": "unverified",
            "discovery_method": pair.get("discovery_method") or "discovered",
            "confidence": str(pair.get("confidence") or "low").lower()
            if str(pair.get("confidence") or "low").lower() in {"low", "medium", "high"}
            else "low",
        }
    neighbor_list = raw.get("neighbor_suggestions")
    if not isinstance(neighbor_list, list):
        neighbor_list = neighbors or []
    out: dict[str, Any] = {
        "source": source,
        "model": model,
        "pair_suggestion": pair,
        "neighbor_suggestions": neighbor_list[:12],
        "safety": {
            "assist_only": True,
            "auto_apply": False,
            "human_must_confirm": True,
            "default_verification_status": "unverified",
        },
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def _validate_relationship_json(raw: dict[str, Any]) -> None:
    if "pair_suggestion" not in raw and "relationship_type" not in raw:
        raise ValueError("relationship JSON missing pair_suggestion/relationship_type")


def suggest_relationships(
    *,
    tenant_id: str,
    source_component_id: str | None = None,
    target_component_id: str | None = None,
    component_id: str | None = None,
    notes: str | None = None,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Suggest relationship type for a pair and/or neighbor edges for one CI."""
    tid = require_tenant_id(tenant_id)
    source = (
        components_service.get_component(source_component_id, tenant_id=tid)
        if source_component_id
        else None
    )
    target = (
        components_service.get_component(target_component_id, tenant_id=tid)
        if target_component_id
        else None
    )
    focus = (
        components_service.get_component(component_id, tenant_id=tid)
        if component_id
        else source or target
    )
    neighbors: list[dict[str, Any]] = []
    if focus and focus.get("component_id"):
        neighbors = _neighbor_candidates(tenant_id=tid, component=focus, limit=8)

    def _fallback(reason: str) -> dict[str, Any]:
        return build_relationship_fallback(
            source=source,
            target=target,
            notes=notes,
            reason=reason,
            neighbor_candidates=neighbors,
        )

    if not source and not target and not focus:
        return _fallback("no_components_resolved")

    catalog = [
        {"type": k, **v} for k, v in RELATIONSHIP_TYPE_DOCS.items()
    ]
    prompt_payload = {
        "source": source,
        "target": target,
        "focus_component": focus,
        "notes": notes,
        "relationship_catalog": catalog,
        "neighbor_candidates": neighbors,
        "instruction": (
            "Suggest relationship_type for the pair when both ends exist. "
            "You may re-rank neighbor_candidates but must not invent component_ids."
        ),
    }
    system = (
        "You are a CMDB topology assistant for SVRMON24. "
        "Respond with a single JSON object only. "
        "Allowed relationship_type values: HOSTED_ON, DEPENDS_ON, CONNECTS_TO, ROUTES_TO. "
        "Never invent component_ids. Suggestions are assist-only; human must create edges. "
        "New edges should use verification_status=unverified. "
        "Required keys: pair_suggestion (object|null with relationship_type, confidence, "
        "rationale array), neighbor_suggestions (array; may be empty)."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="cmdb.relationships",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Suggest CMDB relationships as JSON:\n"
                + json.dumps(prompt_payload, default=str),
            },
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_relationship_json,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        # Post-validate cited IDs against known set.
        known = {
            c
            for c in [
                (source or {}).get("component_id"),
                (target or {}).get("component_id"),
                (focus or {}).get("component_id"),
                *[n.get("source_component_id") for n in neighbors],
                *[n.get("target_component_id") for n in neighbors],
            ]
            if c
        }
        normalized = _normalize_relationship_result(
            result.payload,
            source=result.source,
            model=result.model,
            neighbors=neighbors,
        )
        pair = normalized.get("pair_suggestion")
        if isinstance(pair, dict):
            for key in ("source_component_id", "target_component_id"):
                val = pair.get(key)
                if val and known and val not in known:
                    pair.pop(key, None)
            # Re-attach resolved ends if present.
            if source and source.get("component_id"):
                pair["source_component_id"] = source["component_id"]
            if target and target.get("component_id"):
                pair["target_component_id"] = target["component_id"]
            normalized["pair_suggestion"] = pair
        # Keep neighbor list limited to candidates we already retrieved.
        allowed_pairs = {
            (n.get("source_component_id"), n.get("target_component_id"))
            for n in neighbors
        }
        filtered = []
        for item in normalized.get("neighbor_suggestions") or []:
            if not isinstance(item, dict):
                continue
            key = (item.get("source_component_id"), item.get("target_component_id"))
            if key in allowed_pairs or not neighbors:
                filtered.append(item)
        normalized["neighbor_suggestions"] = filtered[:12] if filtered else neighbors
        return normalized

    payload = result.payload
    if isinstance(payload, dict) and (
        payload.get("pair_suggestion") is not None or payload.get("neighbor_suggestions")
    ):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")


# ---------------------------------------------------------------------------
# C3 Impact narrative + C4 change-risk helper
# ---------------------------------------------------------------------------


def _impact_known_ids(impact: dict[str, Any]) -> set[str]:
    known: set[str] = set()
    selected = impact.get("selected") or {}
    if selected.get("component_id"):
        known.add(str(selected["component_id"]))
    for app in impact.get("potentially_affected_applications") or []:
        comp = app.get("component") if isinstance(app, dict) else None
        if isinstance(comp, dict) and comp.get("component_id"):
            known.add(str(comp["component_id"]))
    downstream = impact.get("downstream") or {}
    for node in downstream.get("nodes") or []:
        if isinstance(node, dict) and node.get("component_id"):
            known.add(str(node["component_id"]))
    return known


def _rank_apps(impact: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    apps: list[dict[str, Any]] = []
    for app in impact.get("potentially_affected_applications") or []:
        if not isinstance(app, dict):
            continue
        comp = app.get("component") or {}
        cid = comp.get("component_id")
        if not cid:
            continue
        apps.append(
            {
                "component_id": str(cid),
                "name": comp.get("name"),
                "environment": comp.get("environment"),
                "depth": app.get("depth"),
                "direct_or_indirect": app.get("direct_or_indirect"),
            }
        )
    return apps[:limit]


def build_impact_narrative_fallback(
    impact: dict[str, Any], *, reason: str
) -> dict[str, Any]:
    """Template narrative from graph counts only — never invents IDs."""
    selected = impact.get("selected") or {}
    cid = selected.get("component_id") or "unknown"
    apps = _rank_apps(impact)
    counts = impact.get("counts") or {}
    app_n = int(counts.get("potentially_affected_applications") or len(apps))
    node_n = int(counts.get("nodes") or 0)
    edge_n = int(counts.get("edges") or 0)
    lines = [
        f"Selected component {cid} has a downstream graph of {node_n} nodes "
        f"and {edge_n} edges (relationship data only).",
        f"{app_n} application(s) are listed as potentially affected if this "
        "component becomes unavailable.",
    ]
    if apps:
        top = ", ".join(a["component_id"] for a in apps[:5])
        lines.append(f"Top potentially affected application ids: {top}.")
    else:
        lines.append("No Application-typed nodes appear in the impact result.")
    lines.append(
        "This does not mean any dependant is currently down or degraded."
    )
    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "executive_narrative": " ".join(lines),
        "ranked_affected_apps": apps,
        "cited_component_ids": sorted(_impact_known_ids(impact)),
        "uncertainty": (
            "Rule template uses only analyze_impact counts and listed application ids."
        ),
        "disclaimer": IMPACT_DISCLAIMER,
        "safety": {
            "assist_only": True,
            "invented_ids_forbidden": True,
            "potential_impact_not_outage": True,
        },
    }


def _filter_cited_ids(raw_ids: Any, known: set[str]) -> list[str]:
    if not isinstance(raw_ids, list):
        return sorted(known)
    out: list[str] = []
    for item in raw_ids:
        cid = str(item).strip()
        if cid and cid in known and cid not in out:
            out.append(cid)
    return out or sorted(known)


def _normalize_impact_narrative(
    raw: dict[str, Any],
    *,
    impact: dict[str, Any],
    source: str,
    model: str | None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    known = _impact_known_ids(impact)
    apps = _rank_apps(impact)
    # Drop any ranked apps whose ids are not in the graph result.
    ranked_raw = raw.get("ranked_affected_apps")
    ranked: list[dict[str, Any]] = []
    if isinstance(ranked_raw, list):
        by_id = {a["component_id"]: a for a in apps}
        for item in ranked_raw:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("component_id") or "").strip()
            if cid in by_id:
                ranked.append({**by_id[cid], **{k: v for k, v in item.items() if k != "component_id"}, "component_id": cid})
    if not ranked:
        ranked = apps
    cited = _filter_cited_ids(raw.get("cited_component_ids"), known)
    narrative = str(raw.get("executive_narrative") or "").strip()
    if not narrative:
        narrative = build_impact_narrative_fallback(
            impact, reason="empty_model_narrative"
        )["executive_narrative"]
    # Strip invented ids mentioned in narrative? Post-validate by ensuring
    # cited list is authoritative for UI; narrative is advisory.
    out: dict[str, Any] = {
        "source": source,
        "model": model,
        "executive_narrative": narrative,
        "ranked_affected_apps": ranked,
        "cited_component_ids": cited,
        "uncertainty": str(raw.get("uncertainty") or "").strip()
        or "Model output constrained to graph-derived component ids.",
        "disclaimer": IMPACT_DISCLAIMER,
        "safety": {
            "assist_only": True,
            "invented_ids_forbidden": True,
            "potential_impact_not_outage": True,
        },
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def _validate_impact_json(raw: dict[str, Any]) -> None:
    if "executive_narrative" not in raw:
        raise ValueError("impact narrative JSON missing executive_narrative")


def narrate_impact(
    component_id: str,
    *,
    tenant_id: str,
    depth: int = 10,
    environment: str | None = None,
    status: str | None = None,
    table: str | None = None,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Narrate existing analyze_impact output (assist only)."""
    tid = require_tenant_id(tenant_id)
    try:
        impact = dependencies_service.analyze_impact(
            component_id,
            tenant_id=tid,
            depth=depth,
            environment=environment,
            status=status,
            table=table,
        )
    except DependencyError:
        raise

    def _fallback(reason: str) -> dict[str, Any]:
        return build_impact_narrative_fallback(impact, reason=reason)

    # Cap prompt size — structured summary only.
    prompt_impact = {
        "selected": impact.get("selected"),
        "disclaimer": impact.get("disclaimer"),
        "counts": impact.get("counts"),
        "potentially_affected_applications": [
            {
                "component_id": (a.get("component") or {}).get("component_id"),
                "name": (a.get("component") or {}).get("name"),
                "depth": a.get("depth"),
                "direct_or_indirect": a.get("direct_or_indirect"),
            }
            for a in (impact.get("potentially_affected_applications") or [])[:20]
            if isinstance(a, dict)
        ],
        "known_component_ids": sorted(_impact_known_ids(impact)),
    }
    system = (
        "You are a CMDB impact narrator for SVRMON24. "
        "Respond with a single JSON object only. "
        "Narrate ONLY the provided impact graph. Never invent component_ids. "
        "Never claim any application is currently down — impact is potential only. "
        "cited_component_ids must be a subset of known_component_ids. "
        "Required keys: executive_narrative (string), ranked_affected_apps "
        "(array of objects with component_id), cited_component_ids (array of strings), "
        "uncertainty (string)."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="cmdb.impact_narrative",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Narrate this impact package as JSON:\n"
                + json.dumps(prompt_impact, default=str),
            },
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_impact_json,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        return _normalize_impact_narrative(
            result.payload, impact=impact, source=result.source, model=result.model
        )
    payload = result.payload
    if isinstance(payload, dict) and payload.get("executive_narrative"):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")


def _risk_band(app_n: int, node_n: int, change_type: str | None) -> str:
    ct = (change_type or "").strip().lower()
    score = app_n * 2 + max(0, node_n - 1)
    if ct in {"emergency", "major"}:
        score += 4
    elif ct in {"standard", "normal"}:
        score += 1
    if score >= 10:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def build_change_risk_fallback(
    impact: dict[str, Any],
    *,
    change_type: str | None,
    window_text: str | None,
    reason: str,
) -> dict[str, Any]:
    apps = _rank_apps(impact)
    counts = impact.get("counts") or {}
    app_n = int(counts.get("potentially_affected_applications") or len(apps))
    node_n = int(counts.get("nodes") or 0)
    band = _risk_band(app_n, node_n, change_type)
    selected = impact.get("selected") or {}
    cid = selected.get("component_id") or "unknown"
    checklist = [
        "Confirm maintenance window with application owners of potentially affected apps.",
        "Verify rollback plan before change start.",
        "Re-check CMDB relationships if topology looks incomplete.",
        "Do not treat potential impact as a current outage.",
    ]
    if window_text:
        checklist.insert(0, f"Review stated window/notes: {str(window_text)[:200]}")
    narrative = (
        f"Change-risk assist for {cid}: risk band {band} based on "
        f"{app_n} potentially affected application(s) and {node_n} graph nodes. "
        f"Change type hint: {change_type or 'unspecified'}. "
        "Derived from relationship graph counts only."
    )
    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "risk_band": band,
        "narrative": narrative,
        "checklist": checklist,
        "evidence_paths": [
            {
                "component_id": a["component_id"],
                "depth": a.get("depth"),
                "direct_or_indirect": a.get("direct_or_indirect"),
            }
            for a in apps
        ],
        "cited_component_ids": sorted(_impact_known_ids(impact)),
        "disclaimer": IMPACT_DISCLAIMER,
        "safety": {
            "assist_only": True,
            "invented_ids_forbidden": True,
            "no_auto_cab": True,
            "potential_impact_not_outage": True,
        },
    }


def _normalize_change_risk(
    raw: dict[str, Any],
    *,
    impact: dict[str, Any],
    source: str,
    model: str | None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    known = _impact_known_ids(impact)
    band = str(raw.get("risk_band") or "low").strip().lower()
    if band not in {"low", "medium", "high"}:
        band = "low"
    checklist = raw.get("checklist") or []
    if isinstance(checklist, str):
        checklist = [checklist]
    if not isinstance(checklist, list):
        checklist = []
    evidence = raw.get("evidence_paths") or []
    filtered_evidence: list[dict[str, Any]] = []
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("component_id") or "").strip()
            if cid in known:
                filtered_evidence.append({"component_id": cid, **{
                    k: v for k, v in item.items() if k != "component_id"
                }})
    if not filtered_evidence:
        filtered_evidence = [
            {"component_id": a["component_id"], "depth": a.get("depth")}
            for a in _rank_apps(impact)
        ]
    out: dict[str, Any] = {
        "source": source,
        "model": model,
        "risk_band": band,
        "narrative": str(raw.get("narrative") or "").strip()
        or build_change_risk_fallback(
            impact, change_type=None, window_text=None, reason="empty_model"
        )["narrative"],
        "checklist": [str(c).strip() for c in checklist if str(c).strip()][:12],
        "evidence_paths": filtered_evidence[:20],
        "cited_component_ids": _filter_cited_ids(raw.get("cited_component_ids"), known),
        "disclaimer": IMPACT_DISCLAIMER,
        "safety": {
            "assist_only": True,
            "invented_ids_forbidden": True,
            "no_auto_cab": True,
            "potential_impact_not_outage": True,
        },
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def _validate_change_risk_json(raw: dict[str, Any]) -> None:
    if "risk_band" not in raw and "narrative" not in raw:
        raise ValueError("change risk JSON missing risk_band/narrative")


def suggest_change_risk(
    component_ids: list[str],
    *,
    tenant_id: str,
    change_type: str | None = None,
    window_text: str | None = None,
    depth: int = 10,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """CMDB-side change risk text for one or more CIs (assist only)."""
    tid = require_tenant_id(tenant_id)
    ids = [str(c).strip() for c in (component_ids or []) if str(c).strip()]
    if not ids:
        raise DependencyError("component_ids is required", status_code=422)

    # Primary narrative from the first CI; merge app lists from others.
    primary = dependencies_service.analyze_impact(
        ids[0], tenant_id=tid, depth=depth
    )
    merged_apps = {
        (a.get("component") or {}).get("component_id"): a
        for a in (primary.get("potentially_affected_applications") or [])
        if isinstance(a, dict) and (a.get("component") or {}).get("component_id")
    }
    for extra_id in ids[1:6]:
        try:
            extra = dependencies_service.analyze_impact(
                extra_id, tenant_id=tid, depth=depth
            )
        except DependencyError:
            continue
        for a in extra.get("potentially_affected_applications") or []:
            if not isinstance(a, dict):
                continue
            cid = (a.get("component") or {}).get("component_id")
            if cid and cid not in merged_apps:
                merged_apps[cid] = a
    impact = {
        **primary,
        "potentially_affected_applications": list(merged_apps.values()),
        "counts": {
            **(primary.get("counts") or {}),
            "potentially_affected_applications": len(merged_apps),
        },
        "selected_component_ids": ids,
    }

    def _fallback(reason: str) -> dict[str, Any]:
        return build_change_risk_fallback(
            impact,
            change_type=change_type,
            window_text=window_text,
            reason=reason,
        )

    prompt = {
        "component_ids": ids,
        "change_type": change_type,
        "window_text": (window_text or "")[:500],
        "disclaimer": IMPACT_DISCLAIMER,
        "counts": impact.get("counts"),
        "potentially_affected_applications": [
            {
                "component_id": (a.get("component") or {}).get("component_id"),
                "name": (a.get("component") or {}).get("name"),
                "depth": a.get("depth"),
            }
            for a in list(merged_apps.values())[:20]
        ],
        "known_component_ids": sorted(_impact_known_ids(impact)),
    }
    system = (
        "You are a CMDB change-risk assistant for SVRMON24. "
        "Respond with a single JSON object only. "
        "Use ONLY provided impact evidence. Never invent component_ids. "
        "Risk is advisory for humans (CAB); never approve or schedule changes. "
        "Required keys: risk_band (low|medium|high), narrative (string), "
        "checklist (array of strings), evidence_paths (array of objects with "
        "component_id), cited_component_ids (array of strings)."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="cmdb.change_risk",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Produce change-risk assist JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_change_risk_json,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        return _normalize_change_risk(
            result.payload, impact=impact, source=result.source, model=result.model
        )
    payload = result.payload
    if isinstance(payload, dict) and payload.get("risk_band"):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")
