"""Agentless check executors — HTTP/TCP (L1) + ICMP/SNMP (L2)."""

from __future__ import annotations

import logging
import shutil
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from .egress import EgressDenied, assert_egress_allowed, host_from_endpoint
from .secrets import SecretRefError, resolve_secret_ref

logger = logging.getLogger(__name__)

# Well-known sysUpTime / ifNumber-style defaults for network demos.
DEFAULT_SNMP_OID = "1.3.6.1.2.1.1.3.0"  # SNMPv2-MIB::sysUpTime.0
DEFAULT_SNMP_PORT = 161


def _ms_since(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def execute_http_check(
    *,
    endpoint: dict[str, Any],
    timeout_seconds: float,
    platform_allowlist: str,
    check_allowlist: list[str] | None = None,
    secret_ref: str | None = None,
) -> dict[str, Any]:
    """Perform an HTTP(S) GET/HEAD against an allowlisted host."""
    del secret_ref  # unused for HTTP
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
    secret_ref: str | None = None,
) -> dict[str, Any]:
    """TCP connect (+ optional short banner read) against an allowlisted host."""
    del secret_ref
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


def _ping_via_subprocess(host: str, timeout_seconds: float) -> dict[str, Any]:
    """ICMP echo via system ``ping`` (no raw socket required of the process)."""
    ping_bin = shutil.which("ping")
    if not ping_bin:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": (
                "icmp unavailable: ping binary not found "
                "(raw socket / setcap also unavailable)"
            ),
            "denied": False,
            "skipped": True,
        }

    # Linux: -c 1 -W deadline(sec). macOS uses -t; we target Linux deploy.
    timeout_i = max(1, int(round(float(timeout_seconds))))
    cmd = [ping_bin, "-c", "1", "-W", str(timeout_i), host]
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_i + 2,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": "icmp unavailable: ping binary not found",
            "denied": False,
            "skipped": True,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "latency_ms": _ms_since(start),
            "value": None,
            "message": f"icmp timeout after {timeout_i}s",
            "denied": False,
            "skipped": False,
        }
    except PermissionError:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": (
                "icmp unavailable: permission denied for ping "
                "(needs CAP_NET_RAW / setuid ping)"
            ),
            "denied": False,
            "skipped": True,
        }
    except OSError as exc:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": f"icmp unavailable: {exc}",
            "denied": False,
            "skipped": True,
        }

    latency = _ms_since(start)
    if proc.returncode == 0:
        # Best-effort parse "time=1.23 ms" from stdout.
        rtt = latency
        for token in (proc.stdout or "").replace(",", " ").split():
            if token.startswith("time="):
                try:
                    rtt = float(token.split("=", 1)[1])
                except ValueError:
                    pass
                break
        return {
            "ok": True,
            "latency_ms": rtt,
            "value": rtt,
            "message": f"icmp echo ok {host}",
            "denied": False,
            "skipped": False,
        }

    stderr = (proc.stderr or "").strip() or (proc.stdout or "").strip()
    # Non-zero often means host unreachable — still a completed check, not skip.
    return {
        "ok": False,
        "latency_ms": latency,
        "value": None,
        "message": f"icmp failed (rc={proc.returncode})"
        + (f": {stderr[:200]}" if stderr else ""),
        "denied": False,
        "skipped": False,
    }


