"""In-process ITSM job runner (feature-flagged).

When ``ITSM_JOB_RUNNER_ENABLED=true``, a daemon thread ticks SLA sweeper,
delivery retries, report schedules, and workflow schedule triggers on an interval.
Disabled by default — safe no-op for monolith and API-only deploys.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from ...config import Settings, get_settings
from . import jobs as jobs_service

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


def _loop(settings: Settings, stop: threading.Event) -> None:
    global _last_tick
    interval = max(5, int(settings.itsm_job_runner_interval_seconds))
    logger.info(
        "itsm job runner started interval_seconds=%s",
        interval,
    )
    # Initial delay so startup / tenancy bootstrap can finish.
    if stop.wait(min(5, interval)):
        logger.info("itsm job runner stopped before first tick")
        return
    while not stop.is_set():
        try:
            result = jobs_service.run_tick(settings=settings, force=False)
            _last_tick = result
            logger.info(
                "itsm job tick ok skipped=%s jobs=%s",
                result.get("skipped_jobs"),
                list((result.get("jobs") or {}).keys()),
            )
        except Exception:  # noqa: BLE001 — never kill the loop
            logger.exception("itsm job tick failed")
        if stop.wait(interval):
            break
    logger.info("itsm job runner stopped")


def start_job_runner(settings: Settings | None = None) -> bool:
    """Start the background runner if enabled. Returns True when started/already running."""
    global _stop_event, _thread
    cfg = settings or get_settings()
    if not cfg.itsm_job_runner_enabled:
        logger.info("itsm job runner disabled (ITSM_JOB_RUNNER_ENABLED=false)")
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        stop = threading.Event()
        thread = threading.Thread(
            target=_loop,
            args=(cfg, stop),
            name="itsm-job-runner",
            daemon=True,
        )
        _stop_event = stop
        _thread = thread
        thread.start()
        return True


def stop_job_runner(*, join_timeout: float = 2.0) -> None:
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
