"""Shared Monitoring literals — SIMULATED default; LIVE widenings for L*."""

from __future__ import annotations

from typing import Literal

ExecutionMode = Literal["SIMULATED", "LIVE"]
DataSource = Literal[
    "SYNTHETIC_DEMO",
    "HTTP_CHECK",
    "TCP_CHECK",
    "ICMP_CHECK",
    "SNMP",
    "SYSLOG",
    "HTTP_INGEST",
    "AGENT",
    "AGENT_FILE_WATCH",
    "AGENTLESS_FILE_POLL",
]
CollectMode = Literal["AGENTLESS", "AGENT"]
Domain = Literal["server", "network", "application", "database", "middleware"]
WatchMode = Literal["SIMULATED", "AGENT", "AGENTLESS_POLL"]
RetentionTier = Literal["hot", "extended", "siem"]

EXECUTION_MODES: tuple[str, ...] = ("SIMULATED", "LIVE")
DATA_SOURCES: tuple[str, ...] = (
    "SYNTHETIC_DEMO",
    "HTTP_CHECK",
    "TCP_CHECK",
    "ICMP_CHECK",
    "SNMP",
    "SYSLOG",
    "HTTP_INGEST",
    "AGENT",
    "AGENT_FILE_WATCH",
    "AGENTLESS_FILE_POLL",
)
COLLECT_MODES_UPPER: tuple[str, ...] = ("AGENTLESS", "AGENT")
DOMAINS: tuple[str, ...] = (
    "server",
    "network",
    "application",
    "database",
    "middleware",
)
WATCH_MODES: tuple[str, ...] = ("SIMULATED", "AGENT", "AGENTLESS_POLL")
