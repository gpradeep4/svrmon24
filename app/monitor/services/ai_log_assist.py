"""Monitoring Log AI assists — parse fields, suggest filters, draft narratives.

Assist-only. Existing ``list_events`` filter pipeline remains source of truth.
Never auto-writes alert rules or creates ITSM incidents from LLM output.
Uses dedicated ``OLLAMA_LOG_MODEL`` (default ``qwen2.5-coder:14b``) via the
shared AI facade (cloud → Ollama → rule).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ...config import get_settings
from ...services import ai_facade as ai_facade_service
from ...services import entitlements as entitlements_service
from ...services.ai_providers import SOURCE_CLOUD, SOURCE_OLLAMA, SOURCE_RULE
from ...services.ollama_client import OllamaClient
from ...tenancy import require_tenant_id, tenant_filter
from .indexes import ensure_monitor_indexes
from .logs import EVENTS_COLLECTION, SEVERITIES

logger = logging.getLogger(__name__)

TASK_PARSE = "monitor.logs.parse"
TASK_SUGGEST_FILTERS = "monitor.logs.suggest_filters"
TASK_PREDICT_NARRATIVE = "monitor.logs.predict_narrative"
MAX_EVENTS_DEFAULT = 25
MAX_EVENTS_CAP = 50

SAFETY = {
    "assist_only": True,
    "auto_apply": False,
    "auto_write_rules": False,
    "auto_create_incidents": False,
    "human_must_confirm": True,
}

_KV_RE = re.compile(
    r"(?P<key>[A-Za-z_][\w.\-]{0,48})\s*[=:]\s*(?P<val>[^\s,;|=]{1,120})"
)
_STATUS_RE = re.compile(r"\bstatus[=:\s]+(?P<code>\d{3})\b", re.IGNORECASE)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class MonitorLogAiError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _events_coll():
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[EVENTS_COLLECTION]


def _log_ollama_client() -> OllamaClient:
    cfg = get_settings()
    return OllamaClient(
        base_url=cfg.ollama_url,
        model=(cfg.ollama_log_model or "qwen2.5-coder:14b").strip()
        or "qwen2.5-coder:14b",
        timeout_seconds=float(cfg.ollama_timeout_seconds),
    )


def _cap_max_events(value: int | None) -> int:
    if value is None:
        return MAX_EVENTS_DEFAULT
    return max(1, min(int(value), MAX_EVENTS_CAP))


def resolve_sample_messages(
    *,
    tenant_id: str,
    event_ids: list[str] | None = None,
    messages: list[str] | None = None,
    max_events: int | None = None,
) -> list[dict[str, Any]]:
    """Load tenant-scoped events and/or accept raw messages for assist prompts."""
    tid = require_tenant_id(tenant_id)
    limit = _cap_max_events(max_events)
    samples: list[dict[str, Any]] = []

    ids = [str(x).strip() for x in (event_ids or []) if str(x).strip()]
    if ids:
        ids = ids[:limit]
        cursor = _events_coll().find(
            {**tenant_filter(tid), "event_id": {"$in": ids}},
            {
                "event_id": 1,
                "message": 1,
                "severity": 1,
                "stream_id": 1,
                "component_id": 1,
                "attrs": 1,
                "source": 1,
                "observed_at": 1,
            },
        )
        by_id = {doc.get("event_id"): doc for doc in cursor}
        for eid in ids:
            doc = by_id.get(eid)
            if not doc:
                continue
            samples.append(
                {
                    "event_id": doc.get("event_id"),
                    "message": str(doc.get("message") or "")[:2000],
                    "severity": doc.get("severity"),
                    "stream_id": doc.get("stream_id"),
                    "component_id": doc.get("component_id"),
                    "attrs": doc.get("attrs") if isinstance(doc.get("attrs"), dict) else {},
                    "source": doc.get("source"),
                    "observed_at": doc.get("observed_at"),
                }
            )

    raw = [str(m).strip() for m in (messages or []) if str(m).strip()]
    for msg in raw:
        if len(samples) >= limit:
            break
        samples.append({"event_id": None, "message": msg[:2000], "attrs": {}})

    if not samples:
        raise MonitorLogAiError(
            "Provide event_ids and/or messages for Log AI assist",
            status_code=400,
        )
    return samples[:limit]


def _with_meta(
    payload: dict[str, Any],
    *,
    source: str,
    model: str | None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    out = dict(payload)
    out["source"] = source
    out["model"] = model
    out["safety"] = dict(SAFETY)
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    elif "fallback_reason" in out and source != SOURCE_RULE:
        out.pop("fallback_reason", None)
    return out


def log_ai_status(*, tenant_id: str) -> dict[str, Any]:
    """Fail-closed status for Logs UI (no write side effects)."""
    tid = require_tenant_id(tenant_id)
    cfg = get_settings()
    runtime = ai_facade_service.ai_runtime_status(tenant_id=tid)
    entitlement = entitlements_service.ollama_analysis_allowed(tid)
    log_model = (cfg.ollama_log_model or "qwen2.5-coder:14b").strip() or (
        "qwen2.5-coder:14b"
    )
    will_use_ollama = bool(runtime.get("will_use_ollama"))
    will_use_cloud = bool(runtime.get("will_use_cloud"))
    return {
        "assist_only": True,
        "ollama_enabled": bool(cfg.ollama_enabled),
        "log_model": log_model,
        "default_model": cfg.ollama_model,
        "will_use_ollama": will_use_ollama,
        "will_use_cloud": will_use_cloud,
        "rule_fallback_always_available": True,
        "entitlement": entitlement,
        "shared_local_contention": runtime.get("shared_local_contention"),
        "safety": dict(SAFETY),
        "tasks": ["parse", "suggest_filters", "predict_narrative"],
        "filters_authoritative": True,
        "auto_write_rules": False,
        "auto_create_incidents": False,
    }


def _rule_extract_fields(message: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    fields: list[dict[str, Any]] = []
    attrs: dict[str, str] = {}
    text = message or ""

    status = _STATUS_RE.search(text)
    if status:
        code = status.group("code")
        fields.append(
            {
                "name": "status",
                "value": code,
                "confidence": "high",
                "evidence": status.group(0)[:80],
            }
        )
        attrs["status"] = code

    for match in _KV_RE.finditer(text):
        key = match.group("key").lower()
        val = match.group("val")
        if key in attrs:
            continue
        if key in {"http", "https", "the", "and", "for"}:
            continue
        attrs[key] = val
        fields.append(
            {
                "name": key,
                "value": val,
                "confidence": "medium",
                "evidence": match.group(0)[:80],
            }
        )
        if len(fields) >= 12:
            break

    ip = _IP_RE.search(text)
    if ip and "client_ip" not in attrs:
        attrs["client_ip"] = ip.group(0)
        fields.append(
            {
                "name": "client_ip",
                "value": ip.group(0),
                "confidence": "medium",
                "evidence": ip.group(0),
            }
        )

    return fields, attrs


def build_parse_fallback(
    samples: list[dict[str, Any]], *, reason: str
) -> dict[str, Any]:
    all_fields: list[dict[str, Any]] = []
    merged_attrs: dict[str, str] = {}
    for sample in samples:
        fields, attrs = _rule_extract_fields(str(sample.get("message") or ""))
        for field in fields:
            all_fields.append(field)
        merged_attrs.update(attrs)
    # Dedupe by name keeping first
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for field in all_fields:
        name = str(field.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(field)
    return _with_meta(
        {
            "fields": unique[:20],
            "attrs_suggestions": merged_attrs,
            "summary": (
                f"Rule parse of {len(samples)} sample line(s); "
                f"extracted {len(unique)} field name(s)."
            ),
            "sample_count": len(samples),
        },
        source=SOURCE_RULE,
        model=None,
        fallback_reason=reason,
    )


def _validate_parse(raw: dict[str, Any]) -> None:
    if not isinstance(raw.get("fields"), list):
        raise ValueError("parse JSON missing fields[]")
    if "summary" not in raw:
        raise ValueError("parse JSON missing summary")


def _normalize_parse(
    raw: dict[str, Any], *, source: str, model: str | None
) -> dict[str, Any]:
    fields_in = raw.get("fields") if isinstance(raw.get("fields"), list) else []
    fields: list[dict[str, Any]] = []
    attrs: dict[str, str] = {}
    if isinstance(raw.get("attrs_suggestions"), dict):
        for k, v in raw["attrs_suggestions"].items():
            if k and v is not None:
                attrs[str(k)[:64]] = str(v)[:120]
    for item in fields_in[:20]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:64]
        value = str(item.get("value") if item.get("value") is not None else "").strip()[
            :120
        ]
        if not name:
            continue
        conf = str(item.get("confidence") or "medium").lower()
        if conf not in {"low", "medium", "high"}:
            conf = "medium"
        fields.append(
            {
                "name": name,
                "value": value,
                "confidence": conf,
                "evidence": str(item.get("evidence") or "")[:120],
            }
        )
        attrs.setdefault(name, value)
    return _with_meta(
        {
            "fields": fields,
            "attrs_suggestions": attrs,
            "summary": str(raw.get("summary") or "Parsed log sample(s).")[:800],
            "sample_count": raw.get("sample_count"),
        },
        source=source,
        model=model,
    )


def parse_log_fields(
    *,
    tenant_id: str,
    event_ids: list[str] | None = None,
    messages: list[str] | None = None,
    max_events: int | None = None,
    force_fallback: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    samples = resolve_sample_messages(
        tenant_id=tid,
        event_ids=event_ids,
        messages=messages,
        max_events=max_events,
    )

    def _fallback(reason: str) -> dict[str, Any]:
        return build_parse_fallback(samples, reason=reason)

    prompt = {
        "samples": [
            {
                "event_id": s.get("event_id"),
                "severity": s.get("severity"),
                "message": s.get("message"),
                "attrs": s.get("attrs") or {},
            }
            for s in samples
        ],
        "instructions": (
            "Extract structured key/value fields from log messages. "
            "Assist only — do not invent alert rules or incidents."
        ),
    }
    system = (
        "You are a log parsing assistant for SVRMON24 Monitoring. "
        "Respond with a single JSON object only. "
        "Required keys: fields (array of {name,value,confidence,evidence}), "
        "attrs_suggestions (object), summary (string), "
        "confidence values low|medium|high. Assist only."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key=TASK_PARSE,
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Parse these log samples as JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_parse,
        force_fallback=force_fallback,
        record_usage=True,
        ollama_client=_log_ollama_client(),
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        normalized = _normalize_parse(
            result.payload, source=result.source, model=result.model
        )
        normalized["sample_count"] = len(samples)
        return normalized
    payload = result.payload if isinstance(result.payload, dict) else {}
    if payload.get("fields") is not None:
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")


def build_suggest_filters_fallback(
    samples: list[dict[str, Any]],
    *,
    current_filters: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    severities = [
        str(s.get("severity") or "").lower()
        for s in samples
        if str(s.get("severity") or "").lower() in SEVERITIES
    ]
    err_like = [s for s in severities if s in {"error", "critical", "warning"}]
    severity_suggest = ""
    if err_like:
        uniq = sorted(set(err_like), key=lambda x: SEVERITIES.index(x))
        severity_suggest = ",".join(uniq)
    elif current_filters and current_filters.get("severity"):
        severity_suggest = str(current_filters.get("severity"))

    phrase = None
    for sample in samples:
        msg = str(sample.get("message") or "")
        for token in (
            "Upstream timeout",
            "Authentication failure",
            "Health check failed",
            "Elevated latency",
        ):
            if token.lower() in msg.lower():
                phrase = token
                break
        if phrase:
            break
    if not phrase and samples:
        words = re.findall(r"[A-Za-z]{5,}", str(samples[0].get("message") or ""))
        if words:
            phrase = words[0]

    q = f'"{phrase}"' if phrase and " " in phrase else (phrase or "")
    attrs: list[str] = []
    _, extracted = _rule_extract_fields(str(samples[0].get("message") or "") if samples else "")
    for key in list(extracted.keys())[:2]:
        attrs.append(f"{key}:{extracted[key]}")

    rationale = [
        "Rule heuristics from sample severities and message tokens.",
        "Existing list_events filters remain authoritative — apply in UI only.",
    ]
    if reason:
        rationale.append(f"Fallback reason: {reason}")

    return _with_meta(
        {
            "suggested_filters": {
                "q": q,
                "severity": severity_suggest,
                "attr": attrs,
                "stream_id": (current_filters or {}).get("stream_id"),
                "component_id": (current_filters or {}).get("component_id"),
                "source": (current_filters or {}).get("source"),
            },
            "suggested_log_match": {
                "severity": (severity_suggest.split(",")[0] if severity_suggest else None),
                "message_contains": phrase,
            },
            "rationale": rationale,
            "confidence": "low" if reason else "medium",
            "sample_count": len(samples),
            "note": (
                "Draft only — does not write alert rules. Human must create rules "
                "via Alerts UI/API if desired."
            ),
        },
        source=SOURCE_RULE,
        model=None,
        fallback_reason=reason,
    )


def _validate_suggest(raw: dict[str, Any]) -> None:
    if not isinstance(raw.get("suggested_filters"), dict):
        raise ValueError("suggest_filters JSON missing suggested_filters")


def _normalize_suggest(
    raw: dict[str, Any], *, source: str, model: str | None
) -> dict[str, Any]:
    filters_in = raw.get("suggested_filters") if isinstance(raw.get("suggested_filters"), dict) else {}
    attr_raw = filters_in.get("attr")
    if isinstance(attr_raw, list):
        attr = [str(a)[:120] for a in attr_raw if str(a).strip()][:8]
    elif isinstance(attr_raw, str) and attr_raw.strip():
        attr = [attr_raw.strip()[:120]]
    else:
        attr = []
    suggested_filters = {
        "q": str(filters_in.get("q") or "")[:240] or None,
        "severity": str(filters_in.get("severity") or "")[:80] or None,
        "attr": attr,
        "stream_id": filters_in.get("stream_id"),
        "component_id": filters_in.get("component_id"),
        "source": filters_in.get("source"),
    }
    log_match = raw.get("suggested_log_match")
    if not isinstance(log_match, dict):
        log_match = {}
    rationale = raw.get("rationale")
    if not isinstance(rationale, list):
        rationale = [str(rationale)] if rationale else []
    conf = str(raw.get("confidence") or "medium").lower()
    if conf not in {"low", "medium", "high"}:
        conf = "medium"
    return _with_meta(
        {
            "suggested_filters": suggested_filters,
            "suggested_log_match": {
                "severity": log_match.get("severity"),
                "message_contains": (
                    str(log_match.get("message_contains") or "")[:240] or None
                ),
            },
            "rationale": [str(r)[:240] for r in rationale[:8]],
            "confidence": conf,
            "note": (
                "Draft only — does not write alert rules. Human must create rules "
                "via Alerts UI/API if desired."
            ),
        },
        source=source,
        model=model,
    )


def suggest_log_filters(
    *,
    tenant_id: str,
    event_ids: list[str] | None = None,
    messages: list[str] | None = None,
    current_filters: dict[str, Any] | None = None,
    max_events: int | None = None,
    force_fallback: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    samples = resolve_sample_messages(
        tenant_id=tid,
        event_ids=event_ids,
        messages=messages,
        max_events=max_events,
    )
    filters = current_filters if isinstance(current_filters, dict) else {}

    def _fallback(reason: str) -> dict[str, Any]:
        return build_suggest_filters_fallback(
            samples, current_filters=filters, reason=reason
        )

    prompt = {
        "samples": [
            {
                "event_id": s.get("event_id"),
                "severity": s.get("severity"),
                "message": s.get("message"),
                "stream_id": s.get("stream_id"),
                "component_id": s.get("component_id"),
            }
            for s in samples
        ],
        "current_filters": filters,
        "allowed_severities": list(SEVERITIES),
        "instructions": (
            "Suggest tighter search filters for the Logs UI and an optional "
            "log_match draft for alert rules. Do NOT claim rules were created."
        ),
    }
    system = (
        "You are a log search assist for SVRMON24. Respond with JSON only. "
        "Required: suggested_filters object with q, severity, attr (array), "
        "optional stream_id/component_id/source; suggested_log_match with "
        "severity and message_contains; rationale (array); confidence "
        "(low|medium|high). Assist only — never write rules or incidents."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key=TASK_SUGGEST_FILTERS,
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Suggest log filters as JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_suggest,
        force_fallback=force_fallback,
        record_usage=True,
        ollama_client=_log_ollama_client(),
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        out = _normalize_suggest(
            result.payload, source=result.source, model=result.model
        )
        out["sample_count"] = len(samples)
        return out
    payload = result.payload if isinstance(result.payload, dict) else {}
    if isinstance(payload.get("suggested_filters"), dict):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")


def build_predict_narrative_fallback(
    samples: list[dict[str, Any]], *, reason: str
) -> dict[str, Any]:
    sev_counts: dict[str, int] = {}
    for sample in samples:
        sev = str(sample.get("severity") or "info").lower()
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
    errors = sev_counts.get("error", 0) + sev_counts.get("critical", 0)
    warnings = sev_counts.get("warning", 0)
    signals: list[str] = []
    if errors:
        signals.append(f"{errors} error/critical sample(s) in the window")
    if warnings:
        signals.append(f"{warnings} warning sample(s) in the window")
    for sample in samples[:5]:
        msg = str(sample.get("message") or "")
        if "timeout" in msg.lower():
            signals.append("timeout language present in messages")
            break
    for sample in samples[:5]:
        msg = str(sample.get("message") or "")
        if "auth" in msg.lower() or "authentication" in msg.lower():
            signals.append("authentication-related messages present")
            break
    if not signals:
        signals.append("No strong anomaly signal from rule heuristics")

    narrative = (
        f"Across {len(samples)} sample log line(s), severity mix is "
        f"{sev_counts or {'info': 0}}. "
    )
    if errors:
        narrative += (
            "Elevated error/critical volume may continue if the underlying "
            "dependency or auth path is not remediated. "
        )
    else:
        narrative += (
            "No strong error surge in this sample; continue watching with "
            "current filters. "
        )
    narrative += (
        "This is an assist draft only — not an automated prediction, SLO "
        "breach, or ticket."
    )
    return _with_meta(
        {
            "narrative": narrative,
            "signals": signals[:8],
            "confidence": "low",
            "disclaimer": (
                "Assist draft only — not an automated prediction or ticket. "
                "Human must approve any write."
            ),
            "sample_count": len(samples),
            "fallback_reason": reason,
        },
        source=SOURCE_RULE,
        model=None,
        fallback_reason=reason,
    )


def _validate_narrative(raw: dict[str, Any]) -> None:
    if not str(raw.get("narrative") or "").strip():
        raise ValueError("predict_narrative JSON missing narrative")


def _normalize_narrative(
    raw: dict[str, Any], *, source: str, model: str | None
) -> dict[str, Any]:
    signals = raw.get("signals")
    if not isinstance(signals, list):
        signals = [str(signals)] if signals else []
    conf = str(raw.get("confidence") or "medium").lower()
    if conf not in {"low", "medium", "high"}:
        conf = "medium"
    return _with_meta(
        {
            "narrative": str(raw.get("narrative") or "")[:2000],
            "signals": [str(s)[:240] for s in signals[:8]],
            "confidence": conf,
            "disclaimer": str(
                raw.get("disclaimer")
                or (
                    "Assist draft only — not an automated prediction or ticket. "
                    "Human must approve any write."
                )
            )[:400],
        },
        source=source,
        model=model,
    )


def predict_log_narrative(
    *,
    tenant_id: str,
    event_ids: list[str] | None = None,
    messages: list[str] | None = None,
    current_filters: dict[str, Any] | None = None,
    max_events: int | None = None,
    force_fallback: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    samples = resolve_sample_messages(
        tenant_id=tid,
        event_ids=event_ids,
        messages=messages,
        max_events=max_events,
    )

    def _fallback(reason: str) -> dict[str, Any]:
        return build_predict_narrative_fallback(samples, reason=reason)

    prompt = {
        "samples": [
            {
                "severity": s.get("severity"),
                "message": s.get("message"),
                "stream_id": s.get("stream_id"),
                "component_id": s.get("component_id"),
                "observed_at": s.get("observed_at"),
            }
            for s in samples
        ],
        "current_filters": current_filters or {},
        "instructions": (
            "Draft a short prediction/trend narrative. Do not open tickets or "
            "claim automated forecasting."
        ),
    }
    system = (
        "You are a log trend narrative assistant for SVRMON24. "
        "Respond with JSON only. Required keys: narrative (string), "
        "signals (array of strings), confidence (low|medium|high), "
        "disclaimer (string). Assist only — never create incidents or rules."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key=TASK_PREDICT_NARRATIVE,
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Draft a log prediction narrative as JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_narrative,
        force_fallback=force_fallback,
        record_usage=True,
        ollama_client=_log_ollama_client(),
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        out = _normalize_narrative(
            result.payload, source=result.source, model=result.model
        )
        out["sample_count"] = len(samples)
        return out
    payload = result.payload if isinstance(result.payload, dict) else {}
    if payload.get("narrative"):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")
