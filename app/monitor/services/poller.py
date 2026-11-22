"""In-process agentless monitor poller (feature-flagged).

When ``MONITOR_POLLER_ENABLED=true``, a daemon thread ticks due HTTP/TCP/ICMP/SNMP
checks for tenants with live agentless gates on. Disabled by default — safe no-op.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from ...config import Settings, get_settings
from ...services import tenants as tenants_service
from . import checks as checks_service
from .live_gates import live_allowed

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None
_last_tick: dict[str, Any] | None = None


def is_running() -> bool:
    t = _thread
    return bool(t and t.is_alive())


def last_tick() -> dict[str, Any] | None:
    return _last_tick


def run_tick(
    *,
    settings: Settings | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run one poller tick across tenants.

    When the platform poller flag is off and ``force`` is False, returns a
    skipped summary (no-op). Manual admin ticks may pass ``force=True`` but
    still respect per-tenant agentless gates inside ``run_due_checks_for_tenant``.
    """
    global _last_tick
    cfg = settings or get_settings()
    if not force and not bool(cfg.monitor_poller_enabled):
        result = {
            "ok": True,
            "skipped": True,
            "reason": "MONITOR_POLLER_ENABLED=false",
            "tenants": 0,
            "ran": 0,
            "results": [],
        }
        _last_tick = result
        return result

    if not bool(cfg.monitor_live_probes_enabled):
        result = {
            "ok": True,
            "skipped": True,
            "reason": "MONITOR_LIVE_PROBES_ENABLED=false",
            "tenants": 0,
            "ran": 0,
            "results": [],
        }
        _last_tick = result
        return result

    tenant_results: list[dict[str, Any]] = []
    ran = 0
    tenants = tenants_service.list_tenants()
    for tenant in tenants:
        tid = str(tenant.get("tenant_id") or "").strip()
        if not tid:
            continue
        if not live_allowed(
            tenant_id=tid, capability="agentless_poll", settings=cfg
        ):
            tenant_results.append(
                {
                    "tenant_id": tid,
                    "skipped": True,
                    "reason": "agentless_poll_gate_off",
                    "ran": 0,
                }
            )
            continue
        outcome = checks_service.run_due_checks_for_tenant(
            tenant_id=tid, settings=cfg
        )
        ran += int(outcome.get("ran") or 0)
        tenant_results.append(outcome)

    result = {
        "ok": True,
        "skipped": False,
        "tenants": len(tenant_results),
        "ran": ran,
        "results": tenant_results,
    }
    _last_tick = result
    return result


def _loop(settings: Settings, stop: threading.Event) -> None:
    interval = max(5, int(settings.monitor_poller_interval_seconds))
    logger.info("monitor poller started interval_seconds=%s", interval)
    if stop.wait(min(5, interval)):
        logger.info("monitor poller stopped before first tick")
        return
    while not stop.is_set():
        try:
            result = run_tick(settings=settings, force=False)
            logger.info(
                "monitor poller tick ok skipped=%s ran=%s tenants=%s",
                result.get("skipped"),
                result.get("ran"),
                result.get("tenants"),
            )
        except Exception:  # noqa: BLE001 — never kill the loop
            logger.exception("monitor poller tick failed")
        if stop.wait(interval):
            break
    logger.info("monitor poller stopped")


def start_poller(settings: Settings | None = None) -> bool:
    """Start the background poller if enabled. Returns True when started/running."""
    global _stop_event, _thread
    cfg = settings or get_settings()
    if not cfg.monitor_poller_enabled:
        logger.info("monitor poller disabled (MONITOR_POLLER_ENABLED=false)")
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        stop = threading.Event()
        thread = threading.Thread(
            target=_loop,
            args=(cfg, stop),
            name="monitor-poller",
            daemon=True,
        )
        _stop_event = stop
        _thread = thread
        thread.start()
        return True


def stop_poller(*, join_timeout: float = 2.0) -> None:
    global _stop_event, _thread
    with _lock:
        stop = _stop_event
        thread = _thread
        _stop_event = None
        _thread = None
    if stop is not None:
        stop.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=join_timeout)
