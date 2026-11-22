#!/usr/bin/env python3
"""Reference / lab fixture client for Monitoring L5 agent ingest.

Pushes one metrics + logs + file-events batch for a given OS family using an
already-registered agent token. Not a production daemon.

Example:
  python agents/fixture_client.py \\
    --base-url http://127.0.0.1:8200 \\
    --agent-id agt-… --token mat_… --os-family linux --stream-id ls-…
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

OS_WATCHERS = {
    "linux": "inotify",
    "windows": "readdirectorychanges",
    "macos": "fsevents",
    "unix": "kqueue_or_poll",
}

CORE_METRICS = (
    ("cpu.usage_pct", 17.5, "%"),
    ("mem.used_pct", 62.0, "%"),
    ("disk.used_pct", 41.0, "%"),
)


def _post(base: str, path: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {path}: {detail}") from exc


def _get(base: str, path: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {path}: {detail}") from exc


def build_payloads(
    *,
    os_family: str,
    stream_id: str | None,
    seq: int,
) -> dict[str, dict[str, Any]]:
    watcher = OS_WATCHERS[os_family]
    metrics = {
        "os_family": os_family,
        "seq": seq,
        "samples": [
            {
                "metric_name": name,
                "value": value,
                "unit": unit,
                "attrs": {"fixture": True, "os_family": os_family},
            }
            for name, value, unit in CORE_METRICS
        ],
    }
    logs: dict[str, Any] = {
        "os_family": os_family,
        "seq": seq,
        "events": [
            {
                "severity": "info",
                "message": f"fixture agent heartbeat os_family={os_family}",
                "attrs": {"fixture": True},
            }
        ],
    }
    if stream_id:
        logs["stream_id"] = stream_id
    files = {
        "os_family": os_family,
        "seq": seq,
        "events": [
            {
                "path": f"/tmp/svrmon24-fixture-{os_family}.conf",
                "change_kind": "modified",
                "summary": f"fixture change ({watcher})",
                "os_watcher": watcher,
                "version": 1,
            }
        ],
    }
    return {"metrics": metrics, "logs": logs, "file_events": files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8200")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument(
        "--os-family",
        choices=sorted(OS_WATCHERS),
        default="linux",
    )
    parser.add_argument("--stream-id", default=None)
    parser.add_argument("--seq", type=int, default=1)
    args = parser.parse_args(argv)

    desired = _get(
        args.base_url,
        f"/api/monitor/agents/{args.agent_id}/desired-state",
        args.token,
    )
    stream_id = args.stream_id or (desired.get("stream_ids") or [None])[0]
    payloads = build_payloads(
        os_family=args.os_family, stream_id=stream_id, seq=args.seq
    )

    results = {
        "desired_state": {
            "watch_ids": desired.get("watch_ids"),
            "stream_ids": desired.get("stream_ids"),
            "os_watcher": desired.get("os_watcher"),
        },
        "metrics": _post(
            args.base_url, "/api/monitor/ingest/metrics", args.token, payloads["metrics"]
        ),
        "logs": _post(
            args.base_url, "/api/monitor/ingest/logs", args.token, payloads["logs"]
        ),
        "file_events": _post(
            args.base_url,
            "/api/monitor/ingest/file-events",
            args.token,
            payloads["file_events"],
        ),
    }
    json.dump(results, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
