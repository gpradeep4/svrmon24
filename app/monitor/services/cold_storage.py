"""Optional cold-storage hooks for Monitoring log archives (L9).

``MONITOR_COLD_STORAGE_URI`` empty → no-op (hot Mongo only).
``file://`` adapter writes JSONL + manifest under a local path.
``s3://`` is recognized but optional / not required in v1.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from ...config import Settings, get_settings
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id, tenant_filter
from .indexes import ensure_monitor_indexes

JOBS_COLLECTION = "monitor_retention_jobs"


class ColdStorageError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jobs():
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[JOBS_COLLECTION]


def _new_job_id() -> str:
    return f"mrj-{uuid.uuid4().hex[:12]}"


def parse_cold_uri(uri: str) -> dict[str, Any]:
    """Parse ``MONITOR_COLD_STORAGE_URI`` into scheme + path details."""
    raw = (uri or "").strip()
    if not raw:
        return {"scheme": None, "configured": False, "path": None, "uri": ""}
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower() or None
    if scheme == "file":
        # file:///tmp/cold → /tmp/cold ; file://localhost/tmp/cold → /tmp/cold
        path = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc not in {"localhost", "127.0.0.1", ""}:
            # UNC-style file://host/share — keep host in path for transparency.
            path = f"//{parsed.netloc}{path}"
        if not path:
            raise ColdStorageError(
                "Invalid file:// cold storage URI (empty path)", status_code=400
            )
        return {
            "scheme": "file",
            "configured": True,
            "path": path,
            "uri": raw,
        }
    if scheme == "s3":
        return {
            "scheme": "s3",
            "configured": True,
            "path": None,
            "bucket": parsed.netloc or None,
            "key_prefix": (parsed.path or "").lstrip("/"),
            "uri": raw,
        }
    raise ColdStorageError(
        f"Unsupported cold storage URI scheme '{scheme}' "
        f"(supported: file://, optional s3://)",
        status_code=400,
    )


def cold_storage_status(*, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    try:
        parsed = parse_cold_uri(cfg.monitor_cold_storage_uri or "")
    except ColdStorageError as exc:
        return {
            "configured": False,
            "scheme": None,
            "uri": (cfg.monitor_cold_storage_uri or "").strip() or None,
            "error": exc.message,
        }
    return {
        "configured": bool(parsed.get("configured")),
        "scheme": parsed.get("scheme"),
        "uri": parsed.get("uri") or None,
        "path": parsed.get("path"),
        "bucket": parsed.get("bucket"),
        "key_prefix": parsed.get("key_prefix"),
    }


def _write_file_archive(
    *,
    base_path: str,
    tenant_id: str,
    job_id: str,
    tier: str,
    events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    root = Path(base_path).expanduser().resolve()
    dest = root / tenant_id / job_id
    dest.mkdir(parents=True, exist_ok=True)
    events_path = dest / "events.jsonl"
    manifest_path = dest / "manifest.json"
    count = 0
    first_id: str | None = None
    last_id: str | None = None
    with events_path.open("w", encoding="utf-8") as handle:
        for doc in events:
            row = serialize_document(doc) if isinstance(doc, dict) else doc
            if not isinstance(row, dict):
                continue
            handle.write(json.dumps(row, default=str, separators=(",", ":")))
            handle.write("\n")
            count += 1
            eid = str(row.get("event_id") or "")
            if first_id is None and eid:
                first_id = eid
            if eid:
                last_id = eid
    manifest = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "tier": tier,
        "adapter": "file",
        "events_path": str(events_path),
        "event_count": count,
        "first_event_id": first_id,
        "last_event_id": last_id,
        "created_at": _now().isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return {
        "adapter": "file",
        "archive_dir": str(dest),
        "events_path": str(events_path),
        "manifest_path": str(manifest_path),
        "event_count": count,
        "manifest": manifest,
    }


def archive_log_events(
    *,
    tenant_id: str,
    events: list[dict[str, Any]],
    tier: str = "siem",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Export events to cold storage. No-op when URI empty; file:// writes manifest."""
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    uri = (cfg.monitor_cold_storage_uri or "").strip()
    job_id = _new_job_id()
    now = _now()

    if not uri:
        job = stamp_tenant_id(
            {
                "job_id": job_id,
                "tier": tier,
                "status": "noop",
                "cold_uri": None,
                "stats": {
                    "event_count": 0,
                    "reason": "cold storage not configured",
                },
                "created_at": now,
                "updated_at": now,
            },
            tenant_id=tid,
        )
        _jobs().insert_one(job)
        return {
            "ok": True,
            "archived": False,
            "reason": "cold storage not configured",
            "job_id": job_id,
            "tenant_id": tid,
            "event_count": 0,
            "cold_uri": None,
            "status": "noop",
        }

    parsed = parse_cold_uri(uri)
    if parsed["scheme"] == "s3":
        job = stamp_tenant_id(
            {
                "job_id": job_id,
                "tier": tier,
                "status": "unsupported",
                "cold_uri": uri,
                "stats": {
                    "event_count": 0,
                    "reason": (
                        "s3:// adapter is optional in L9; configure file:// "
                        "for local/filesystem cold archives"
                    ),
                },
                "created_at": now,
                "updated_at": now,
            },
            tenant_id=tid,
        )
        _jobs().insert_one(job)
        return {
            "ok": True,
            "archived": False,
            "reason": (
                "s3:// adapter is optional in L9; configure file:// "
                "for local/filesystem cold archives"
            ),
            "job_id": job_id,
            "tenant_id": tid,
            "event_count": 0,
            "cold_uri": uri,
            "status": "unsupported",
            "scheme": "s3",
        }

    if parsed["scheme"] != "file":
        raise ColdStorageError(
            f"Unsupported cold storage scheme '{parsed.get('scheme')}'",
            status_code=400,
        )

    written = _write_file_archive(
        base_path=str(parsed["path"]),
        tenant_id=tid,
        job_id=job_id,
        tier=tier,
        events=events,
    )
    job = stamp_tenant_id(
        {
            "job_id": job_id,
            "tier": tier,
            "status": "completed",
            "cold_uri": uri,
            "stats": {
                "event_count": written["event_count"],
                "archive_dir": written["archive_dir"],
                "events_path": written["events_path"],
                "manifest_path": written["manifest_path"],
            },
            "created_at": now,
            "updated_at": now,
        },
        tenant_id=tid,
    )
    _jobs().insert_one(job)
    return {
        "ok": True,
        "archived": True,
        "reason": None,
        "job_id": job_id,
        "tenant_id": tid,
        "event_count": written["event_count"],
        "cold_uri": uri,
        "status": "completed",
        "scheme": "file",
        **{k: written[k] for k in ("archive_dir", "events_path", "manifest_path")},
        "manifest": written["manifest"],
    }


def list_retention_jobs(*, tenant_id: str, limit: int = 20) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    lim = min(max(1, int(limit or 20)), 100)
    rows = list(
        _jobs()
        .find(tenant_filter(tid))
        .sort([("created_at", -1)])
        .limit(lim)
    )
    return {
        "tenant_id": tid,
        "items": [serialize_document(row) for row in rows],
        "total": len(rows),
    }
