"""Provider adapter failures, raised by src/providers/*_provider.py. Caught
by the `ProviderError` exception handler in src/api/app.py."""

from __future__ import annotations


class ProviderError(Exception):
    code: str
    http_status: int

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(self.code)


class UpstreamUnavailableError(ProviderError):
    """Missing platform key, or the upstream is unreachable. 503, not 500 --
    this is a known, expected failure mode (bad ops config or a downed
    provider), not a bug in this service."""

    code = "UPSTREAM_UNAVAILABLE"
    http_status = 503
