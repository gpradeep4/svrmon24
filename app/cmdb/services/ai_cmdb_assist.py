"""CMDB AI assists — CI classification (C1) and relationship suggestions (C2).

Assist / suggestion only. Apply writes go through normal create/update APIs.
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
