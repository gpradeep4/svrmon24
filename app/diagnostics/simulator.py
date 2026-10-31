"""Synthetic diagnostic value generator.

Never connects to servers, never runs shell/SQL, never scans networks.
All values are deterministic-ish demo numbers labeled SYNTHETIC_DEMO.
"""

from __future__ import annotations

import hashlib
from typing import Any


SYNTHETIC_NOTE = "Synthetic demo value — not real telemetry."
DATA_SOURCE = "SYNTHETIC_DEMO"


def _seed_int(component_id: str, check_id: str, modulo: int) -> int:
    digest = hashlib.sha256(f"{component_id}:{check_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def generate_check_result(component_id: str, check: dict[str, Any]) -> dict[str, Any]:
    """Generate one clearly labeled synthetic check result."""
    check_id = str(check["check_id"])
    kind = str(check.get("metric_kind") or check_id)

    if kind in {"cpu", "memory", "disk"}:
        # Keep demo values in a plausible but obviously rounded band
        value = 15 + _seed_int(component_id, check_id, 60)  # 15–74
        status = "ok" if value < 85 else "warning"
        rendered = value
    elif kind == "service_status":
        # Demo always reports a synthetic healthy service for approved basic-health
        rendered = "SYNTHETIC_RUNNING"
        status = "ok"
    elif kind == "connectivity":
        rendered = "SYNTHETIC_REACHABLE"
        status = "ok"
    else:
        rendered = "SYNTHETIC_N/A"
        status = "unknown"

    return {
        "check_id": check_id,
        "label": check.get("label") or check_id,
        "metric_kind": kind,
        "unit": check.get("unit") or "",
        "value": rendered,
        "status": status,
        "synthetic": True,
        "data_source": DATA_SOURCE,
        "note": SYNTHETIC_NOTE,
    }


def run_simulated_profile(
    *,
    component_id: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute an approved profile in SIMULATED mode only."""
    results: list[dict[str, Any]] = []
    for check in profile.get("checks") or []:
        results.append(generate_check_result(component_id, check))
    return results
