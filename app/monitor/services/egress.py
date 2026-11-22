"""Egress allowlist + SSRF guards for agentless polls (fail-closed)."""

from __future__ import annotations

import ipaddress
import socket
from typing import Iterable
from urllib.parse import urlparse


class EgressDenied(Exception):
    """Destination blocked by allowlist or SSRF policy."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def parse_allowlist(raw: str | Iterable[str] | None) -> list[str]:
    """Split comma-separated or list allowlist into trimmed non-empty tokens."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = list(raw)
    out: list[str] = []
    for part in parts:
        token = str(part).strip()
        if token:
            out.append(token)
    return out


def host_from_endpoint(*, url: str | None = None, host: str | None = None) -> str:
    """Extract hostname from URL or host field."""
    if host and str(host).strip():
        return str(host).strip().lower().rstrip(".")
    if url and str(url).strip():
        parsed = urlparse(str(url).strip())
        if parsed.hostname:
            return parsed.hostname.lower().rstrip(".")
        # bare host without scheme
        bare = str(url).strip().split("/")[0].split(":")[0]
        if bare:
            return bare.lower().rstrip(".")
    raise EgressDenied("endpoint has no host/url to dial")


def _entry_matches_host(entry: str, hostname: str, resolved: list[str]) -> bool:
    entry = entry.strip().lower()
    if not entry:
        return False
    # Exact hostname / wildcard suffix
    if entry.startswith("*."):
        suffix = entry[1:]  # ".example.com"
        if hostname.endswith(suffix) or hostname == entry[2:]:
            return True
    if hostname == entry or hostname.rstrip(".") == entry.rstrip("."):
        return True
    # CIDR / single IP
    try:
        network = ipaddress.ip_network(entry, strict=False)
    except ValueError:
        return False
    for addr in resolved:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip in network:
            return True
    return False


def _resolve_ips(hostname: str) -> list[str]:
    """Resolve hostname to IP strings; literal IPs returned as-is."""
    try:
        ipaddress.ip_address(hostname)
        return [hostname]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise EgressDenied(f"DNS resolution failed for '{hostname}': {exc}") from exc
    ips: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr and addr not in ips:
            ips.append(addr)
    if not ips:
        raise EgressDenied(f"no addresses resolved for '{hostname}'")
    return ips


def _is_sensitive_unallowlisted(ip: str, allowlist: list[str]) -> bool:
    """True when IP is loopback/link-local/metadata and not explicitly allowed."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    sensitive = (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or str(addr) == "169.254.169.254"
    )
    if not sensitive:
        # Also treat classic cloud metadata IPv6 if ever resolved
        return False
    # Explicit allow: entry must match this IP (CIDR or exact)
    for entry in allowlist:
        if _entry_matches_host(entry, str(addr), [str(addr)]):
            return False
    return True


def assert_egress_allowed(
    *,
    hostname: str,
    platform_allowlist: str | Iterable[str] | None,
    check_allowlist: str | Iterable[str] | None = None,
    resolve: bool = True,
) -> list[str]:
    """Fail-closed egress gate.

    - Empty platform allowlist → deny all.
    - Hostname (or resolved IPs) must match platform allowlist.
    - Non-empty check allowlist further restricts (intersection).
    - Loopback / link-local / metadata IPs denied unless explicitly allowlisted.
    """
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        raise EgressDenied("empty hostname")

    platform = parse_allowlist(platform_allowlist)
    if not platform:
        raise EgressDenied(
            "egress denied: MONITOR_EGRESS_ALLOWLIST is empty (deny-all)"
        )

    check = parse_allowlist(check_allowlist)
    resolved = _resolve_ips(host) if resolve else []

    if not any(_entry_matches_host(e, host, resolved) for e in platform):
        raise EgressDenied(
            f"egress denied: '{host}' not in platform MONITOR_EGRESS_ALLOWLIST"
        )

    if check and not any(_entry_matches_host(e, host, resolved) for e in check):
        raise EgressDenied(
            f"egress denied: '{host}' not in check egress_allowlist"
        )

    combined = platform + check
    for ip in resolved:
        if _is_sensitive_unallowlisted(ip, combined):
            raise EgressDenied(
                f"egress denied: sensitive address '{ip}' for host '{host}' "
                "(loopback/link-local/metadata require explicit allowlist entry)"
            )

    return resolved