def _try_raw_icmp_socket() -> tuple[socket.socket | None, str | None]:
    """Attempt raw ICMP socket; return (sock, error_reason)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        return sock, None
    except PermissionError:
        return None, "raw ICMP socket requires CAP_NET_RAW / root"
    except OSError as exc:
        return None, f"raw ICMP socket unavailable: {exc}"


def execute_icmp_check(
    *,
    endpoint: dict[str, Any],
    timeout_seconds: float,
    platform_allowlist: str,
    check_allowlist: list[str] | None = None,
    secret_ref: str | None = None,
) -> dict[str, Any]:
    """ICMP echo RTT when OS permits; structured error (no crash) otherwise."""
    del secret_ref
    host = (endpoint.get("host") or "").strip()
    url = (endpoint.get("url") or "").strip() or None
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
                "skipped": False,
            }
    if not host:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": "icmp endpoint requires host",
            "denied": False,
            "skipped": False,
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
            "skipped": False,
        }

    # Prefer subprocess ping (works without process CAP_NET_RAW on many hosts).
    # Raw socket probe is only used to document capability; ping path is primary.
    _raw, raw_reason = _try_raw_icmp_socket()
    if _raw is not None:
        try:
            _raw.close()
        except OSError:
            pass

    result = _ping_via_subprocess(host, timeout_seconds)
    if result.get("skipped") and raw_reason:
        result["message"] = (
            f"{result['message']}; also {raw_reason}"
        )
    return result


def _encode_oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.strip(".").split(".") if p != ""]
    if len(parts) < 2:
        raise ValueError("OID too short")
    # First two arcs packed into one byte: 40*first + second
    body = bytes([40 * parts[0] + parts[1]])
    for arc in parts[2:]:
        if arc < 0:
            raise ValueError("negative OID arc")
        if arc < 128:
            body += bytes([arc])
        else:
            stack: list[int] = []
            while arc:
                stack.append(arc & 0x7F)
                arc >>= 7
            for i, b in enumerate(reversed(stack)):
                if i < len(stack) - 1:
                    body += bytes([b | 0x80])
                else:
                    body += bytes([b])
    return body


def _ber_len(n: int) -> bytes:
    if n < 128:
        return bytes([n])
    enc = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(enc)]) + enc


def _ber_tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _ber_len(len(value)) + value


def build_snmp_v2c_get_pdu(*, community: str, oid: str, request_id: int = 1) -> bytes:
    """Minimal SNMPv2c GetRequest BER packet (no external SNMP libs)."""
    oid_bytes = _encode_oid(oid)
    # VarBind: SEQUENCE { OID, NULL }
    varbind = _ber_tlv(
        0x30,
        _ber_tlv(0x06, oid_bytes) + _ber_tlv(0x05, b""),
    )
    varbind_list = _ber_tlv(0x30, varbind)
    # GetRequest-PDU = [0] IMPLICIT SEQUENCE
    pdu_body = (
        _ber_tlv(0x02, struct.pack(">I", request_id).lstrip(b"\x00") or b"\x00")
        + _ber_tlv(0x02, b"\x00")  # error-status
        + _ber_tlv(0x02, b"\x00")  # error-index
        + varbind_list
    )
    pdu = _ber_tlv(0xA0, pdu_body)
    version = _ber_tlv(0x02, b"\x01")  # version 1 => SNMPv2c
    community_tlv = _ber_tlv(0x04, community.encode("utf-8"))
    return _ber_tlv(0x30, version + community_tlv + pdu)


def _parse_snmp_gaugeish(response: bytes) -> float | None:
    """Best-effort extract first INTEGER / Counter / Gauge / TimeTicks value."""
    # Walk for tags: INTEGER(0x02), Counter32(0x41), Gauge32(0x42), TimeTicks(0x43)
    i = 0
    n = len(response)
    while i < n - 2:
        tag = response[i]
        length = response[i + 1]
        if length & 0x80:
            i += 1
            continue
        if tag in (0x02, 0x41, 0x42, 0x43) and i + 2 + length <= n and 0 < length <= 8:
            raw = response[i + 2 : i + 2 + length]
            try:
                return float(int.from_bytes(raw, "big"))
            except ValueError:
                pass
        i += 1
    return None


def snmp_get_oid(
    *,
    host: str,
    port: int,
    community: str,
    oid: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """UDP SNMPv2c GET. Separated for test doubles / mocks."""
    packet = build_snmp_v2c_get_pdu(community=community, oid=oid)
    start = time.perf_counter()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(max(0.1, float(timeout_seconds)))
        sock.sendto(packet, (host, port))
        data, _addr = sock.recvfrom(4096)
    except TimeoutError:
        return {
            "ok": False,
            "latency_ms": _ms_since(start),
            "value": None,
            "message": f"snmp timeout waiting for {host}:{port} oid={oid}",
        }
    except OSError as exc:
        return {
            "ok": False,
            "latency_ms": _ms_since(start),
            "value": None,
            "message": f"snmp error: {exc}",
        }
    finally:
        try:
            sock.close()
        except OSError:
            pass

    latency = _ms_since(start)
    value = _parse_snmp_gaugeish(data)
    if value is None:
        return {
            "ok": True,
            "latency_ms": latency,
            "value": float(len(data)),
            "message": f"snmp response {len(data)} bytes oid={oid} (unparsed)",
        }
    return {
        "ok": True,
        "latency_ms": latency,
        "value": value,
        "message": f"snmp oid {oid} = {value}",
    }


def execute_snmp_check(
    *,
    endpoint: dict[str, Any],
    timeout_seconds: float,
    platform_allowlist: str,
    check_allowlist: list[str] | None = None,
    secret_ref: str | None = None,
) -> dict[str, Any]:
    """SNMPv2c OID GET using community from ``secret_ref`` (env or insecure demo)."""
    host = (endpoint.get("host") or "").strip()
    url = (endpoint.get("url") or "").strip() or None
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
                "secret_insecure_demo": False,
            }
    if not host:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": "snmp endpoint requires host",
            "denied": False,
            "secret_insecure_demo": False,
        }

    oid = (endpoint.get("oid") or DEFAULT_SNMP_OID).strip()
    if not oid:
        oid = DEFAULT_SNMP_OID
    try:
        port = int(endpoint.get("port") or DEFAULT_SNMP_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_SNMP_PORT
    if port < 1 or port > 65535:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": "snmp endpoint requires a valid port",
            "denied": False,
            "secret_insecure_demo": False,
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
            "secret_insecure_demo": False,
        }

    try:
        resolved = resolve_secret_ref(secret_ref)
    except SecretRefError as exc:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": f"snmp secret_ref error: {exc.message}",
            "denied": False,
            "secret_insecure_demo": False,
        }

    if not resolved["configured"]:
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": (
                "snmp requires secret_ref (env:COMMUNITY_VAR or insecure:community "
                "for lab demos)"
            ),
            "denied": False,
            "secret_insecure_demo": bool(resolved["insecure_demo"]),
        }

    community = resolved["value"]
    insecure = bool(resolved["insecure_demo"])
    try:
        snmp_result = snmp_get_oid(
            host=host,
            port=port,
            community=community,
            oid=oid,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — never crash the poller
        logger.exception("snmp_get_oid unexpected host=%s oid=%s", host, oid)
        return {
            "ok": False,
            "latency_ms": None,
            "value": None,
            "message": f"snmp unexpected error: {exc}",
            "denied": False,
            "secret_insecure_demo": insecure,
        }

    return {
        "ok": bool(snmp_result.get("ok")),
        "latency_ms": snmp_result.get("latency_ms"),
        "value": snmp_result.get("value"),
        "message": snmp_result.get("message"),
        "denied": False,
        "secret_insecure_demo": insecure,
        "oid": oid,
    }


def execute_check(
    *,
    protocol: str,
    endpoint: dict[str, Any],
    timeout_seconds: float,
    platform_allowlist: str,
    check_allowlist: list[str] | None = None,
    secret_ref: str | None = None,
) -> dict[str, Any]:
    """Dispatch to HTTP/TCP/ICMP/SNMP executor."""
    proto = (protocol or "").strip().lower()
    common = dict(
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        platform_allowlist=platform_allowlist,
        check_allowlist=check_allowlist,
        secret_ref=secret_ref,
    )
    if proto == "http":
        return execute_http_check(**common)
    if proto == "tcp":
        return execute_tcp_check(**common)
    if proto == "icmp":
        return execute_icmp_check(**common)
    if proto == "snmp":
        return execute_snmp_check(**common)
    return {
        "ok": False,
        "latency_ms": None,
        "value": None,
        "message": f"protocol '{proto}' not implemented (http/tcp/icmp/snmp)",
        "denied": False,
    }
