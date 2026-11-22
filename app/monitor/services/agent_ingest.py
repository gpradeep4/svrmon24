"""Agent telemetry ingest — metrics / logs / file-events (L5).

Authenticated agents push LIVE samples behind ``agent_ingest`` gates.
Dedup uses ``monitor_ingest_cursors`` (per agent + channel + optional key).
Multi-OS contract: payload ``os_family`` must match the registered agent
(linux / windows / macos / unix) with documented watcher + metric shapes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pymongo.collection import Collection

from ...config import Settings, get_settings
from ...serialization import serialize_document
from ...services import entitlements as entitlements_service
from ...services.entitlements import EntitlementError
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from . import agents as agents_service
from . import file_monitoring as file_service
from . import ingest as ingest_service
from .indexes import ensure_monitor_indexes
from .live_gates import live_allowed
from .logs import ensure_default_streams
from .targets import enforce_metric_samples_retention

CURSORS_COLLECTION = "monitor_ingest_cursors"
SAMPLES_COLLECTION = "metric_samples"
FILE_EVENTS_COLLECTION = "file_version_events"
FILE_TARGETS_COLLECTION = "file_watch_targets"
STREAMS_COLLECTION = "log_streams"

DEFAULT_MAX_ITEMS = 100
DEFAULT_MAX_BODY_BYTES = 1_048_576

Channel = Literal["metrics", "logs", "file_events"]

OS_FAMILIES = frozenset({"linux", "windows", "macos", "unix"})

# Multi-OS contract — canonical metric names agents should emit.
OS_CORE_METRICS: tuple[str, ...] = (
    "cpu.usage_pct",
    "mem.used_pct",
    "disk.used_pct",
)

# OS watcher identifiers for agent file-event payloads (L5/L6 contract).
OS_WATCHERS: dict[str, str] = {
    "linux": "inotify",
    "windows": "readdirectorychanges",
    "macos": "fsevents",
    "unix": "kqueue_or_poll",
}
VALID_OS_WATCHERS = frozenset(OS_WATCHERS.values())

CHANGE_KINDS = frozenset(
    {"created", "modified", "renamed", "deleted", "permission"}
)


class AgentIngestError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cursors() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[CURSORS_COLLECTION]


def _samples() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[SAMPLES_COLLECTION]


def _file_events() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[FILE_EVENTS_COLLECTION]


def _file_targets() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[FILE_TARGETS_COLLECTION]


def _streams() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[STREAMS_COLLECTION]


def _new_sample_id() -> str:
    return f"ms-{uuid.uuid4().hex[:12]}"


def _new_file_event_id() -> str:
    return f"fve-{uuid.uuid4().hex[:12]}"


def _parse_observed(raw: Any, *, default: datetime, label: str) -> datetime:
    if raw is None:
        return default
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        text = str(raw).strip().replace("Z", "+00:00")
        observed = datetime.fromisoformat(text)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed
    except ValueError as exc:
        raise AgentIngestError(f"{label}: invalid observed_at/changed_at", status_code=422) from exc


def assert_agent_ingest_allowed(
    *,
    tenant_id: str,
    settings: Settings | None = None,
) -> None:
    if not live_allowed(
        tenant_id=tenant_id, capability="agent_ingest", settings=settings
    ):
        raise AgentIngestError(
            "Live agent ingest is disabled (platform and/or tenant gate).",
            status_code=403,
        )


def assert_agent_entitlement(*, tenant_id: str) -> None:
    """Enforce ``monitor_agents`` still allows this tenant's active agents."""
    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.monitor_agents_limit(tid)
    if limit is None:
        return
    total = agents_service.count_monitor_agents(tenant_id=tid, active_only=True)
    if total > limit:
        raise EntitlementError(
            f"Agent entitlement exceeded ({total}/{limit}). "
            "Revoke agents or upgrade entitlements before ingest.",
            status_code=403,
        )


