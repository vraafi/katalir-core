"""The single chokepoint for "may this description cause outbound traffic".

Every F3 protocol turns a *user-supplied description* of an API into a real
request: an OpenAPI document supplies URLs, a GraphQL schema supplies a
endpoint, a JS sandbox runs a fetch, an MCP registry entry supplies a transport.
Each of those is an SSRF path, and four separate copies of a blocklist is four
chances to ship the weaker one.

`tools._host_blocked` already does this for the native HTTP tool, and it is
reused rather than reimplemented: a second blocklist would be a second opinion,
and when they disagree nothing tells you which one the new call path uses.

DNS rebinding is the reason this resolves names instead of string-matching. A
prefix check on "10." catches the obvious case, but `internal.example.com` can
resolve to 10.0.0.1 and pass a hostname check outright, so every resolved
address is checked and any single private answer rejects the whole host.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from tools import _host_blocked


class SsrfError(ValueError):
    """Raised when a target is not a public, non-credential-bearing address."""


def is_public_url(url: str) -> tuple[bool, str]:
    """Return ``(allowed, reason)``. ``reason`` is non-empty whenever not allowed.

    Scheme is checked before the host because ``file://`` and ``gopher://`` have
    no host at all, and a host check on them would pass vacuously.
    """
    raw = (url or "").strip()
    if not raw:
        return False, "empty_url"
    try:
        parts = urlparse(raw)
    except Exception:  # noqa: BLE001 - malformed input is a rejection, not a crash
        return False, "unparseable_url"
    scheme = (parts.scheme or "").lower()
    if scheme != "https":
        # http is excluded too: these descriptions are fetched over the network
        # and a plaintext leg makes the guard bypassable by a downgrade.
        return False, f"scheme_not_https:{scheme or 'none'}"
    host = parts.hostname or ""
    if not host:
        return False, "no_host"
    if _host_blocked(host):
        return False, f"non_public_host:{host}"
    return True, "ok"


def require_public_url(url: str) -> str:
    """Return ``url`` unchanged, or raise :class:`SsrfError`.

    Callers use this at the last moment before the socket is opened, so a
    check that passed at import time cannot be stale by the time we connect.
    """
    ok, why = is_public_url(url)
    if not ok:
        raise SsrfError(f"refusing outbound request: {why}")
    return url


def resolve_ips(host: str) -> list[str]:
    """Every address a hostname resolves to. Test/debug helper."""
    try:
        infos = socket.getaddrinfo((host or "").strip("[]"), None)
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in out:
            out.append(addr)
    return out


def is_public_host(host: str) -> bool:
    return _host_blocked(host) is False


__all__ = [
    "is_public_url",
    "require_public_url",
    "is_public_host",
    "resolve_ips",
    "SsrfError",
    "ipaddress",
]