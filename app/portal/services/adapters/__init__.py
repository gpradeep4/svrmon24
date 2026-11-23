"""Service Portal LIVE execution adapters (SP10 / SM-166).

Allowlisted ``action_key`` handlers for AGENT and AGENTLESS collect modes.
Cloud VM provision uses Terraform (OD-15). Fail-closed behind live gates;
SIMULATED path does not import this package for mutate.
"""

from __future__ import annotations

from .registry import AdapterError, AdapterResult, execute_live

__all__ = ["AdapterError", "AdapterResult", "execute_live"]
