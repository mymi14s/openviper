"""SSRF prevention utilities for AI provider URL validation."""

from __future__ import annotations

import ipaddress
import urllib.parse

PRIVATE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def is_private_address(host: str) -> bool:
    """Return True if *host* resolves to a private or reserved IP address."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in PRIVATE_NETWORKS)


def validate_base_url(
    url: str,
    *,
    allow_localhost: bool = False,
    provider: str = "Provider",
) -> None:
    """Raise ValueError if *url* targets a private address or uses an insecure scheme.

    Args:
        url: Base URL to validate.
        allow_localhost: Permit localhost/loopback addresses (local dev).
        provider: Name used in error messages.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""

    is_local = host in LOCALHOST_HOSTS or "." not in host
    if allow_localhost and is_local:
        return

    if parsed.scheme != "https":
        raise ValueError(f"{provider}: non-localhost base_url must use HTTPS, got {url!r}")

    if is_private_address(host):
        raise ValueError(
            f"{provider}: base_url resolves to a private/reserved address "
            f"({host}), which is not permitted."
        )


def validate_image_url(url: str, *, provider: str = "Provider") -> None:
    """Raise ValueError if *url* is non-HTTPS or targets a private address."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"{provider}: image URL must use HTTPS, got {url!r}")
    host = parsed.hostname or ""
    if is_private_address(host):
        raise ValueError(
            f"{provider}: image URL resolves to a private/reserved address "
            f"({host}), which is not permitted."
        )