def validate_os_family(
    *,
    agent: dict[str, Any],
    payload_os_family: str | None,
) -> str:
    """Ensure batch os_family matches the registered agent (multi-OS contract)."""
    registered = str(agent.get("os_family") or "linux").strip().lower()
    if registered not in OS_FAMILIES:
        registered = "linux"
    if payload_os_family is None or not str(payload_os_family).strip():
        return registered
    family = str(payload_os_family).strip().lower()
    if family not in OS_FAMILIES:
        raise AgentIngestError(
            f"os_family must be one of: {', '.join(sorted(OS_FAMILIES))}",
            status_code=422,
        )
    if family != registered:
        raise AgentIngestError(
            f"os_family '{family}' does not match registered agent "
            f"os_family '{registered}'",
            status_code=422,
        )
    return family


def os_contract_meta() -> dict[str, Any]:
    """Documented multi-OS ingest contract for meta + fixture clients."""
    return {
        "os_families": sorted(OS_FAMILIES),
        "core_metrics": list(OS_CORE_METRICS),
        "os_watchers": dict(OS_WATCHERS),
        "channels": ["metrics", "logs", "file_events"],
        "dedup": {
            "field": "seq",
            "collection": CURSORS_COLLECTION,
            "rule": "batches with seq <= last_seq for (agent_id, channel, key) are skipped",
        },
        "endpoints": {
            "metrics": "/api/monitor/ingest/metrics",
            "logs": "/api/monitor/ingest/logs",
            "file_events": "/api/monitor/ingest/file-events",
            "desired_state": "/api/monitor/agents/{agent_id}/desired-state",
        },
        "notes": (
            "Agents push LIVE batches with Authorization: Bearer mat_… "
            "(or X-Monitor-Agent-Token). Payload os_family must match the "
            "registered agent. File events should set os_watcher per OS "
            f"({', '.join(f'{k}={v}' for k, v in OS_WATCHERS.items())}). "
            "Existing watches must have watch_mode=AGENT (L6); SIMULATED / "
            "AGENTLESS_POLL targets reject agent file-events. "
            "Production-signed installers are out of scope."
        ),
        "file_watch_modes": ["SIMULATED", "AGENT", "AGENTLESS_POLL"],
        "agent_watcher_schema": {
            "required": ["path_or_watch_id", "change_kind"],
            "change_kinds": sorted(CHANGE_KINDS),
            "os_watcher_by_family": dict(OS_WATCHERS),
            "execution_mode": "LIVE",
            "data_source": "AGENT_FILE_WATCH",
        },
    }


def _cursor_key(
    *,
    agent_id: str,
    channel: Channel,
    key: str | None = None,
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "channel": channel,
        "key": (key or "").strip() or "_",
    }


