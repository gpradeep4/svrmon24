"""Diagnostic profile registry.

Only approved profiles may be run. Initial release is DEMO/SIMULATED only —
profiles describe synthetic check templates, never real probe commands.
"""

from __future__ import annotations

from typing import Any

from ..models.components import COMPONENT_TYPES

# Hard rule for Phase 6: every profile executes as SIMULATED only.
EXECUTION_MODE = "SIMULATED"

BASIC_HEALTH_PROFILE: dict[str, Any] = {
    "profile_name": "basic-health",
    "display_name": "Basic Health (Demo)",
    "description": (
        "Approved demo profile that generates clearly labeled synthetic CPU, "
        "memory, disk, service status, and connectivity readings. "
        "Does not connect to servers or run commands."
    ),
    "execution_mode": EXECUTION_MODE,
    "approved": True,
    "allowed_component_types": list(COMPONENT_TYPES),
    "checks": [
        {
            "check_id": "cpu",
            "label": "CPU utilization",
            "metric_kind": "cpu",
            "unit": "percent",
            "synthetic": True,
        },
        {
            "check_id": "memory",
            "label": "Memory utilization",
            "metric_kind": "memory",
            "unit": "percent",
            "synthetic": True,
        },
        {
            "check_id": "disk",
            "label": "Disk utilization",
            "metric_kind": "disk",
            "unit": "percent",
            "synthetic": True,
        },
        {
            "check_id": "service_status",
            "label": "Service status",
            "metric_kind": "service_status",
            "unit": "status",
            "synthetic": True,
        },
        {
            "check_id": "connectivity",
            "label": "Connectivity",
            "metric_kind": "connectivity",
            "unit": "status",
            "synthetic": True,
        },
    ],
    "safety": {
        "allows_remote_execution": False,
        "allows_shell": False,
        "allows_sql": False,
        "allows_network_scan": False,
        "demo_only": True,
    },
}

_REGISTRY: dict[str, dict[str, Any]] = {
    BASIC_HEALTH_PROFILE["profile_name"]: BASIC_HEALTH_PROFILE,
}


def list_profiles() -> list[dict[str, Any]]:
    return [dict(profile) for profile in _REGISTRY.values()]


def get_profile(profile_name: str) -> dict[str, Any] | None:
    profile = _REGISTRY.get(profile_name)
    return dict(profile) if profile else None


def require_profile(profile_name: str) -> dict[str, Any]:
    profile = get_profile(profile_name)
    if profile is None:
        raise KeyError(profile_name)
    if not profile.get("approved"):
        raise PermissionError(f"Profile '{profile_name}' is not approved")
    return profile
