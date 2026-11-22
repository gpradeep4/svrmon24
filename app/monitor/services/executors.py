"""HTTP + TCP check executors (L1). ICMP/SNMP land in L2."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from typing import Any

from .egress import EgressDenied, assert_egress_allowed, host_from_endpoint


def _ms_since(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def execute_http_check(
    *,
    endpoint: dict[str, Any],
    timeout_seconds: float,
    platform_allowlist: str,
    check_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """Perform an HTTP(S) GET/HEAD against an allowlisted host."""
    url = (endpoint.get("url") or "").strip()
    host = (endpoint.get("host") or "").strip() or None
    method = (endpoint.get("method") or "GET").strip().upper() or "GET"
    if method not in {"GET", "HEAD"}:
        method = "GET"
    expect_status = endpoint.get("expect_status")
    if expect_status is None:
        expect_status = 200
    try:
        expect_status = int(expect_status)
    except (TypeError, ValueError):
        expect_status = 200

    if not url:
        if not host:
            return {
                "ok": False,
                "latency_ms": None,
                "value": None,
                "message": "http endpoint requires url or host",
                "denied": False,
            }
        port = endpoint.get("port") or 80
        path = endpoint.get("path") or "/"
        if not str(path).startswith("/"):
            path = f"/{path}"
        scheme = "https" if int(port) == 443 else "http"
        url = f"{scheme}://{host}:{int(port)}{path}"

    try:
        hostname = host_from_endpoint(url=url, host=host)
        assert_egress_allowed(
            hostname=hostname,
            platform_allowlist=platform_allowlist,
            check_allowlist=check_allowlist,
        )
    except EgressDenied as exc:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": exc.message,
            "denied": True,
        }

    start = time.perf_counter()
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=max(0.1, float(timeout_seconds))) as resp:
            status = int(getattr(resp, "status", 0) or resp.getcode())
            # Drain a small body so connections close cleanly.
            try:
                resp.read(1024)
            except Exception:  # noqa: BLE001
                pass
        latency = _ms_since(start)
        ok = status == expect_status
        return {
            "ok": ok,
            "latency_ms": latency,
            "value": float(status),
            "message": f"HTTP {status}" + ("" if ok else f" (expected {expect_status})"),
            "denied": False,
        }
    except urllib.error.HTTPError as exc:
        latency = _ms_since(start)
        status = int(exc.code)
        ok = status == expect_status
        return {
            "ok": ok,
            "latency_ms": latency,
            "value": float(status),
            "message": f"HTTP {status}" + ("" if ok else f" (expected {expect_status})"),
            "denied": False,
        }
    except Exception as exc:  # noqa: BLE001 — record as check failure
        return {
            "ok": False,
            "latency_ms": _ms_since(start),
            "value": None,
            "message": f"http error: {exc}",
            "denied": False,
        }


def execute_tcp_check(
    *,
    endpoint: dict[str, Any],
    timeout_seconds: float,
    platform_allowlist: str,
    check_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """TCP connect (+ optional short banner read) against an allowlisted host."""
    host = (endpoint.get("host") or "").strip()
    url = (endpoint.get("url") or "").strip() or None
    port = endpoint.get("port")
    if not host and url:
        try:
            host = host_from_endpoint(url=url)
        except EgressDenied as exc:
            return {
                "ok": False,
                "latency_ms": None,
                "value": None,
                "message": exc.message,
                "denied": True,
            }
        if port is None:
            from urllib.parse import urlparse

            parsed = urlparse(url if "://" in url else f"tcp://{url}")
            port = parsed.port
    if not host:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": "tcp endpoint requires host",
            "denied": False,
        }
    try:
        port_i = int(port) if port is not None else 0
    except (TypeError, ValueError):
        port_i = 0
    if port_i < 1 or port_i > 65535:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": "tcp endpoint requires a valid port (1-65535)",
            "denied": False,
        }

    try:
        assert_egress_allowed(
            hostname=host,
            platform_allowlist=platform_allowlist,
            check_allowlist=check_allowlist,
        )
    except EgressDenied as exc:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": exc.message,
            "denied": True,
        }

    start = time.perf_counter()
    try:
        with socket.create_connection(
            (host, port_i), timeout=max(0.1, float(timeout_seconds))
        ) as sock:
            sock.settimeout(min(1.0, max(0.1, float(timeout_seconds))))
            try:
                sock.recv(64)
            except (OSError, TimeoutError):
                pass
        latency = _ms_since(start)
        return {
            "ok": True,
            "latency_ms": latency,
            "value": latency,
            "message": f"tcp connect ok {host}:{port_i}",
            "denied": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "latency_ms": _ms_since(start),
            "value": None,
            "message": f"tcp error: {exc}",
            "denied": False,
        }


def execute_check(
    *,
    protocol: str,
    endpoint: dict[str, Any],
    timeout_seconds: float,
    platform_allowlist: str,
    check_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """Dispatch to HTTP or TCP executor; other protocols return structured error."""
    proto = (protocol or "").strip().lower()
    if proto == "http":
        return execute_http_check(
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            platform_allowlist=platform_allowlist,
            check_allowlist=check_allowlist,
        )
    if proto == "tcp":
        return execute_tcp_check(
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            platform_allowlist=platform_allowlist,
            check_allowlist=check_allowlist,
        )
    return {
        "ok": False,
        "latency_ms": None,
        "value": None,
        "message": f"protocol '{proto}' not implemented in L1 (http/tcp only)",
        "denied": False,
    }
