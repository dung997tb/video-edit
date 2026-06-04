from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


_LOCALHOST_NAMES = {"localhost", "localhost.localdomain"}


def validate_url_access(
    url: str | None,
    *,
    allowed_schemes: set[str],
    allow_private_networks: bool = False,
    field_name: str = "url",
) -> None:
    if not url:
        return
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in allowed_schemes:
        raise ValueError(f"{field_name} scheme is not allowed: {parsed.scheme}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"{field_name} must include a hostname")
    if allow_private_networks:
        return
    if _is_private_hostname(hostname):
        raise ValueError(f"{field_name} host is not allowed: {hostname}")


def _is_private_hostname(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if host in _LOCALHOST_NAMES or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )
