"""SSRF-resistant URL validation for the web fetch step: scheme allowlist,
block private/loopback/link-local/reserved/multicast addresses and localhost.
"""

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeUrlError(Exception):
    """Raised when a URL fails the scheme/private-IP safety check."""


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    """Raises UnsafeUrlError if `url` isn't http(s), or resolves to a
    private/loopback/link-local/reserved/multicast address.

    ponytail: validates then lets the caller connect separately -- it does
    not pin the later connection to the IP checked here, so a DNS-rebinding
    attacker could still redirect the actual request between the two. Fine
    for a first line of defense against opportunistic SSRF targets (cloud
    metadata endpoints, internal services); upgrade to IP-pinned connections
    if this ever fetches from a source untrusted enough for that gap to
    matter.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme not allowed: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("URL has no hostname")
    if hostname.lower() == "localhost":
        raise UnsafeUrlError("localhost is blocked")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"could not resolve host: {hostname!r}") from e

    for info in infos:
        ip = str(info[4][0])
        if not _is_public_ip(ip):
            raise UnsafeUrlError(f"{hostname!r} resolves to a non-public address ({ip})")
