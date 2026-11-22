"""Optional syslog UDP receiver — binds only when MONITOR_LIVE_SYSLOG_BIND is set.

Fail-closed: empty bind → do not listen. Platform master must be on to start.
Per-datagram tenant gates are enforced inside ``ingest.ingest_syslog_message``.
Unknown sources are dropped (or quarantined when mapped with status=quarantine).
"""

from __future__ import annotations

import logging
import re
import socket
import threading
from typing import Any

from ...config import Settings, get_settings
from . import ingest as ingest_service

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None
_sock: socket.socket | None = None
_stats: dict[str, Any] = {
    "bound": False,
    "bind": "",
    "received": 0,
    "accepted": 0,
    "dropped": 0,
}

# Lightweight RFC5424 / BSD syslog severity extraction (PRI).
_PRI_RE = re.compile(r"^<(\d{1,3})>")


def is_running() -> bool:
    t = _thread
    return bool(t and t.is_alive())


def stats() -> dict[str, Any]:
    return dict(_stats)


def parse_bind(bind: str) -> tuple[str, int] | None:
    text = (bind or "").strip()
    if not text:
        return None
    # host:port — IPv6 in [addr]:port not required for v1 lab bind.
    if text.count(":") != 1:
        return None
    host, port_s = text.rsplit(":", 1)
    host = host.strip() or "0.0.0.0"
    try:
        port = int(port_s)
    except ValueError:
        return None
    if not (1 <= port <= 65535):
        return None
    return host, port


def severity_from_syslog(raw: bytes | str) -> tuple[str, str]:
    """Return ``(severity, message_text)`` from a syslog datagram."""
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text = raw.decode("latin-1", errors="replace")
    else:
        text = str(raw)
    text = text.strip()
    severity = "info"
    match = _PRI_RE.match(text)
    if match:
        try:
            pri = int(match.group(1))
            sev_num = pri % 8
            # syslog severity 0=emerg .. 7=debug
            mapping = {
                0: "critical",
                1: "critical",
                2: "critical",
                3: "error",
                4: "warning",
                5: "info",
                6: "info",
                7: "debug",
            }
            severity = mapping.get(sev_num, "info")
        except ValueError:
            pass
        text = text[match.end() :].lstrip()
    return severity, text


def handle_datagram(
    data: bytes,
    addr: tuple[str, int] | str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Process one datagram (used by the receiver loop and unit tests)."""
    global _stats
    cfg = settings or get_settings()
    source_ip = addr[0] if isinstance(addr, tuple) else str(addr)
    severity, message = severity_from_syslog(data)
    _stats["received"] = int(_stats.get("received") or 0) + 1
    result = ingest_service.ingest_syslog_message(
        source_ip=source_ip,
        message=message,
        severity=severity,
        settings=cfg,
    )
    if result.get("ok") and int(result.get("accepted") or 0) > 0:
        _stats["accepted"] = int(_stats.get("accepted") or 0) + 1
    else:
        _stats["dropped"] = int(_stats.get("dropped") or 0) + 1
    return result


def _loop(settings: Settings, stop: threading.Event, sock: socket.socket) -> None:
    logger.info(
        "monitor syslog receiver listening bind=%s",
        settings.monitor_live_syslog_bind,
    )
    sock.settimeout(1.0)
    while not stop.is_set():
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            if stop.is_set():
                break
            logger.exception("syslog recv failed")
            continue
        try:
            handle_datagram(data, addr, settings=settings)
        except Exception:  # noqa: BLE001 — never kill the loop
            logger.exception("syslog handle failed")
    logger.info("monitor syslog receiver stopped")


def start_receiver(settings: Settings | None = None) -> bool:
    """Bind UDP syslog when configured + platform live on. Returns True if running."""
    global _stop_event, _thread, _sock, _stats
    cfg = settings or get_settings()
    parsed = parse_bind(cfg.monitor_live_syslog_bind or "")
    if not parsed:
        logger.info(
            "monitor syslog receiver disabled (MONITOR_LIVE_SYSLOG_BIND empty)"
        )
        return False
    if not bool(cfg.monitor_live_probes_enabled):
        logger.info(
            "monitor syslog receiver not started "
            "(MONITOR_LIVE_PROBES_ENABLED=false; bind configured but fail-closed)"
        )
        return False

    host, port = parsed
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        except OSError:
            sock.close()
            logger.exception(
                "monitor syslog bind failed host=%s port=%s", host, port
            )
            return False
        stop = threading.Event()
        thread = threading.Thread(
            target=_loop,
            args=(cfg, stop, sock),
            name="monitor-syslog",
            daemon=True,
        )
        _stop_event = stop
        _thread = thread
        _sock = sock
        _stats = {
            "bound": True,
            "bind": f"{host}:{port}",
            "received": 0,
            "accepted": 0,
            "dropped": 0,
        }
        thread.start()
        return True


def stop_receiver(*, join_timeout: float = 2.0) -> None:
    global _stop_event, _thread, _sock, _stats
    with _lock:
        stop = _stop_event
        thread = _thread
        sock = _sock
        _stop_event = None
        _thread = None
        _sock = None
    if stop is not None:
        stop.set()
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
    if thread is not None and thread.is_alive():
        thread.join(timeout=join_timeout)
    _stats = {
        "bound": False,
        "bind": "",
        "received": int(_stats.get("received") or 0),
        "accepted": int(_stats.get("accepted") or 0),
        "dropped": int(_stats.get("dropped") or 0),
    }