def get_cursor(
    *,
    tenant_id: str,
    agent_id: str,
    channel: Channel,
    key: str | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    filt = merge_tenant_filter(
        _cursor_key(agent_id=agent_id, channel=channel, key=key),
        tid,
    )
    doc = _cursors().find_one(filt)
    if not doc:
        return {
            "agent_id": agent_id,
            "channel": channel,
            "key": (key or "").strip() or "_",
            "last_seq": 0,
            "tenant_id": tid,
        }
    out = serialize_document(doc) or {}
    out.pop("_id", None)
    return out


def advance_cursor(
    *,
    tenant_id: str,
    agent_id: str,
    channel: Channel,
    seq: int,
    key: str | None = None,
) -> dict[str, Any]:
    """Advance last_seq when ``seq`` is strictly greater (monotonic)."""
    tid = require_tenant_id(tenant_id)
    now = _now()
    filt = merge_tenant_filter(
        _cursor_key(agent_id=agent_id, channel=channel, key=key),
        tid,
    )
    existing = _cursors().find_one(filt)
    last = int(existing.get("last_seq") or 0) if existing else 0
    if int(seq) <= last:
        return {
            "advanced": False,
            "duplicate": True,
            "last_seq": last,
            "seq": int(seq),
        }
    doc = stamp_tenant_id(
        {
            **_cursor_key(agent_id=agent_id, channel=channel, key=key),
            "last_seq": int(seq),
            "updated_at": now,
            "created_at": (existing or {}).get("created_at") or now,
        },
        tenant_id=tid,
    )
    _cursors().update_one(
        filt,
        {"$set": doc},
        upsert=True,
    )
    return {
        "advanced": True,
        "duplicate": False,
        "last_seq": int(seq),
        "seq": int(seq),
    }


def _check_seq_dedup(
    *,
    tenant_id: str,
    agent_id: str,
    channel: Channel,
    seq: int | None,
    key: str | None = None,
) -> dict[str, Any] | None:
    """Return a duplicate response dict when seq is not advancing; else None."""
    if seq is None:
        return None
    try:
        seq_i = int(seq)
    except (TypeError, ValueError) as exc:
        raise AgentIngestError("seq must be an integer", status_code=422) from exc
    if seq_i < 1:
        raise AgentIngestError("seq must be >= 1", status_code=422)
    cursor = get_cursor(
        tenant_id=tenant_id, agent_id=agent_id, channel=channel, key=key
    )
    last = int(cursor.get("last_seq") or 0)
    if seq_i <= last:
        return {
            "ok": True,
            "execution_mode": "LIVE",
            "data_source": "AGENT",
            "accepted": 0,
            "rejected": 0,
            "deduped": True,
            "duplicate": True,
            "seq": seq_i,
            "last_seq": last,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "channel": channel,
            "live_probes": True,
        }
    return None


def get_desired_state(*, tenant_id: str, agent_id: str) -> dict[str, Any]:
    """Minimal desired-state: watch_ids / stream_ids / target_ids for the agent.

    Only ``watch_mode=AGENT`` targets are returned (L6).
    """
    tid = require_tenant_id(tenant_id)
    agent = agents_service.get_agent(tenant_id=tid, agent_id=agent_id)
    watch_ids = list(agent.get("desired_watch_ids") or [])
    stream_ids = list(agent.get("desired_stream_ids") or [])
    target_ids = list(agent.get("desired_target_ids") or [])

    # Surface watches already tagged with this agent_id in AGENT mode.
    tagged = list(
        _file_targets().find(
            merge_tenant_filter(
                {"agent_id": agent_id, "watch_mode": "AGENT"},
                tid,
            ),
            {"watch_id": 1},
        )
    )
    for row in tagged:
        wid = str(row.get("watch_id") or "").strip()
        if wid and wid not in watch_ids:
            watch_ids.append(wid)

    # Drop desired ids that are not AGENT-mode (SIMULATED / AGENTLESS_POLL).
    if watch_ids:
        allowed: list[str] = []
        for wid in watch_ids:
            doc = _file_targets().find_one(
                merge_tenant_filter({"watch_id": wid}, tid)
            )
            if doc is None:
                continue
            if str(doc.get("watch_mode") or "SIMULATED") == "AGENT":
                allowed.append(wid)
        watch_ids = allowed

    return {
        "agent_id": agent_id,
        "tenant_id": tid,
        "os_family": agent.get("os_family"),
        "os_watcher": OS_WATCHERS.get(str(agent.get("os_family") or "linux")),
        "watch_ids": watch_ids,
        "stream_ids": stream_ids,
        "target_ids": target_ids,
        "watch_mode": "AGENT",
        "contract": os_contract_meta(),
    }


def set_desired_state(
    *,
    tenant_id: str,
    agent_id: str,
    watch_ids: list[str] | None = None,
    stream_ids: list[str] | None = None,
    target_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Admin sets minimal desired-state lists on the agent document."""
    tid = require_tenant_id(tenant_id)
    aid = (agent_id or "").strip()
    updates: dict[str, Any] = {"desired_updated_at": _now()}
    if watch_ids is not None:
        updates["desired_watch_ids"] = [
            str(x).strip() for x in watch_ids if str(x).strip()
        ]
    if stream_ids is not None:
        # Validate streams exist when provided.
        ensure_default_streams(tenant_id=tid)
        cleaned: list[str] = []
        for sid in stream_ids:
            s = str(sid).strip()
            if not s:
                continue
            if not _streams().find_one(merge_tenant_filter({"stream_id": s}, tid)):
                raise AgentIngestError(f"stream_id '{s}' not found", status_code=404)
            cleaned.append(s)
        updates["desired_stream_ids"] = cleaned
    if target_ids is not None:
        updates["desired_target_ids"] = [
            str(x).strip() for x in target_ids if str(x).strip()
        ]

    try:
        agents_service.patch_agent_fields(
            tenant_id=tid, agent_id=aid, fields=updates
        )
    except agents_service.MonitorAgentsError as exc:
        raise AgentIngestError(exc.message, status_code=exc.status_code) from exc
    return get_desired_state(tenant_id=tid, agent_id=aid)


def ingest_metrics(
    *,
    tenant_id: str,
    agent: dict[str, Any],
    samples: list[dict[str, Any]],
    os_family: str | None = None,
    seq: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Write LIVE metric_samples from an authenticated agent."""
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    assert_agent_ingest_allowed(tenant_id=tid, settings=cfg)
    assert_agent_entitlement(tenant_id=tid)
    agent_id = str(agent.get("agent_id") or "")
    if not agent_id:
        raise AgentIngestError("agent_id required", status_code=401)
    family = validate_os_family(agent=agent, payload_os_family=os_family)

    dup = _check_seq_dedup(
        tenant_id=tid, agent_id=agent_id, channel="metrics", seq=seq
    )
    if dup:
        return dup

    batch = list(samples or [])
    if len(batch) > DEFAULT_MAX_ITEMS:
        raise AgentIngestError(
            f"batch exceeds max items ({DEFAULT_MAX_ITEMS})",
            status_code=413,
        )
    if not batch:
        if seq is not None:
            advance_cursor(
                tenant_id=tid, agent_id=agent_id, channel="metrics", seq=int(seq)
            )
        return {
            "ok": True,
            "execution_mode": "LIVE",
            "data_source": "AGENT",
            "accepted": 0,
            "rejected": 0,
            "deduped": False,
            "tenant_id": tid,
            "agent_id": agent_id,
            "os_family": family,
            "live_probes": True,
        }

    now = _now()
    prepared: list[dict[str, Any]] = []
    errors: list[str] = []
    for idx, raw in enumerate(batch):
        if not isinstance(raw, dict):
            errors.append(f"sample[{idx}]: must be an object")
            continue
        metric_name = str(raw.get("metric_name") or "").strip()
        if not metric_name or len(metric_name) > 128:
            errors.append(f"sample[{idx}]: metric_name is required")
            continue
        if "value" not in raw:
            errors.append(f"sample[{idx}]: value is required")
            continue
        try:
            value = float(raw["value"])
        except (TypeError, ValueError):
            errors.append(f"sample[{idx}]: value must be a number")
            continue
        target_id = str(raw.get("target_id") or "").strip() or None
        component_id = (
            str(raw.get("component_id") or "").strip()
            or target_id
            or agent_id
        )
        if not target_id:
            # Agents may omit target_id; bind to agent-scoped synthetic id.
            target_id = f"agent:{agent_id}"
        try:
            observed_at = _parse_observed(
                raw.get("observed_at"), default=now, label=f"sample[{idx}]"
            )
        except AgentIngestError as exc:
            errors.append(exc.message)
            continue
        unit = raw.get("unit")
        attrs = raw.get("attrs") if isinstance(raw.get("attrs"), dict) else {}
        prepared.append(
            stamp_tenant_id(
                {
                    "sample_id": _new_sample_id(),
                    "target_id": target_id,
                    "component_id": component_id,
                    "metric_name": metric_name,
                    "value": value,
                    "unit": (str(unit).strip() if unit is not None else None) or None,
                    "observed_at": observed_at,
                    "data_source": "AGENT",
                    "collect_mode": "AGENT",
                    "execution_mode": "LIVE",
                    "agent_id": agent_id,
                    "os_family": family,
                    "attrs": {
                        **attrs,
                        "ingest": True,
                        "os_family": family,
                    },
                    "created_at": now,
                },
                tenant_id=tid,
            )
        )

    rejected = len(errors)
    if prepared:
        _samples().insert_many(prepared)
        try:
            enforce_metric_samples_retention(tenant_id=tid)
        except Exception:  # noqa: BLE001 — retention must not fail ingest
            pass
        # Touch agent last_seen.
        try:
            agents_service.heartbeat_agent(
                agent_id=agent_id, tenant_id=tid, settings=cfg
            )
        except Exception:  # noqa: BLE001
            pass

    last_seq = None
    if seq is not None and prepared:
        advanced = advance_cursor(
            tenant_id=tid, agent_id=agent_id, channel="metrics", seq=int(seq)
        )
        last_seq = advanced.get("last_seq")
    elif seq is not None and not prepared:
        # Do not advance cursor when nothing accepted.
        last_seq = get_cursor(
            tenant_id=tid, agent_id=agent_id, channel="metrics"
        ).get("last_seq")

    return {
        "ok": bool(prepared) or rejected == 0,
        "execution_mode": "LIVE",
        "data_source": "AGENT",
        "accepted": len(prepared),
        "rejected": rejected,
        "deduped": False,
        "errors": errors,
        "tenant_id": tid,
        "agent_id": agent_id,
        "os_family": family,
        "seq": seq,
        "last_seq": last_seq,
        "live_probes": True,
        "core_metrics": list(OS_CORE_METRICS),
    }


def ingest_file_events(
    *,
    tenant_id: str,
    agent: dict[str, Any],
    events: list[dict[str, Any]],
    os_family: str | None = None,
    seq: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Write LIVE file_version_events from an authenticated agent."""
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    assert_agent_ingest_allowed(tenant_id=tid, settings=cfg)
    assert_agent_entitlement(tenant_id=tid)
    agent_id = str(agent.get("agent_id") or "")
    if not agent_id:
        raise AgentIngestError("agent_id required", status_code=401)
    family = validate_os_family(agent=agent, payload_os_family=os_family)
    default_watcher = OS_WATCHERS[family]

    dup = _check_seq_dedup(
        tenant_id=tid, agent_id=agent_id, channel="file_events", seq=seq
    )
    if dup:
        return dup

    batch = list(events or [])
    if len(batch) > DEFAULT_MAX_ITEMS:
        raise AgentIngestError(
            f"batch exceeds max items ({DEFAULT_MAX_ITEMS})",
            status_code=413,
        )
    if not batch:
        if seq is not None:
            advance_cursor(
                tenant_id=tid,
                agent_id=agent_id,
                channel="file_events",
                seq=int(seq),
            )
        return {
            "ok": True,
            "execution_mode": "LIVE",
            "data_source": "AGENT_FILE_WATCH",
            "accepted": 0,
            "rejected": 0,
            "deduped": False,
            "tenant_id": tid,
            "agent_id": agent_id,
            "os_family": family,
            "os_watcher": default_watcher,
            "live_probes": True,
        }

    # Ensure SIMULATED seeds exist so demo watches are available for lab binding.
    try:
        file_service.ensure_simulated_seed(tenant_id=tid)
    except Exception:  # noqa: BLE001
        pass

    now = _now()
    prepared: list[dict[str, Any]] = []
    errors: list[str] = []
    watch_updates: dict[str, dict[str, Any]] = {}

    for idx, raw in enumerate(batch):
        if not isinstance(raw, dict):
            errors.append(f"event[{idx}]: must be an object")
            continue
        watch_id = str(raw.get("watch_id") or "").strip()
        path = str(raw.get("path") or "").strip()
        if not watch_id and not path:
            errors.append(f"event[{idx}]: watch_id or path is required")
            continue
        target = None
        if watch_id:
            target = _file_targets().find_one(
                merge_tenant_filter({"watch_id": watch_id}, tid)
            )
        if target is None and path:
            target = _file_targets().find_one(
                merge_tenant_filter({"path": path}, tid)
            )
            if target:
                watch_id = str(target.get("watch_id") or watch_id)
        if target is None:
            # Auto-bind a LIVE AGENT watch for new agent-reported paths.
            if not path:
                errors.append(f"event[{idx}]: unknown watch_id '{watch_id}'")
                continue
            if not watch_id:
                watch_id = f"fw-agent-{uuid.uuid4().hex[:10]}"
            target = stamp_tenant_id(
                {
                    "watch_id": watch_id,
                    "path": path,
                    "label": str(raw.get("label") or path).strip()[:128],
                    "host": agent.get("hostname"),
                    "component_id": raw.get("component_id"),
                    "status": "active",
                    "execution_mode": "LIVE",
                    "watch_mode": "AGENT",
                    "agent_id": agent_id,
                    "os_watcher": str(raw.get("os_watcher") or default_watcher),
                    "latest_version": 0,
                    "latest_actor": agent_id,
                    "latest_changed_at": now,
                    "notes": "[agent-ingest] LIVE watch created from file-event",
                    "created_at": now,
                    "updated_at": now,
                },
                tenant_id=tid,
            )
            _file_targets().insert_one(target)
        else:
            # L6: existing watches must be AGENT mode to accept agent events.
            mode = str(target.get("watch_mode") or "SIMULATED").upper()
            if mode != "AGENT":
                errors.append(
                    f"event[{idx}]: watch '{watch_id or target.get('watch_id')}' "
                    f"has watch_mode={mode}; set watch_mode=AGENT to accept "
                    "agent file-events"
                )
                continue
            bound_agent = str(target.get("agent_id") or "").strip()
            if bound_agent and bound_agent != agent_id:
                errors.append(
                    f"event[{idx}]: watch bound to agent '{bound_agent}'"
                )
                continue

        path = path or str(target.get("path") or "")
        change_kind = str(raw.get("change_kind") or "modified").strip().lower()
        if change_kind not in CHANGE_KINDS:
            errors.append(f"event[{idx}]: invalid change_kind '{change_kind}'")
            continue
        try:
            version = int(raw.get("version") or 0)
        except (TypeError, ValueError):
            errors.append(f"event[{idx}]: version must be an integer")
            continue
        if version < 1:
            # Auto-increment from target latest when omitted/invalid.
            version = int(target.get("latest_version") or 0) + 1
        try:
            changed_at = _parse_observed(
                raw.get("changed_at") or raw.get("observed_at"),
                default=now,
                label=f"event[{idx}]",
            )
        except AgentIngestError as exc:
            errors.append(exc.message)
            continue
        actor = str(raw.get("actor") or agent_id).strip() or agent_id
        actor_type = str(raw.get("actor_type") or "service").strip().lower()
        if actor_type not in {"user", "service", "system"}:
            actor_type = "service"
        summary = str(raw.get("summary") or f"{change_kind} {path}").strip()[:512]
        os_watcher = str(
            raw.get("os_watcher") or target.get("os_watcher") or default_watcher
        ).strip().lower()
        if os_watcher not in VALID_OS_WATCHERS:
            errors.append(
                f"event[{idx}]: invalid os_watcher '{os_watcher}' "
                f"(expected one of {sorted(VALID_OS_WATCHERS)})"
            )
            continue
        content_hash = raw.get("content_hash")
        size_bytes = raw.get("size_bytes")
        try:
            size_val = int(size_bytes) if size_bytes is not None else None
        except (TypeError, ValueError):
            errors.append(f"event[{idx}]: size_bytes must be an integer")
            continue

        prepared.append(
            stamp_tenant_id(
                {
                    "event_id": _new_file_event_id(),
                    "watch_id": watch_id,
                    "path": path,
                    "version": version,
                    "change_kind": change_kind,
                    "actor": actor,
                    "actor_type": actor_type,
                    "changed_at": changed_at,
                    "summary": summary,
                    "content_hash": (
                        str(content_hash).strip() if content_hash else None
                    ),
                    "size_bytes": size_val,
                    "execution_mode": "LIVE",
                    "data_source": "AGENT_FILE_WATCH",
                    "note": "LIVE agent file-event ingest",
                    "agent_id": agent_id,
                    "os_family": family,
                    "os_watcher": os_watcher,
                    "created_at": now,
                },
                tenant_id=tid,
            )
        )
        prev = watch_updates.get(watch_id)
        if prev is None or version >= int(prev.get("latest_version") or 0):
            watch_updates[watch_id] = {
                "latest_version": version,
                "latest_actor": actor,
                "latest_changed_at": changed_at,
                "execution_mode": "LIVE",
                "watch_mode": "AGENT",
                "agent_id": agent_id,
                "os_watcher": os_watcher,
                "updated_at": now,
            }

    rejected = len(errors)
    if prepared:
        _file_events().insert_many(prepared)
        for wid, updates in watch_updates.items():
            _file_targets().update_one(
                merge_tenant_filter({"watch_id": wid}, tid),
                {"$set": updates},
            )
        try:
            agents_service.heartbeat_agent(
                agent_id=agent_id, tenant_id=tid, settings=cfg
            )
        except Exception:  # noqa: BLE001
            pass

    last_seq = None
    if seq is not None and prepared:
        advanced = advance_cursor(
            tenant_id=tid,
            agent_id=agent_id,
            channel="file_events",
            seq=int(seq),
        )
        last_seq = advanced.get("last_seq")
    elif seq is not None:
        last_seq = get_cursor(
            tenant_id=tid, agent_id=agent_id, channel="file_events"
        ).get("last_seq")

    return {
        "ok": bool(prepared) or rejected == 0,
        "execution_mode": "LIVE",
        "data_source": "AGENT_FILE_WATCH",
        "accepted": len(prepared),
        "rejected": rejected,
        "deduped": False,
        "errors": errors,
        "tenant_id": tid,
        "agent_id": agent_id,
        "os_family": family,
        "os_watcher": default_watcher,
        "seq": seq,
        "last_seq": last_seq,
        "live_probes": True,
    }


def ingest_agent_logs(
    *,
    tenant_id: str,
    agent: dict[str, Any],
    events: list[dict[str, Any]],
    default_stream_id: str | None = None,
    os_family: str | None = None,
    seq: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Agent-authenticated log ingest → LIVE log_events (data_source=AGENT)."""
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    assert_agent_ingest_allowed(tenant_id=tid, settings=cfg)
    assert_agent_entitlement(tenant_id=tid)
    agent_id = str(agent.get("agent_id") or "")
    if not agent_id:
        raise AgentIngestError("agent_id required", status_code=401)
    family = validate_os_family(agent=agent, payload_os_family=os_family)

    dup = _check_seq_dedup(
        tenant_id=tid, agent_id=agent_id, channel="logs", seq=seq
    )
    if dup:
        return dup

    # Stamp agent attrs onto events.
    stamped: list[dict[str, Any]] = []
    for raw in events or []:
        if not isinstance(raw, dict):
            continue
        attrs = dict(raw.get("attrs") or {}) if isinstance(raw.get("attrs"), dict) else {}
        attrs.setdefault("agent_id", agent_id)
        attrs.setdefault("os_family", family)
        item = {
            **raw,
            "attrs": attrs,
            "collect_mode": "AGENT",
        }
        stamped.append(item)

    try:
        result = ingest_service.ingest_log_events(
            tenant_id=tid,
            events=stamped,
            default_stream_id=default_stream_id,
            data_source="AGENT",
            source_tag="agent",
            settings=cfg,
            capability="agent_ingest",
        )
    except ingest_service.MonitorIngestError as exc:
        raise AgentIngestError(exc.message, status_code=exc.status_code) from exc

    if seq is not None and int(result.get("accepted") or 0) > 0:
        advanced = advance_cursor(
            tenant_id=tid, agent_id=agent_id, channel="logs", seq=int(seq)
        )
        result["last_seq"] = advanced.get("last_seq")
    elif seq is not None:
        result["last_seq"] = get_cursor(
            tenant_id=tid, agent_id=agent_id, channel="logs"
        ).get("last_seq")

    result["agent_id"] = agent_id
    result["os_family"] = family
    result["deduped"] = False
    result["seq"] = seq
    try:
        agents_service.heartbeat_agent(
            agent_id=agent_id, tenant_id=tid, settings=cfg
        )
    except Exception:  # noqa: BLE001
        pass
    return result
